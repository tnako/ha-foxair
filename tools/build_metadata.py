#!/usr/bin/env python3
"""Generate foxair_metadata.json for v0.3 — editable, min/max, group, risk.

Sources: data/foxair_phnix_registers.json + data/foxair_phnix_knowledge.json
Extends with groups identical to FoxAir_Control BLOCK_SHORT and protection tiers.
"""
import json, pathlib, re

ROOT = pathlib.Path(__file__).parents[1]
REG_PATH = ROOT / "custom_components/foxair/data/foxair_phnix_registers.json"
KNOW_PATH = ROOT / "custom_components/foxair/data/foxair_phnix_knowledge.json"
OUT_PATH = ROOT / "custom_components/foxair/data/foxair_metadata.json"

BLOCK_SHORT = {
    "H": "Base/Hardware",
    "A": "Protection/Limits",
    "F": "Fan",
    "D": "Defrost",
    "E": "EVI/EEV",
    "C": "Compressor",
    "R": "Setpoints",
    "T": "Diagnostics/Live",
    "Z": "Zone",
    "G": "Legionella",
    "P": "Pump",
    "SG": "SG Ready",
    "KG": "Timer",
    "ERR": "Fault",
}

# Risk tiers: safe (everyday), advanced (installer), dangerous (can damage/brick)
RISK_BY_BLOCK = {
    "R": "safe",
    "SG": "safe",
    "KG": "safe",
    "G": "advanced",
    "Z": "advanced",
    "P": "advanced",
    "H": "advanced",      # overridden per-addr for H10/H34 etc -> dangerous
    "A": "dangerous",
    "F": "dangerous",
    "D": "dangerous",
    "E": "dangerous",
    "C": "dangerous",
    "T": "safe",          # but read-only
    "ERR": "safe",
}

# Per-address risk overrides (hardware/brick risks)
RISK_OVERRIDES = {
    1024: "dangerous",  # H10 device address 1..32 - bricks bus
    1020: "dangerous",  # H34 ERP test mode
    1019: "dangerous",  # H33 driver integrated
    1027: "dangerous",  # H27 EVI enable
    1054: "dangerous",  # A26 refrigerant type
    1074: "dangerous",  # F10 quantity fan count
    1059: "dangerous",  # F01 fan type
    1086: "advanced",   # F21 timer mute
}

TYPE_TO_PLATFORM = {
    "BLOCK": "sensor",
    "BITFIELD": "sensor",
    "TEMP1": "number", "TEMP": "number", "TEMP05": "number",
    "BAR_X10": "number", "POWER_KW_X10": "number",
    "FLOW_M3H_X100": "number", "FLOW_M3H_X10": "number",
    "VOLT": "sensor", "AMP_X10": "sensor", "AMP_X2": "sensor",
    "HZ": "number", "RPM": "number", "PERCENT": "number", "STEPS_N": "number",
    "WATT": "sensor", "KWH": "sensor", "COP_X100": "sensor",
    "DIGI1": "select", "DIGI4": "select", "DIGI5": "number", "DIGI6": "number", "DIGI19": "number",
    "MINUTES": "number", "SECONDS": "number", "HOURS": "number", "DAYS": "number",
    "TIME_HHMM": "time", "TIMER_BITPAIR": "select", "TIMER_MODE": "select",
    "SG_MODE": "select", "MODE_0_4": "select", "RAW": "number",
}

ICON_BY_BLOCK = {
    "H": "mdi:chip", "A": "mdi:shield-alert", "F": "mdi:fan", "D": "mdi:snowflake-melt",
    "E": "mdi:valve", "C": "mdi:air-conditioner", "R": "mdi:thermometer", "T": "mdi:pulse",
    "Z": "mdi:home-thermometer", "G": "mdi:water-thermometer", "P": "mdi:water-pump",
    "SG": "mdi:power-socket-eu", "KG": "mdi:timer-outline", "ERR": "mdi:alert-circle",
}

def parse_range(desc: str, dtype: str):
    """Try to extract min/max from knowledge description like '60 bis 130°C' or '-40.0 10.0°C'."""
    if not desc:
        return None, None
    d = desc.replace(",", ".").strip()
    # patterns: "X bis Y", "X..Y", "X - Y"
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:bis|..|–|—|-)\s*(-?\d+(?:\.\d+)?)", d)
    if m:
        try:
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            # sanity: ignore absurd ranges like 0..97 handled elsewhere, but keep
            if abs(hi-lo) < 500:
                return lo, hi
        except: pass
    # fallback "1 bis 32" without degree
    m = re.search(r"(\d+)\s*bis\s*(\d+)", d)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except: pass
    return None, None

