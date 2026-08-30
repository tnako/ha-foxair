#!/usr/bin/env python3
"""Generate foxair_metadata.json — editable, min/max, group, risk, poll_tier.

Sources: data/foxair_phnix_registers.json + data/foxair_phnix_knowledge.json
         + data/foxair_config.json (blocks, types, markers, per-register overrides)

All integration-wide tables (blocks, types, risk tiers, poll tiers, dead ranges,
icons, per-address overrides) now live in foxair_config.json so they can be
tuned without touching Python. This script is the generator only.

Run: python3 tools/build_metadata.py  (see tools/README.md)
"""
import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
REG_PATH = ROOT / "custom_components/foxair/data/foxair_phnix_registers.json"
KNOW_PATH = ROOT / "custom_components/foxair/data/foxair_phnix_knowledge.json"
CFG_PATH = ROOT / "custom_components/foxair/data/foxair_config.json"
OUT_PATH = ROOT / "custom_components/foxair/data/foxair_metadata.json"

# Addresses without a block/code in register json that belong to Diagnostics/Live.
BLOCK_T_LIVE = {2125, 2126, 2127, 2128, 2136, 2137, 2138, 2178, 2179, 2180}
# Orphan core-control addresses that must stay non-expert (used by climate/curve):
CORE_NON_EXPERT_ADDRS = {1011, 1012, 1013, 1014, 1015, 1016, 1017,
                         1212, 1213, 1214, 1234, 1235}


def load_config():
    return json.loads(CFG_PATH.read_text(encoding="utf-8-sig"))


CFG = load_config()
BLOCKS = CFG["blocks"]
TYPES = CFG["types"]
MARKERS = CFG["markers"]
OVERRIDES = {int(k): v for k, v in MARKERS["overrides"].items()}
EXPERT_BLOCKS = set(BLOCKS["expert_blocks"])
RISK_BY_BLOCK = BLOCKS["risk_by_block"]
ICON_BY_BLOCK = BLOCKS["icons"]
APP_TAB_TITLES = BLOCKS["labels"]
BLOCK_SHORT = BLOCKS["labels"]
TYPE_TO_PLATFORM = {t: spec.get("platform", "sensor") for t, spec in TYPES.items() if isinstance(spec, dict)}
# const.py keeps its own DTYPE_SPEC; derive defaults from config types table


def parse_range(desc: str, dtype: str):
    """Try to extract min/max from knowledge description like '60 bis 130°C' or '-40.0 10.0°C'."""
    if not desc:
        return None, None
    d = desc.replace(",", ".").strip()
    # must be pure numeric bis numeric, not "R10 bis R11"
    if re.search(r"R\d", d):
        return None, None  # limit regs like R10..R11 are interdependent, not absolute
    # skip BLOCK type already handled outside, but also skip hex like 0x0210
    if "0x" in d.lower():
        return None, None
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:bis|..|–|—|-)\s*(-?\d+(?:\.\d+)?)", d)  # .. = any-2-chars (original regex behavior)
    if m:
        try:
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            if hi - lo < 0.01:
                return None, None  # degenerate 0-0
            if abs(hi - lo) < 500 and abs(lo) < 500 and abs(hi) < 500:
                return lo, hi
        except Exception:
            pass
    return None, None


def default_step(dtype, lo, hi):
    if dtype in ("TEMP1", "TEMP", "TEMP05", "BAR_X10", "POWER_KW_X10", "FLOW_M3H_X10", "FLOW_M3H_X100", "DIGI5"):
        return 0.1 if dtype not in ("FLOW_M3H_X100",) else 0.01
    if dtype == "DIGI6":
        return 0.001
    if dtype == "DIGI19":
        return 0.01
    if dtype == "DIGI4":
        return 0.2
    if dtype in ("HZ", "RPM", "STEPS_N", "MINUTES", "SECONDS", "HOURS", "DAYS", "PERCENT"):
        return 1
    if dtype in ("TIME_HHMM",):
        return 1
    # temperature default 0.5 like climate
    if lo is not None and hi is not None and hi - lo <= 20:
        return 0.5
    return 1


def poll_tier_for(addr: int, block: str, typ: str, risk: str, ov: dict) -> str:
    """Resolve the poll tier for an address.

    Order: explicit per-register override > T_QUICK-equivalent > T_MEDIUM-equivalent
    > block-based rule. The quick/medium address sets are encoded as poll_tier
    overrides in foxair_config.json, so the first check covers them.
    """
    if "poll_tier" in ov:
        return ov["poll_tier"]
    if block == "T":
        # remaining T -> medium (secondary diagnostics); primary T quick is set via override
        return "medium"
    if block == "R":
        return "quick"
    if typ == "KWH":
        return "medium"
    if block in ("H", "A", "C", "F", "D", "E", "Z", "G", "P", "SG", "KG", "S", "ERR", "O") or risk == "blocked":
        return "rare"
    if block == "":
        return "rare"
    return "rare"


