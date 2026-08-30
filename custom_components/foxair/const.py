"""FoxAir constants - block names identical to FoxAir_Control.

Loads blocks, types, intervals, and core addresses from foxair_config.json
(the single source of truth). DTYPE_SPEC is derived from the config types
table (platform key stripped). TABS_CODE_ORDER is the exact code sequence
from modbus/tabs.txt — each menu and entity in required order.
"""
import json
import pathlib
from homeassistant.helpers.entity import DeviceInfo

DOMAIN = "foxair"

# ── Load foxair_config.json (single source of truth) ──────────────────
_CFG_PATH = pathlib.Path(__file__).parent / "data/foxair_config.json"
try:
    _CFG = json.loads(_CFG_PATH.read_text(encoding="utf-8-sig"))
except (OSError, json.JSONDecodeError):
    _CFG = {}

_blocks_cfg = _CFG.get("blocks", {})
_types_cfg = _CFG.get("types", {})
_modbus_cfg = _CFG.get("modbus", {})
_poll_cfg = _CFG.get("poll_intervals", {})
_markers_cfg = _CFG.get("markers", {})

# Whole tabs that are expert-only (hidden entirely until expert mode is on).
# Normal mode keeps: main device, R Setpoints, T Live (always visible), SG Ready, KG Timer, ERR Fault.
# T Diagnostic only in expert mode (requires_expert=true on those registers).
EXPERT_BLOCKS = set(_blocks_cfg.get("expert_blocks", []))

# Order MUST match tabs.txt Tab sequence: H, A, F, D, E, R, P, G, C, Z, O, S, T
# SG/KG/ERR are appended after (not in tabs.txt)
BLOCK_ORDER = _blocks_cfg.get("order", ["H", "A", "F", "D", "E", "R", "P", "G", "C", "Z", "O", "S", "T", "SG", "KG", "ERR"])
BLOCK_ORDER_INDEX = {b: i for i, b in enumerate(BLOCK_ORDER)}

BLOCK_SHORT = _blocks_cfg.get("labels", {})

# Data type specifications — derived from config types (platform key stripped).
# Used by coordinator.scaled(), sensor.py DTYPE_MAP.
DTYPE_SPEC = {
    t: {k: v for k, v in spec.items() if k != "platform"}
    for t, spec in _types_cfg.items()
    if isinstance(spec, dict)
}

# Tier intervals (multiples of 30s base)
QUICK_INTERVAL = _poll_cfg.get("quick", 1)   # every poll (30s)
MEDIUM_INTERVAL = _poll_cfg.get("medium", 4)  # 120s
RARE_INTERVAL = _poll_cfg.get("rare", 10)     # 300s (600s when expert)

# EW11 gateway limits — do not exceed
MODBUS_MAX_SPAN = _modbus_cfg.get("max_span", 45)
MODBUS_MAX_GAP = _modbus_cfg.get("max_gap", 8)

# Core main device addresses (on main device, not sub-device)
_core_marker = _markers_cfg.get("core_main_addrs", {})
CORE_MAIN_ADDRS = set(_core_marker.get("addr_list", [1011, 1012, 1157, 1158, 1159, 1234, 1235, 1236, 8801, 2133, 2012]))

# Exact code sequence from modbus/tabs.txt — each menu and entity in required order
TABS_CODE_ORDER = [
    "A03","A04","A05","A06","A11","A21","A22","A23","A24","A25","A26","A27","A28","A29","A30","A31","A32","A33","A34","A35","A38","A39","A40",
    "F01","F02","F03","F05","F06","F10","F18","F19","F22","F23","F25","F26","F27","F28","F29",
    "D01","D02","D03","D04","D05-1","D05-2","D06","D07","D08","D09","D14","D15","D16","D17","D18","D19","D20","D21","D22","D23","D24","D25","D26","D30",
    "E01","E02","E03","E07","E08","E09","E10","E13","E14","E17","E18","E19","E03-1","E03-2","E03-3","E03-4","E03-5","E07-1","E07-2","E07-3","E07-4","E07-5",
    "R01","R02","R03","R04","R05","R06","R07","R08","R09","R10","R11","R15","R16","R17","R29","R30","R31","R32","R33","R34","R35","R36","R37","R39","R43","R44","R45","R46","R60","R61","R62","R70","R71","R72","R73","R74",
    "P01","P02","P03","P05","P06","P08","P09","P10","P11","P12","P13","P14","P15","P16",
    "G01","G02","G03","G04","G05",
    "C01","C02","C03","C04","C05","C07","C08","C09","C10","C11","C12",
    "Z01","Z02","Z03","Z04","Z05","Z06","Z07","Z08","Z09","Z10","Z11","Z12","Z13","Z14","Z15","Z16","Z17","Z19","Z20",
    "O05","O06","O07","O08","O09","O10","O11","O12","O13","O15","O17",
    "S01","S02","S03","S04","S05","S06","S07","S10",
    "T01","T02","T03","T04","T05","T06","T07","T10","T11","T12","T15","T27","T29","T30","T31","T32","T33","T34","T35","T36","T37","T38","T39",
]
CODE_ORDER_INDEX = {c: i for i, c in enumerate(TABS_CODE_ORDER)}

def block_sort_key(block: str) -> int:
    return BLOCK_ORDER_INDEX.get(block or "", 999)

def code_sort_key(code: str) -> int:
    if not code:
        return 9999
    return CODE_ORDER_INDEX.get(code, 9999)

def entity_sort_key(addr: int, code: str = "", block: str = "") -> tuple:
    return (block_sort_key(block), code_sort_key(code), int(addr))

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
    label = BLOCK_SHORT.get(tab or block, BLOCK_SHORT.get(block, block))
    suffix = tab or block
    return DeviceInfo(
        identifiers={(DOMAIN, f"{ident_main[1]}_{suffix}")},
        name=f"FoxAir — {label} [{suffix}]",
        manufacturer="FoxAir/PHNIX",
        model=f"Tab {suffix}",
        via_device=ident_main,
    )

def device_for_addr(addr: int, block: str | None, entry_id: str | None = None, tab: str | None = None) -> DeviceInfo:
    if addr in CORE_MAIN_ADDRS:
        return main_device(entry_id)
    return device_for_block(block or "", entry_id, tab)

POLL_BLOCKS: list[tuple[int, int, str]] = []

POPULAR_ADDRS = {
    1011,1012,1016,1018,1021,1030,1035,
    *range(1157, 1200),
    1197,1198,1199,1205,
    1334,8801,2133,2034,
    1234,1235,1236,
    2044,2045,2046,2048,2049,2051,2053,2062,2071,2072,2074,2077,2020,2069,2019,2065,2066,2067,
}