def default_step(dtype, lo, hi):
    if dtype in ("TEMP1","TEMP","TEMP05","BAR_X10","POWER_KW_X10","FLOW_M3H_X10","FLOW_M3H_X100","DIGI5"):
        return 0.1 if dtype not in ("FLOW_M3H_X100",) else 0.01
    if dtype == "DIGI6": return 0.001
    if dtype == "DIGI19": return 0.01
    if dtype == "DIGI4": return 0.2
    if dtype in ("HZ","RPM","STEPS_N","MINUTES","SECONDS","HOURS","DAYS","PERCENT"): return 1
    if dtype in ("TIME_HHMM",): return 1
    # temperature default 0.5 like climate
    if lo is not None and hi is not None and hi-lo <= 20:
        return 0.5
    return 1

def main():
    regs = json.loads(REG_PATH.read_text(encoding="utf-8-sig"))
    know = json.loads(KNOW_PATH.read_text(encoding="utf-8-sig"))
    out = {}
    for addr_str, rec in regs.items():
        if addr_str.startswith("_"):
            continue
        try:
            addr = int(addr_str)
        except: continue
        if not isinstance(rec, dict):
            continue
        dtype = rec.get("type","RAW")
        code = rec.get("code","")
        block = rec.get("block","") or (re.match(r"^([A-Z]+)", code).group(1) if re.match(r"^([A-Z]+)", code) else "")
        # derive group
        group = BLOCK_SHORT.get(block, "Other" if block else "Header/Reserved")
        if dtype == "BLOCK" or not code:
            group = "Header/Reserved"
        mode = rec.get("mode","read")
        editable = mode == "r/w" and dtype != "BLOCK"
        # platform
        platform = TYPE_TO_PLATFORM.get(dtype, "sensor")
        if not editable:
            platform = "sensor"
        # risk
        risk = RISK_OVERRIDES.get(addr, RISK_BY_BLOCK.get(block, "advanced" if editable else "safe"))
        if dtype == "BLOCK":
            risk = "blocked"
        requires_expert = risk in ("advanced","dangerous") or addr in RISK_OVERRIDES
        if risk == "dangerous":
            requires_expert = True
        # min/max from knowledge
        kd = know.get(addr_str, {}) if isinstance(know.get(addr_str), dict) else {}
        desc = kd.get("description","") if isinstance(kd, dict) else ""
        lo, hi = parse_range(desc, dtype)
        # fallback per type if still None and editable
        if lo is None and editable:
            # generic safe defaults per type to prevent unbounded writes
            fallbacks = {
                "TEMP1": (-30, 60), "TEMP": (-30, 60), "TEMP05": (-30, 60),
                "BAR_X10": (0, 5), "HZ": (20, 130), "PERCENT": (0,100),
                "STEPS_N": (0,500), "RPM": (0,1500), "MINUTES": (0,180), "SECONDS": (0,300),
                "HOURS": (0,24), "DAYS": (0,365), "POWER_KW_X10": (0, 50),
                "DIGI1": (0, 5), "DIGI5": (0, 100), "DIGI6": (0,10), "DIGI19": (0,100),
            }
            if dtype in fallbacks:
                lo, hi = fallbacks[dtype]
        step = default_step(dtype, lo, hi)
        # default value
        default = kd.get("default") if isinstance(kd, dict) else None
        # unit from rec
        unit = rec.get("unit")
        # icon
        icon = ICON_BY_BLOCK.get(block, "mdi:heat-pump")
        if risk == "dangerous":
            icon = "mdi:shield-alert"
        elif risk == "advanced":
            icon = icon  # keep
        # value_map hint
        has_map = bool(rec.get("value_map"))
        out[addr_str] = {
            "addr": addr, "code": code, "block": block, "group": group,
            "editable": editable, "platform": platform, "risk": risk,
            "requires_expert": requires_expert, "type": dtype,
            "unit": unit, "min": lo, "max": hi, "step": step,
            "default": default, "icon": icon, "has_value_map": has_map,
            "name": rec.get("name","")
        }
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    # stats
    from collections import Counter
    c = Counter(v["risk"] for v in out.values())
    p = Counter(v["platform"] for v in out.values() if v["editable"])
    print(f"Wrote {len(out)} entries to {OUT_PATH}")
    print("risk:", dict(c))
    print("editable platform:", dict(p))
    print("editable total:", sum(1 for v in out.values() if v["editable"]))
    print("dangerous editable:", sum(1 for v in out.values() if v["editable"] and v["risk"]=="dangerous"))

if __name__ == "__main__":
    main()