def main():
    regs = json.loads(REG_PATH.read_text(encoding="utf-8-sig"))
    know = json.loads(KNOW_PATH.read_text(encoding="utf-8-sig"))
    out = {}
    for addr_str, rec in regs.items():
        if addr_str.startswith("_"):
            continue
        try:
            addr = int(addr_str)
        except (ValueError, TypeError):
            continue
        if not isinstance(rec, dict):
            continue
        dtype = rec.get("type", "RAW")
        code = rec.get("code", "")
        block = rec.get("block", "") or (re.match(r"^([A-Z]+)", code).group(1) if re.match(r"^([A-Z]+)", code) else "")
        # 2178-2180 humidity/dewpoint + 2125-2138 energy/T live without block have no block/code in register json — assign to Diagnostics/Live
        if addr in BLOCK_T_LIVE:
            block = "T"
        tab = rec.get("tab") or block
        # derive group from app tab when available
        group = APP_TAB_TITLES.get(tab, BLOCK_SHORT.get(block, "Other" if block else "Header/Reserved"))
        if dtype == "BLOCK" or (not code and addr not in BLOCK_T_LIVE):
            group = "Header/Reserved"
        mode = rec.get("mode", "read")
        editable = mode == "r/w" and dtype != "BLOCK"
        # platform
        platform = TYPE_TO_PLATFORM.get(dtype, "sensor")
        if not editable:
            platform = "sensor"
        # per-register overrides (risk, poll_tier, range, block, etc.)
        ov = OVERRIDES.get(addr, {})
        # risk
        risk = ov.get("risk", RISK_BY_BLOCK.get(block, "advanced" if editable else "safe"))
        if dtype == "BLOCK":
            risk = "blocked"
        # Write-only registers (FC16) that don't respond to FC03 reads — mark blocked
        if str(addr) in OVERRIDES and OVERRIDES[addr].get("risk") == "blocked":
            risk = "blocked"
        # block override
        if "block" in ov:
            block = ov["block"]
            tab = ov.get("tab", block)
            group = APP_TAB_TITLES.get(tab, BLOCK_SHORT.get(block, "Other" if block else "Header/Reserved"))
            if dtype == "BLOCK":
                group = "Header/Reserved"
        requires_expert = risk == "dangerous" or block in EXPERT_BLOCKS
        # Orphan addrs without block/code (reserved / header / factory-test leftovers)
        # are expert-only, EXCEPT core control/curve addrs used by climate & main device.
        if not block and not code and addr not in CORE_NON_EXPERT_ADDRS:
            requires_expert = True
        # min/max from knowledge
        kd = know.get(addr_str, {}) if isinstance(know.get(addr_str), dict) else {}
        desc = kd.get("description", "") if isinstance(kd, dict) else ""
        lo, hi = parse_range(desc, dtype)
        # fallback per type if still None and editable
        if lo is None and editable:
            fallbacks = {
                "TEMP1": (-30, 60), "TEMP": (-30, 60), "TEMP05": (-30, 60),
                "BAR_X10": (0, 5), "HZ": (20, 130), "PERCENT": (0, 100),
                "STEPS_N": (0, 500), "RPM": (0, 1500), "MINUTES": (0, 180), "SECONDS": (0, 300),
                "HOURS": (0, 24), "DAYS": (0, 365), "POWER_KW_X10": (0, 50),
                "DIGI1": (0, 5), "DIGI5": (0, 10), "DIGI6": (0, 10), "DIGI19": (0, 100),
            }
            if dtype in fallbacks:
                lo, hi = fallbacks[dtype]
        # explicit per-address range override (displayed units)
        if "min" in ov:
            lo = ov["min"]
        if "max" in ov:
            hi = ov["max"]
        step = default_step(dtype, lo, hi)
        # default value
        default = kd.get("default") if isinstance(kd, dict) else None
        # unit from rec
        unit = rec.get("unit")
        # icon
        icon = ICON_BY_BLOCK.get(block, "mdi:heat-pump")
        if risk == "dangerous":
            icon = "mdi:shield-alert"
        # value_map hint
        has_map = bool(rec.get("value_map"))
        tier = poll_tier_for(addr, block, dtype, risk, ov)
        out[addr_str] = {
            "addr": addr, "code": code, "block": block, "tab": tab, "group": group,
            "editable": editable, "platform": platform, "risk": risk,
            "requires_expert": requires_expert, "type": dtype,
            "unit": unit, "min": lo, "max": hi, "step": step,
            "default": default, "icon": icon, "has_value_map": has_map,
            "name": rec.get("name", ""), "poll_tier": tier
        }
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    # stats
    from collections import Counter
    c = Counter(v["risk"] for v in out.values())
    p = Counter(v["platform"] for v in out.values() if v["editable"])
    t = Counter(v.get("poll_tier", "rare") for v in out.values())
    print(f"Wrote {len(out)} entries to {OUT_PATH}")
    print("risk:", dict(c))
    print("editable platform:", dict(p))
    print("tier:", dict(t))
    print("editable total:", sum(1 for v in out.values() if v["editable"]))
    print("dangerous editable:", sum(1 for v in out.values() if v["editable"] and v["risk"] == "dangerous"))


if __name__ == "__main__":
    main()
