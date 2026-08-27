"""FoxAir constants - block names and poll layout identical to FoxAir_Control."""
from homeassistant.helpers.entity import DeviceInfo

DOMAIN = "foxair"

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

# German labels matching FoxAir_Control dialogs/parameter_settings_dialog.py BLOCK_SHORT_DESCRIPTIONS
BLOCK_SHORT_DE = {
    "H": "Basis/Hardware",
    "A": "Schutz/Grenzen",
    "F": "Fan",
    "D": "Abtauen",
    "E": "EVI/EEV",
    "C": "Compressor",
    "R": "Sollwerte",
    "T": "Diagnose/Live",
    "Z": "Zone",
    "G": "Legionellen",
    "P": "Pumpe",
    "SG": "SG Ready",
    "KG": "Timer",
    "ERR": "Fault",
}

# Main heat pump device (climate + core controls) - kept as primary via_device parent
def main_device(entry_id: str | None = None) -> DeviceInfo:
    ident = (DOMAIN, entry_id) if entry_id else (DOMAIN, "foxair")
    return DeviceInfo(
        identifiers={ident},
        name="FoxAir Heat Pump",
        manufacturer="FoxAir/PHNIX",
        model="Modbus TCP Heat Pump",
    )

# Single device fallback for legacy callers (tests)
DEVICE = main_device()

def device_for_block(block: str, entry_id: str | None = None) -> DeviceInfo:
    """Return DeviceInfo for a given register block.

    - Empty/unknown block or core controls (1011/1012) -> Main Heat Pump
    - Known BLOCK_SHORT -> sub-device FoxAir — <label> [BLOCK] via Main
    - Mirrors FoxAir_Control ParameterSettingsDialog grouping; H/A/F/D/E/C/R/T/Z/G/P/SG/KG/ERR
    """
    ident_main = (DOMAIN, entry_id) if entry_id else (DOMAIN, "foxair")
    if not block or block not in BLOCK_SHORT:
        # Header/Reserved or core ON/OFF/mode live on Main
        return main_device(entry_id)
    label = BLOCK_SHORT.get(block, block)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{ident_main[1]}_{block}")},
        name=f"FoxAir — {label} [{block}]",
        manufacturer="FoxAir/PHNIX",
        model=f"Block {block}",
        via_device=ident_main,
    )

def device_for_addr(addr: int, block: str | None, entry_id: str | None = None) -> DeviceInfo:
    """Convenience: core control addrs always on Main, else by block."""
    # Core climate controls stay on Main for UX (climate card on top)
    CORE_MAIN_ADDRS = {1011, 1012, 1157, 1158, 1159, 1234, 1235, 1236, 8801, 2133, 2012, 2048, 2046}
    if addr in CORE_MAIN_ADDRS:
        return main_device(entry_id)
    return device_for_block(block or "", entry_id)

# Bulk poll blocks (qty <=125) covering 1001-1540 and 2001-2149
# Mirrors FoxAir_Control 8x90 init blocks but merged for efficiency (max 125 per Modbus frame).
POLL_BLOCKS = [
    (1001, 125, "B1 H/A/F/D"),
    (1126, 125, "B2 E/R"),
    (1251, 125, "B3 R/C/SG/P 1251-1375"),
    (1376, 125, "B4 factory/test+P 1376-1500"),
    (1501, 40, "B5 extra 1501-1540"),
    (2001, 125, "B6 T live"),
    (2126, 24, "B7 ERR tail"),
]
# Everyday controls stay visible, installer controls are Diagnostic and disabled by default
POPULAR_ADDRS = {
    1011,1012,1016,1018,1021,1030,1035,
    *range(1157, 1200),  # R
    1197,1198,1199,1205,
    1334,8801,2133,2034,
    1234,1235,1236,
    2044,2045,2046,2048,2049,2051,2053,2062,2071,2072,2074,2077,2020,2069,2019,2065,2066,2067,
}
