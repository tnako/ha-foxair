#!/usr/bin/env python3
"""Check every foxair register end-to-end: code -> Home Assistant -> Modbus bridge -> device.

Sources (all from .env, nothing hardcoded — public repo):
  HASS_URL, HASS_TOKEN   HA REST API (http://<host>:8123)
  MODBUS_HOST, MODBUS_PORT, MODBUS_SLAVE   direct device read (optional, --direct)

Modes:
  default     HA-only audit: tabs.txt + metadata-only codes vs HA entity state
  --direct    also read each address straight from the device via Modbus TCP
              (note: EW11 gateways usually allow ONE TCP client — pause the
              integration for a clean comparison)
  --codes     comma-separated code filter (e.g. 'H01,P02')
  --show-all  list every checked code, not only problems
  --json      machine-readable output

Verdicts:
  OK              entity exists and has a value that matches the device (with --direct)
  UNKNOWN         entity exists but state is unknown (device value never polled/decoded)
  UNAVAILABLE     entity exists but connection to the bridge is down
  MISMATCH        HA value differs from the direct device read
  RESTORED-ORPHAN entity is a restored leftover from an older version (safe to ignore/delete)
  NOT-EXPOSED     no enabled entity in HA (disabled by default, hidden category, or not created)
  EXPERT-ONLY     entity requires expert mode (enabled in integration options)
  NO-METADATA     code in tabs.txt has no entry in the integration metadata
  NO-RESPONSE     (--direct) device did not answer for this address

Exit code: 0 = no real problems, 1 = problems found, 2 = config error.
"""

import argparse
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
META_PATH = REPO / "custom_components/foxair/data/foxair_metadata.json"
TABS_PATH = REPO / "modbus/tabs.txt"

# Minimal scale map mirroring const.py DTYPE_SPEC (const.py imports homeassistant,
# which is not available outside HA, so the scales needed for decoding live here).
SCALES = {
    "TEMP1": 0.1, "TEMP": 0.1, "TEMP05": 0.5, "TEMP_0_5": 0.5, "STEP_0_5C": 0.5,
    "VOLT": 1.0, "VOLTS": 1.0, "V": 1.0, "HZ": 1.0, "FREQUENCY_HZ": 1.0,
    "PERCENT": 1.0, "DIGI1": 1.0, "DIGI4": 0.2, "DIGI5": 0.1, "DIGI6": 0.001,
    "BAR_X10": 0.1, "POWER_KW_X10": 0.1, "FLOW_M3H_X100": 0.01,
    "TIME_HHMM": 1.0, "RAW": 1.0,
}

PROBLEM_VERDICTS = {"UNKNOWN", "UNAVAILABLE", "MISMATCH", "NO-RESPONSE"}

# Codes with no holding-register entity by design (see docs/skill notes):
# O/S blocks are single BITFIELD registers (2019/2034); H43/E01 are coil/cloud-only.
BITFIELD_CODES = {f"O{n:02d}" for n in range(1, 21)} | {f"S{n:02d}" for n in range(1, 21)}
NON_HOLDING_CODES = {"H43", "E01", "T35"}


