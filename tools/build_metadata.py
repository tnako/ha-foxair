#!/usr/bin/env python3
"""Generate foxair_metadata.json — editable, min/max, group, risk.

Sources: data/foxair_phnix_registers.json + data/foxair_phnix_knowledge.json
Extends with groups identical to FoxAir_Control BLOCK_SHORT and protection tiers.
Run: python3 tools/build_metadata.py  (see tools/README.md)
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
APP_TAB_TITLES = {
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

# Whole tabs that are expert-only (hidden entirely until expert mode is on).
# Normal mode keeps: main device, R Setpoints, T Diagnostics/Live, SG Ready, KG Timer, ERR Fault.
EXPERT_BLOCKS = {"H", "A", "F", "D", "E", "C", "P", "Z", "G"}

# Risk tiers: safe (everyday), advanced (installer/normal config, visible in CONFIG), dangerous (can damage/brick -> expert only)
RISK_BY_BLOCK = {
    "R": "safe",       # setpoints: target/min/max temps
    "SG": "safe",       # SG Ready modes
    "KG": "safe",       # timer
    "G": "advanced",    # legionella/disinfection
    "Z": "advanced",    # zones
    "P": "advanced",    # pump
    "H": "advanced",    # base/hardware (most are normal config; truly dangerous ones overridden below)
    "A": "advanced",    # protection/limits (normal tuning; dangerous ones overridden)
    "F": "advanced",    # fan
    "D": "advanced",    # defrost
    "E": "advanced",    # EVI/EEV
    "C": "advanced",    # compressor
    "T": "safe",        # but read-only
    "ERR": "safe",      # fault read-only
    "S": "safe",        # switches read-only
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
    # Heating-curve controls are safe, everyday user settings (NOT hardware/brick risks):
    1234: "safe",       # AT-compensation slope
    1235: "safe",       # AT-compensation offset
    1236: "safe",       # H36 fixed vs AT-compensation mode selector
    # Heating setpoint limits are safe installer/end-user settings:
    1158: "safe",       # R02 heating target temp
    1164: "safe",       # R10 min heating target temp
    1165: "safe",       # R11 max heating target temp
    1157: "safe",       # R01 DHW target temp
    1159: "safe",       # R03 cooling target temp
}

# Per-address min/max overrides (DISPLAYED/scaled units) for entities whose
# generic per-type fallback is too wide. Applied after parse_range + fallback.
RANGE_OVERRIDES = {
    1234: (0.0, 3.5),     # AT-compensation slope: 0..3.5 per °C (DIGI5 /10)
}

# Poll tiers — controls bus load. 30s quick (curve/COP/main temps), 120s medium (secondary live), 300s rare (config/H/A etc).
# Tunable via JSON without code change: build_metadata emits poll_tier per addr.
POLL_TIER_OVERRIDES = {
    # quick: power/mode + curve + R setpoints are handled via block check below, but explicit for clarity
    1011: "quick", 1012: "quick", 1234: "quick", 1235: "quick", 1236: "quick",
}
# T secondary that should be medium (primary T is quick)
T_MEDIUM = {1070,1072,1075,1076,1205,1212,1213,2029,2030,2031,2032,2037,2038,2039,2047,2050,2055,2061,2063,2064,2065,2066,2067,2071,2072,2073,2074,2075,2076,2078,2079,2118,2120,2122,2124,2125,2126,2127,2128,2130,2131,2132}
T_QUICK = {2013,2014,2016,2035,2036,2042,2043,2044,2045,2046,2048,2049,2051,2052,2053,2054,2058,2059,2060,2062,2069,2077,2136,2137,2138,2178,2179,2180}

def poll_tier_for(addr: int, block: str, typ: str, risk: str) -> str:
    if addr in POLL_TIER_OVERRIDES:
        return POLL_TIER_OVERRIDES[addr]
    if addr in T_QUICK:
        return "quick"
    if addr in T_MEDIUM:
        return "medium"
    if block == "T":
        # remaining T -> medium (secondary diagnostics)
        return "medium"
    if block == "R":
        return "quick"
    if typ == "KWH":
        return "medium"
    if block in ("H","A","C","F","D","E","Z","G","P","SG","KG","S","ERR") or risk == "blocked":
        return "rare"
    if block == "":
        return "rare"
    return "rare"

TYPE_TO_PLATFORM = {
    "BLOCK": "sensor",
    "BITFIELD": "sensor",
    "ASCII": "sensor",
    "U16": "sensor",
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
    # must be pure numeric bis numeric, not "R10 bis R11"
    if re.search(r"R\d", d):
        # limit regs like R10..R11 are interdependent, not absolute - fallback
        return None, None
    # skip BLOCK type already handled outside, but also skip hex like 0x0210
    if "0x" in d.lower():
        return None, None
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:bis|..|–|—|-)\s*(-?\d+(?:\.\d+)?)", d)
    if m:
        try:
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            if hi-lo < 0.01:
                return None, None  # degenerate 0-0
            if abs(hi-lo) < 500 and abs(lo) < 500 and abs(hi) < 500:
                return lo, hi
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
        # 2178-2180 humidity/dewpoint + 2125-2138 energy/T live without block have no block/code in register json — assign to Diagnostics/Live
        if addr in (2125, 2126, 2127, 2128, 2136, 2137, 2138, 2178, 2179, 2180):
            block = "T"
        tab = rec.get("tab") or block
        # derive group from app tab when available
        group = APP_TAB_TITLES.get(tab, BLOCK_SHORT.get(block, "Other" if block else "Header/Reserved"))
        if dtype == "BLOCK" or (not code and addr not in (2125, 2126, 2127, 2128, 2136, 2137, 2138, 2178, 2179, 2180)):
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
        requires_expert = risk == "dangerous" or block in EXPERT_BLOCKS
        # Orphan addrs without block/code (reserved / header / factory-test leftovers)
        # are expert-only, EXCEPT core control/curve addrs used by climate & main device:
        # 1011-1017 On/Off+mode, 1212-1214 offsets, 1234-1235 curve slope/offset.
        if not block and not code and addr not in (
            1011, 1012, 1013, 1014, 1015, 1016, 1017,
            1212, 1213, 1214, 1234, 1235,
        ):
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
                "DIGI1": (0, 5), "DIGI5": (0, 10), "DIGI6": (0,10), "DIGI19": (0,100),
            }
            if dtype in fallbacks:
                lo, hi = fallbacks[dtype]
        # explicit per-address range override (displayed units)
        if addr in RANGE_OVERRIDES:
            lo, hi = RANGE_OVERRIDES[addr]
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
        tier = poll_tier_for(addr, block, dtype, risk)
        out[addr_str] = {
            "addr": addr, "code": code, "block": block, "tab": tab, "group": group,
            "editable": editable, "platform": platform, "risk": risk,
            "requires_expert": requires_expert, "type": dtype,
            "unit": unit, "min": lo, "max": hi, "step": step,
            "default": default, "icon": icon, "has_value_map": has_map,
            "name": rec.get("name",""), "poll_tier": tier
        }
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    # stats
    from collections import Counter
    c = Counter(v["risk"] for v in out.values())
    p = Counter(v["platform"] for v in out.values() if v["editable"])
    t = Counter(v.get("poll_tier","rare") for v in out.values())
    print(f"Wrote {len(out)} entries to {OUT_PATH}")
    print("risk:", dict(c))
    print("editable platform:", dict(p))
    print("tier:", dict(t))
    print("editable total:", sum(1 for v in out.values() if v["editable"]))
    print("dangerous editable:", sum(1 for v in out.values() if v["editable"] and v["risk"]=="dangerous"))

if __name__ == "__main__":
    main()
