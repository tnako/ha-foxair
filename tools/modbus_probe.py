#!/usr/bin/env python3
"""Live Modbus probe for a FoxAir/PHNIX unit: read, verified write with restore, unit scan.

Host, port and unit id come from .env or the environment only (MODBUS_HOST,
MODBUS_PORT, MODBUS_SLAVE) or --host/--port/--unit; nothing is hardcoded
(public repo). The bridge accepted this client next to a running
integration in testing, but keep sessions short.

Bridge quirk (USR-DR164 / EW11): the first request after a new connect is often
dropped. The probe keeps ONE socket open, retries every request and paces
requests 0.35 s apart, so a timeout here means the unit really did not answer.

Usage:
  tools/modbus_probe.py read 2104 1250:6 2014
  tools/modbus_probe.py write 1236=2 --watch 2014 --restore
  tools/modbus_probe.py write 1464=18.0 1465=1 --watch 2146 --until-bit 4 --timeout 120 --restore
  tools/modbus_probe.py scan

Values are scaled with the register type from foxair_metadata.json
(TEMP1 = 0.1 degC etc.); pass --raw to read/write raw words.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META_PATH = ROOT / "custom_components/foxair/data/foxair_metadata.json"
TYPES_PATH = ROOT / "custom_components/foxair/data/foxair_config.json"
PACE_S = 0.35


def load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("MODBUS_HOST", "MODBUS_PORT", "MODBUS_SLAVE"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def s16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


class Probe:
    def __init__(self, host: str, port: int, unit: int, timeout: float = 2.5, tries: int = 4):
        self.unit, self.tries = unit, tries
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(timeout)
        self.tid = 0

    def close(self) -> None:
        self.sock.close()

    def _request(self, pdu: bytes, fc: int, unit: int | None = None) -> bytes:
        unit = self.unit if unit is None else unit
        for _ in range(self.tries):
            self.tid = (self.tid + 1) & 0xFFFF
            try:
                self.sock.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, unit) + pdu)
                buf = b""
                while True:
                    chunk = self.sock.recv(512)
                    if not chunk:
                        raise ConnectionError("bridge closed the connection")
                    buf += chunk
                    if len(buf) >= 9 and buf[7] == fc | 0x80:
                        raise RuntimeError(f"Modbus exception {buf[8]} (fc {fc})")
                    if fc == 3 and len(buf) >= 9 and buf[7] == 3 and len(buf) >= 9 + buf[8]:
                        time.sleep(PACE_S)
                        return buf
                    if fc == 16 and len(buf) >= 12 and buf[7] == 16:
                        time.sleep(PACE_S)
                        return buf
            except socket.timeout:
                time.sleep(0.5)
        raise TimeoutError(f"no answer after {self.tries} tries (fc {fc})")

    def read(self, addr: int, count: int = 1, unit: int | None = None) -> list[int]:
        buf = self._request(struct.pack(">BHH", 3, addr, count), 3, unit)
        return list(struct.unpack(f">{buf[8] // 2}H", buf[9:9 + buf[8]]))

    def write(self, addr: int, words: list[int]) -> None:
        words = [w & 0xFFFF for w in words]
        pdu = struct.pack(">BHHB", 16, addr, len(words), 2 * len(words)) + b"".join(struct.pack(">H", w) for w in words)
        self._request(pdu, 16)


class Scaler:
    def __init__(self, raw: bool):
        self.raw = raw
        self.meta = json.loads(META_PATH.read_text(encoding="utf-8-sig")) if META_PATH.exists() else {}
        cfg = json.loads(TYPES_PATH.read_text(encoding="utf-8-sig")) if TYPES_PATH.exists() else {}
        self.scales = {t: (s or {}).get("scale", 1.0) for t, s in cfg.get("types", {}).items() if isinstance(s, dict)}

    def _scale(self, addr: int) -> float:
        return 1.0 if self.raw else float(self.scales.get((self.meta.get(str(addr)) or {}).get("type") or "RAW", 1.0) or 1.0)

    def label(self, addr: int) -> str:
        m = self.meta.get(str(addr)) or {}
        return f"{m.get('code') or '-':<6} {m.get('name', '')[:48]}"

    def to_value(self, addr: int, raw: int):
        sc = self._scale(addr)
        return raw if sc == 1.0 else round(s16(raw) * sc, 3)

    def to_raw(self, addr: int, value: float) -> int:
        return int(round(value / self._scale(addr))) & 0xFFFF


def parse_spans(tokens: list[str]) -> list[tuple[int, int]]:
    spans = []
    for t in tokens:
        a, _, n = t.partition(":")
        spans.append((int(a), int(n or 1)))
    return spans


def cmd_read(p: Probe, sc: Scaler, args) -> int:
    for addr, count in parse_spans(args.addrs):
        for i, raw in enumerate(p.read(addr, count)):
            a = addr + i
            print(f"{a:>5}  raw={raw:<6} value={sc.to_value(a, raw)!s:<10} {sc.label(a)}")
    return 0


def cmd_write(p: Probe, sc: Scaler, args) -> int:
    targets = []
    for t in args.assignments:
        a, _, v = t.partition("=")
        targets.append((int(a), float(v)))
    watch = args.watch
    original = {a: p.read(a)[0] for a, _ in targets}
    before = p.read(watch)[0] if watch is not None else None
    print(f"snapshot: {original}" + (f", watch {watch}={before}" if watch is not None else ""))
    rc = 0
    try:
        for a, v in targets:
            raw = sc.to_raw(a, v)
            p.write(a, [raw])
            back = p.read(a)[0]
            ok = back == raw
            rc |= 0 if ok else 1
            print(f"write {a}={v} raw={raw} readback={back} {'OK' if ok else 'MISMATCH'}")
        if watch is not None:
            t0 = time.monotonic()
            last = None
            while time.monotonic() - t0 < args.timeout:
                cur = p.read(watch)[0]
                if cur != last:
                    print(f"  t+{time.monotonic() - t0:5.1f}s {watch}: raw={cur} value={sc.to_value(watch, cur)}"
                          + (f" bit{args.until_bit}={cur >> args.until_bit & 1}" if args.until_bit is not None else ""))
                    last = cur
                if args.until_bit is not None and cur >> args.until_bit & 1:
                    break
                if args.until_bit is None and cur != before:
                    break
                time.sleep(args.interval)
            else:
                print(f"  {watch} did not change within {args.timeout}s")
                rc |= 2
    finally:
        if args.restore:
            for a, raw in original.items():
                p.write(a, [raw])
            restored = {a: p.read(a)[0] for a in original}
            print(f"restored: {restored} {'OK' if restored == original else 'MISMATCH'}")
            rc |= 0 if restored == original else 4
    return rc


def cmd_scan(p: Probe, sc: Scaler, args) -> int:
    fw_addr = 2104
    found = False
    for unit in list(range(0, 17)) + [99, 247]:
        try:
            raw = p.read(fw_addr, 1, unit=unit)[0]
        except (TimeoutError, RuntimeError):
            continue
        found = True
        print(f"unit {unit}: 2104 = {raw} (firmware v{raw // 10}.{raw % 10})")
    return 0 if found else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Live Modbus probe for a FoxAir/PHNIX unit")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--unit", type=int)
    ap.add_argument("--raw", action="store_true", help="no scaling: read/write raw words")
    ap.add_argument("--tries", type=int, default=4)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", help="read ADDR or ADDR:COUNT ...")
    r.add_argument("addrs", nargs="+")
    w = sub.add_parser("write", help="write ADDR=VALUE ... (FC16), verify read-back")
    w.add_argument("assignments", nargs="+")
    w.add_argument("--watch", type=int, help="register whose change proves the effect")
    w.add_argument("--until-bit", type=int, help="with --watch: wait until this bit is set")
    w.add_argument("--timeout", type=float, default=60)
    w.add_argument("--interval", type=float, default=5)
    w.add_argument("--restore", action="store_true", help="write the snapshot back afterwards")
    sub.add_parser("scan", help="find answering unit ids (reads 2104)")
    args = ap.parse_args()

    env = load_env()
    host = args.host or env.get("MODBUS_HOST")
    if not host:
        print("ERROR: set MODBUS_HOST in .env (see .env.example) or pass --host", file=sys.stderr)
        return 2
    port = args.port or int(env.get("MODBUS_PORT") or 502)
    unit = args.unit if args.unit is not None else int(env.get("MODBUS_SLAVE") or 1)
    probe = Probe(host, port, unit, tries=args.tries)
    try:
        return {"read": cmd_read, "write": cmd_write, "scan": cmd_scan}[args.cmd](probe, Scaler(args.raw), args)
    finally:
        probe.close()


if __name__ == "__main__":
    sys.exit(main())