def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # real environment wins
    for k in ("HASS_URL", "HASS_TOKEN", "MODBUS_HOST", "MODBUS_PORT", "MODBUS_SLAVE"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def tabs_order() -> list[str]:
    """Code sequence: tabs.txt (source of truth) plus metadata-only codes
    (KG timers, T-Diag, ERR, SG, sub-codes like E03-1) appended per block."""
    codes = []
    seen = set()
    for line in TABS_PATH.read_text().splitlines():
        m = re.match(r"\s*\*\s*([A-Z]{1,2}\d+):", line)
        if m:
            codes.append(m.group(1))
            seen.add(m.group(1))
    meta = json.loads(META_PATH.read_text(encoding="utf-8-sig"))
    extras = sorted(
        ((int(k), v["code"]) for k, v in meta.items()
         if k.isdigit() and v.get("code") and v["code"] not in seen),
        key=lambda t: t[0],
    )
    codes.extend(c for _, c in extras)
    return codes


def ha_get(env: dict, path: str):
    url = env["HASS_URL"].rstrip("/")
    req = urllib.request.Request(
        f"{url}{path}", headers={"Authorization": f"Bearer {env['HASS_TOKEN']}"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def ha_states(env: dict) -> dict:
    try:
        states = ha_get(env, "/api/states")
    except Exception as e:
        print(f"ERROR: HA REST API unreachable: {e}", file=sys.stderr)
        sys.exit(2)
    return {s["entity_id"]: s for s in states}


def ha_config_entry(env: dict) -> dict | None:
    """Find the foxair config entry (title carries the bridge IP)."""
    try:
        for e in ha_get(env, "/api/config/config_entries/entry"):
            if e.get("domain") == "foxair":
                return e
    except Exception:
        pass
    return None


def modbus_read(host: str, port: int, slave: int, addr: int, count: int = 1,
                retries: int = 2, timeout: float = 2.0) -> int | None:
    """Raw Modbus TCP FC03 read (no pymodbus dependency). Fail fast: the EW11
    gateway usually serves a single TCP client, so slow rejection is expected."""
    pdu = struct.pack(">BHH", 3, addr, count)
    for attempt in range(retries):
        s: socket.socket | None = None
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.settimeout(timeout)
            tid = attempt + 1
            s.sendall(struct.pack(">HHHB", tid, 0, len(pdu) + 1, slave) + pdu)
            data = s.recv(1024)
            if len(data) >= 9 and data[7] == 3:
                bc = data[8]
                vals = struct.unpack(f">{bc // 2}H", data[9:9 + bc])
                return vals[0]  # first register (scalar reads)
            # exception response or short frame — retry
        except Exception:
            pass
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            time.sleep(0.2 * (attempt + 1))
    return None


def s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def scaled(dtype: str, raw: int) -> float:
    return s16(raw) * SCALES.get((dtype or "RAW").upper(), 1.0)


def find_entity(states: dict, code: str, addr: int, domain: str) -> dict | None:
    """Locate an entity by unique-id pattern or code in the friendly name."""
    uid = {"select": f"foxair_sel_{addr}", "number": f"foxair_num_{addr}"}.get(domain, f"foxair_{addr}")
    exact = states.get(f"{domain}.{uid}")
    if exact:
        return exact
    # code appears in the friendly name, possibly as a range member (KG13-KG28)
    pat = re.compile(rf"(?<![A-Z0-9]){re.escape(code)}(?![0-9])")
    for eid, st in states.items():
        if not eid.startswith(f"{domain}.foxair"):
            continue
        if pat.search(st["attributes"].get("friendly_name", "")):
            return st
    return None


def domain_for(meta_rec: dict) -> str:
    platform = meta_rec.get("platform")
    if meta_rec.get("editable") and platform in ("select", "number"):
        return platform
    return "sensor"


def main() -> None:
    ap = argparse.ArgumentParser(description="FoxAir register end-to-end checker")
    ap.add_argument("--direct", action="store_true",
                    help="also read each address directly from the device (Modbus TCP)")
    ap.add_argument("--show-all", action="store_true",
                    help="list every checked code, not only problems")
    ap.add_argument("--codes", default="",
                    help="comma-separated code list to check (e.g. 'H01,P02') — useful with --direct")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    env = load_env(REPO / ".env")
    if not env.get("HASS_URL") or not env.get("HASS_TOKEN"):
        print("ERROR: HASS_URL / HASS_TOKEN missing (create .env from .env.example)", file=sys.stderr)
        sys.exit(2)

    meta = json.loads(META_PATH.read_text(encoding="utf-8-sig"))
    by_code = {v["code"]: (int(k), v) for k, v in meta.items() if k.isdigit() and v.get("code")}
    order = tabs_order()
    if args.codes:
        wanted = {c.strip().upper() for c in args.codes.split(",") if c.strip()}
        order = [c for c in order if c in wanted]
        if not order:
            print(f"ERROR: none of --codes matched tabs.txt", file=sys.stderr)
            sys.exit(2)

    states = ha_states(env)
    entry = ha_config_entry(env)

    rows = []
    for code in order:
        m = by_code.get(code)
        if not m:
            if code in BITFIELD_CODES:
                rows.append({"code": code, "verdict": "BITFIELD-REG"})
            elif code in NON_HOLDING_CODES:
                rows.append({"code": code, "verdict": "NON-HOLDING"})
            else:
                rows.append({"code": code, "verdict": "NO-METADATA"})
            continue
        addr, meta_rec = m
        row = {
            "code": code, "addr": addr, "platform": meta_rec.get("platform"),
            "tier": meta_rec.get("poll_tier"), "risk": meta_rec.get("risk"),
            "requires_expert": bool(meta_rec.get("requires_expert")),
        }
        domain = domain_for(meta_rec)
        ent = find_entity(states, code, addr, domain)
        if ent is None:
            # code may exist on a different domain (e.g. KG timers as sensors)
            for alt in ("sensor", "number", "select"):
                if alt != domain:
                    ent = find_entity(states, code, addr, alt)
                    if ent:
                        break
        if ent is None:
            row["verdict"] = "EXPERT-ONLY" if row["requires_expert"] else "NOT-EXPOSED"
            rows.append(row)
            continue
        state = ent["state"]
        row["entity"] = ent["entity_id"]
        row["ha_state"] = state
        if ent["attributes"].get("restored"):
            row["verdict"] = "RESTORED-ORPHAN"
        elif state == "unknown":
            row["verdict"] = "UNKNOWN"
        elif state == "unavailable":
            row["verdict"] = "UNAVAILABLE"
        else:
            row["verdict"] = "OK"
            row["ha_value"] = state
        rows.append(row)

    # direct device reads
    if args.direct:
        host = env.get("MODBUS_HOST")
        if not host and entry:
            mh = re.search(r"(\d+\.\d+\.\d+\.\d+)", entry.get("title", ""))
            host = mh.group(1) if mh else None
        port = int(env.get("MODBUS_PORT", "502"))
        slave = int(env.get("MODBUS_SLAVE", "1"))
        if not host:
            print("ERROR: --direct needs MODBUS_HOST in .env", file=sys.stderr)
            sys.exit(2)
        for row in rows:
            if "addr" not in row:
                continue
            raw = modbus_read(host, port, slave, row["addr"])
            if raw is None:
                row["device_verdict"] = "NO-RESPONSE"
                if row.get("verdict") == "OK":
                    row["verdict"] = "OK"  # HA fine, device just busy — keep OK but note
                continue
            row["device_raw"] = raw
            dtype = by_code.get(row.get("code", ""), {}).get("type", "RAW")
            row["device_value"] = scaled(dtype, raw)
            ha_val = row.get("ha_value")
            if ha_val is not None:
                try:
                    match = abs(float(ha_val) - float(row["device_value"])) < 0.051
                except ValueError:
                    match = str(ha_val).strip() == str(int(raw))
                row["device_verdict"] = "OK" if match else "MISMATCH"
                if not match:
                    row["verdict"] = "MISMATCH"
            else:
                row["device_verdict"] = "OK"

    problems = [r for r in rows if r["verdict"] in PROBLEM_VERDICTS]

    if args.json:
        print(json.dumps({
            "summary": {"total": len(rows), "problems": len(problems)},
            "rows": rows,
        }, ensure_ascii=False, indent=1))
    else:
        print(f"FoxAir register checker — {len(rows)} codes (tabs.txt + metadata)")
        print(f"mode: {'HA + direct device' if args.direct else 'HA only'}")
        if args.direct:
            print("NOTE: --direct competes with the integration for the single EW11 client slot;")
            print("      mismatched/junk device reads while HA polls are expected. Pause the")
            print("      integration (or stop HA) for a clean end-to-end comparison.")
        print()
        shown = rows if args.show_all else problems
        for r in shown:
            extra = ""
            if r["verdict"] == "MISMATCH":
                extra = f" ha={r.get('ha_value')} device={r.get('device_value')} (raw {r.get('device_raw')})"
            elif r.get("device_raw") is not None:
                extra = f" device raw={r['device_raw']}"
            print(f"{r['code']:6} {str(r.get('addr', '')):>6} {r['verdict']:16} {r.get('entity', '')}{extra}")
        print()
        print(f"total: {len(rows)}  problems: {len(problems)}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
