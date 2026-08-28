#!/usr/bin/env python3
"""Generate foxair_modbus vendor package from register JSON."""
import json, pathlib, re, textwrap

ROOT = pathlib.Path(__file__).parents[1]
REG_PATH = ROOT / "custom_components/foxair/data/foxair_phnix_registers.json"
OUT_DIR = ROOT / "custom_components/foxair/vendor/foxair_modbus"
OUT_FILE = OUT_DIR / "heat_pump.py"

# map dtype -> (field_type, scale, unit_default)
# field_type: gauge=>scaled float, integer=>int, raw_register=>raw
DTYPE_SCALE = {
    "TEMP": 0.1,
    "TEMP1": 0.1,
    "TEMP05": 0.5,
    "DIGI5": 0.1,
    "POWER_KW_X10": 0.1,
    "BAR_X10": 0.1,
    "FLOW_M3H_X10": 0.1,
    "AMP_X10": 0.1,
    "FLOW_M3H_X100": 0.01,
    "COP_X100": 0.01,
    "AMP_X2": 0.5,
    "DIGI6": 0.001,
    "DIGI19": 0.01,
    "DIGI4": 0.2,
}

# types that should be integer (no scaling) but still signed
INT_TYPES = {"DIGI1","MODE_0_4","SG_MODE","TIMER_BITPAIR","TIMER_MODE","BITFIELD","STEPS_N","HZ","RPM","PERCENT","KWH","WATT","VOLT","MINUTES","SECONDS","HOURS","DAYS","RAW","BLOCK"}

def field_for(addr: int, rec: dict):
    dtype = rec.get("type","RAW")
    mode = rec.get("mode","read")
    writable = (mode == "r/w" and dtype != "BLOCK")
    unit = rec.get("unit") or None
    # code for comment
    code = rec.get("code","")
    name = rec.get("name","")
    # sanitize python attribute: addr_<addr> for uniqueness; also add code alias if exists and unique
    attr = f"reg_{addr}"
    # Determine field call
    # TIME_HHMM special: keep as raw integer, we'll decode elsewhere
    if dtype == "TIME_HHMM":
        return f'    {attr} = integer({addr}, signed=False, writable={writable})  # {code} {dtype} {name}', dtype, writable
    if dtype in DTYPE_SCALE:
        scale = DTYPE_SCALE[dtype]
        # use gauge with scale; for writable set True
        unit_str = f', unit="{unit}"' if unit else ''
        return f'    {attr} = gauge({addr}, {scale}, writable={writable}{unit_str})  # {code} {dtype} {name}', dtype, writable
    if dtype in ("VOLT","WATT","RPM","KWH","HZ","PERCENT","STEPS_N","MINUTES","SECONDS","HOURS","DAYS","RAW"):
        # gauge with scale 1
        unit_str = f', unit="{unit}"' if unit else ''
        return f'    {attr} = gauge({addr}, 1.0, writable={writable}{unit_str})  # {code} {dtype}', dtype, writable
    if dtype in ("DIGI1","MODE_0_4","SG_MODE","TIMER_BITPAIR","TIMER_MODE","BITFIELD"):
        # integer raw
        return f'    {attr} = integer({addr}, signed=True, writable={writable})  # {code} {dtype}', dtype, writable
    # fallback
    return f'    {attr} = integer({addr}, signed=True, writable={writable})  # {code} {dtype}', dtype, writable

def main():
    regs = json.loads(REG_PATH.read_text(encoding="utf-8-sig"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # create __init__.py
    init = '''"""FoxAir modbus vendor package."""
from .heat_pump import FoxAir

__all__ = ["FoxAir"]
'''
    (OUT_DIR / "__init__.py").write_text(init, encoding="utf-8")

    lines = []
    lines.append('"""FoxAir heat pump Modbus model — generated from foxair_phnix_registers.json."""')
    lines.append("from modbus_connection.model import Component, gauge, integer, raw_register")
    lines.append("")
    lines.append("class FoxAir(Component):")
    lines.append('    """FoxAir/PHNIX heat pump — all holding registers."""')
    lines.append("    max_span = 65  # heat pump caps per-request")
    lines.append("    max_gap = 12   # merge nearby registers")
    lines.append("    register_space = \"holding\"")
    lines.append("")

    # collect addresses to include: only dict entries with int addr and type != BLOCK and not _comment
    items = []
    for k,v in regs.items():
        if k.startswith("_"):
            continue
        try:
            addr=int(k)
        except: continue
        if not isinstance(v, dict): continue
        if v.get("type")=="BLOCK":
            # skip BLOCK headers — they are not real registers
            continue
        # also skip ascii group 200-205? They are BLOCK type already
        items.append((addr,v))
    items.sort()

    for addr, rec in items:
        field_line, dtype, writable = field_for(addr, rec)
        lines.append(field_line)

    # helpers
    lines.append("")
    lines.append("    def as_dict(self, regmap=None):")
    lines.append('        """Compat shim: return {addr: {raw, value, info}} like old coordinator.data."""')
    lines.append("        out={}")
    lines.append("        for addr in [a for a,_ in __import__('typing').cast(list, [])]: pass")
    lines.append("        # dynamically build from declared fields")
    lines.append("        for name, field in self.declared_fields.items():")
    lines.append("            if not name.startswith('reg_'): continue")
    lines.append("            try: addr=int(name.split('_')[1])")
    lines.append("            except: continue")
    lines.append("            val=getattr(self, name, None)")
    lines.append("            # raw words not directly exposed; use value for both (compat: raw==value for scaled? keep value)")
    lines.append("            # For diagnostics we store value as both raw/value; caller can read .value")
    lines.append("            info={}")
    lines.append("            if regmap and str(addr) in regmap:")
    lines.append("                info=regmap[str(addr)]")
    lines.append("            # Try to get raw word via private _values? fallback to value")
    lines.append("            raw=val")
    lines.append("            out[addr]={'raw': raw, 'value': val, 'info': info}")
    lines.append("        return out")
    lines.append("")
    lines.append("    @property")
    lines.append("    def poll_addrs(self):")
    lines.append("        return [int(n.split('_')[1]) for n in self.declared_fields if n.startswith('reg_')]")
    lines.append("")

    content = "\n".join(lines) + "\n"
    OUT_FILE.write_text(content, encoding="utf-8")
    print(f"Wrote {len(items)} fields to {OUT_FILE}")
    # verify compile
    import py_compile, sys
    py_compile.compile(str(OUT_FILE), doraise=True)
    print("compile OK")

if __name__ == "__main__":
    main()
