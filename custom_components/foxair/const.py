"""FoxAir constants - block names identical to FoxAir_Control."""
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
    "O": "Outputs",
    "S": "Switches",
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
    "O": "Outputs",
    "S": "Switches",
    "ERR": "Fault",
}

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
    "O": "Ausgänge",
    "S": "Schalter",
    "ERR": "Fault",
}

def main_device(entry_id: str | None = None) -> DeviceInfo:
    ident = (DOMAIN, entry_id) if entry_id else (DOMAIN, "foxair")
    return DeviceInfo(
        identifiers={ident},
        name="FoxAir Heat Pump",
        manufacturer="FoxAir/PHNIX",
        model="Modbus TCP Heat Pump",
    )

DEVICE = main_device()

def device_for_block(block: str, entry_id: str | None = None, tab: str | None = None) -> DeviceInfo:
    ident_main = (DOMAIN, entry_id) if entry_id else (DOMAIN, "foxair")
    if not block or block not in BLOCK_SHORT:
        return main_device(entry_id)
    label = APP_TAB_TITLES.get(tab or block, BLOCK_SHORT.get(block, block))
    suffix = tab or block
    return DeviceInfo(
        identifiers={(DOMAIN, f"{ident_main[1]}_{suffix}")},
        name=f"FoxAir — {label} [{suffix}]",
        manufacturer="FoxAir/PHNIX",
        model=f"Tab {suffix}",
        via_device=ident_main,
    )

def device_for_addr(addr: int, block: str | None, entry_id: str | None = None, tab: str | None = None) -> DeviceInfo:
    CORE_MAIN_ADDRS = {1011, 1012, 1157, 1158, 1159, 1234, 1235, 1236, 8801, 2133, 2012, 2048, 2046}
    if addr in CORE_MAIN_ADDRS:
        return main_device(entry_id)
    return device_for_block(block or "", entry_id, tab)

POLL_BLOCKS: list[tuple[int, int, str]] = []

POPULAR_ADDRS = {
    1011,1012,1016,1018,1021,1030,1035,
    *range(1157, 1200),  # R
    1197,1198,1199,1205,
    1334,8801,2133,2034,
    1234,1235,1236,
    2044,2045,2046,2048,2049,2051,2053,2062,2071,2072,2074,2077,2020,2069,2019,2065,2066,2067,
}
