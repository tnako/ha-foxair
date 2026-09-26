"""FoxAir constants - block names identical to FoxAir_Control.

Loads blocks, types, intervals, and core addresses from foxair_config.json
(the single source of truth). DTYPE_SPEC is derived from the config types
table (platform key stripped). TABS_CODE_ORDER is the exact code sequence
from modbus/tabs.txt — each menu and entity in required order.
"""
from __future__ import annotations
import json
import re
import pathlib
from homeassistant.helpers.entity import DeviceInfo

DOMAIN = "foxair"

# ── Load foxair_config.json (single source of truth) ──────────────────
# Lazy-loaded: HA 2026+ flags synchronous read_text() at import time as a
# blocking call inside the event loop (homeassistant.util.loop warning).
# We defer the read until first access and cache the result.
_CFG_PATH = pathlib.Path(__file__).parent / "data/foxair_config.json"
_CFG: dict | None = None  # type: ignore[assignment]
_CFG_LOADED = False

# Module-level names always exist (fallback defaults until config loads).
# _apply_dict() mutates these containers in place so `from .const import X`
# references in platforms stay valid.
_blocks_cfg, _types_cfg, _modbus_cfg, _poll_cfg, _markers_cfg = {}, {}, {}, {}, {}
EXPERT_BLOCKS: set = set()
BLOCK_ORDER: list = ["H", "A", "F", "D", "E", "R", "P", "G", "C", "Z", "O", "S", "T", "SG", "KG", "ERR"]
BLOCK_ORDER_INDEX: dict = {b: i for i, b in enumerate(BLOCK_ORDER)}
BLOCK_SHORT: dict = {}
DTYPE_SPEC: dict = {}
QUICK_INTERVAL, MEDIUM_INTERVAL, RARE_INTERVAL = 1, 4, 10
MODBUS_MAX_SPAN, MODBUS_MAX_GAP = 90, 30
# Address sets: EMPTY fallbacks, populated from foxair_config.json by
# _apply_dict() (eager off-loop via _ensure_cfg, inside HA via apply_config
# from the coordinator before entity setup). Never hardcode addr lists here —
# not every addr exists on every firmware (e.g. 8801 is documentation-only,
# T59/T60 absent below v3.3), and a stale literal silently polls dead words.
CORE_MAIN_ADDRS: set = set()

POLL_BLOCKS: list = []

POPULAR_ADDRS: set = set()

SENSOR_HIDDEN_ADDRS: set = set()

def _apply_dict(cfg: dict) -> dict:
    """Set all config-derived globals from an already-loaded dict (no I/O).

    Mutates containers IN PLACE (clear/update) so existing
    `from .const import X` references in platforms stay valid — rebinding
    would leave them pointing at the stale fallback objects.
    """
    global _CFG, _CFG_LOADED, _blocks_cfg, _types_cfg, _modbus_cfg, _poll_cfg, _markers_cfg
    global BLOCK_ORDER, QUICK_INTERVAL, MEDIUM_INTERVAL, RARE_INTERVAL
    global MODBUS_MAX_SPAN, MODBUS_MAX_GAP
    _CFG = cfg or {}
    _CFG_LOADED = True
    _blocks_cfg = _CFG.get("blocks", {})
    _types_cfg = _CFG.get("types", {})
    _modbus_cfg = _CFG.get("modbus", {})
    _poll_cfg = _CFG.get("poll_intervals", {})
    _markers_cfg = _CFG.get("markers", {})
    EXPERT_BLOCKS.clear()
    EXPERT_BLOCKS.update(_blocks_cfg.get("expert_blocks", []))
    BLOCK_ORDER[:] = _blocks_cfg.get("order", ["H", "A", "F", "D", "E", "R", "P", "G", "C", "Z", "O", "S", "T", "SG", "KG", "ERR"])
    BLOCK_ORDER_INDEX.clear()
    BLOCK_ORDER_INDEX.update({b: i for i, b in enumerate(BLOCK_ORDER)})
    BLOCK_SHORT.clear()
    BLOCK_SHORT.update(_blocks_cfg.get("labels", {}))
    DTYPE_SPEC.clear()
    DTYPE_SPEC.update({
        t: {k: v for k, v in spec.items() if k != "platform"}
        for t, spec in _types_cfg.items()
        if isinstance(spec, dict)
    })
    QUICK_INTERVAL = _poll_cfg.get("quick", 1)
    MEDIUM_INTERVAL = _poll_cfg.get("medium", 4)
    RARE_INTERVAL = _poll_cfg.get("rare", 10)
    MODBUS_MAX_SPAN = _modbus_cfg.get("max_span", 90)
    MODBUS_MAX_GAP = _modbus_cfg.get("max_gap", 30)
    _core_marker = _markers_cfg.get("core_main_addrs", {})
    CORE_MAIN_ADDRS.clear()
    CORE_MAIN_ADDRS.update(_core_marker.get("addr_list", []))
    POPULAR_ADDRS.clear()
    POPULAR_ADDRS.update(_CFG.get("popular_addrs", []) or [])
    SENSOR_HIDDEN_ADDRS.clear()
    SENSOR_HIDDEN_ADDRS.update(_CFG.get("sensor_hidden_addrs", []) or [])
    return _CFG


def apply_config(cfg: dict) -> dict:
    """Push an already-loaded config dict (no file read).

    Called by the coordinator after loading foxair_config.json off the event
    loop — this is what makes BLOCK_SHORT / DTYPE_SPEC / POPULAR_ADDRS real
    inside HA, where _ensure_cfg() must never do blocking I/O.
    """
    return _apply_dict(cfg or {})


def _ensure_cfg() -> dict:
    global _CFG, _CFG_LOADED, _blocks_cfg, _types_cfg, _modbus_cfg, _poll_cfg, _markers_cfg
    global EXPERT_BLOCKS, BLOCK_ORDER, BLOCK_ORDER_INDEX, BLOCK_SHORT
    global DTYPE_SPEC, QUICK_INTERVAL, MEDIUM_INTERVAL, RARE_INTERVAL
    global MODBUS_MAX_SPAN, MODBUS_MAX_GAP, CORE_MAIN_ADDRS, POPULAR_ADDRS
    if _CFG_LOADED and _CFG is not None:
        return _CFG  # type: ignore[return-value]
    try:
        cfg = json.loads(_CFG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        cfg = {}
    return _apply_dict(cfg)

# Eager-load when not running inside HA event loop (tools, tests, CLI).
# Inside HA the import happens on the event loop — keep it lazy there.
# Globals above already hold fallback defaults, so nothing more to do here.
try:
    import asyncio as _asyncio
    _asyncio.get_running_loop()
except RuntimeError:
    _ensure_cfg()

# (EXPERT_BLOCKS / BLOCK_ORDER / DTYPE_SPEC / intervals / CORE_MAIN_ADDRS
# are already set above — either by _ensure_cfg() eager load or by the
# fallback defaults. No re-read here so we don't re-trigger blocking I/O
# at import when running on the HA event loop.)

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

def main_device(entry_id: str | None = None, name_prefix: str = "foxair", slave_id: int | None = None, host: str | None = None, port: int | None = None) -> DeviceInfo:
    ident = (DOMAIN, entry_id) if entry_id else (DOMAIN, "foxair")
    prefix_display = name_prefix.title() if name_prefix else "FoxAir"
    # Prefix is the multi-pump differentiator — no host in device names.
    name = f"{prefix_display} Heat Pump"
    if slave_id is not None and slave_id != 1:
        name = f"{name} (slave {slave_id})"
    port_str = f":{port}" if port and port != 8899 else ""
    return DeviceInfo(
        identifiers={ident},
        name=name,
        manufacturer="FoxAir/PHNIX",
        model=f"Modbus TCP Heat Pump ({host}{port_str})" if host else f"Modbus TCP Heat Pump (slave {slave_id})" if slave_id else "Modbus TCP Heat Pump",
    )


def get_device_prefix(entry) -> str:
    """Get the name prefix from a config entry, defaulting to 'foxair'."""
    if entry and hasattr(entry, "data"):
        return entry.data.get("name_prefix", "foxair")
    return "foxair"


def get_slave_id(entry) -> int | None:
    """Get the Modbus slave (unit) ID from a config entry, or None."""
    if entry and hasattr(entry, "data"):
        return entry.data.get("slave")
    return None


def slug_code(code: str) -> str:
    """Slugify a register code for uid/entity_id/translation_key use."""
    return re.sub(r"[^a-z0-9]+", "_", (code or "").lower()).strip("_")


def entity_suffix(coord, addr: int) -> str:
    """Return the name suffix for entity_id/unique_id/translation_key.

    Uses metadata ``code`` when present (e.g. ``t02``, ``h36``, ``r04``),
    falls back to the raw address string (e.g. ``2014``, ``1012``) when no
    code exists.  Code-based naming is the single consistent scheme across
    all platforms.
    """
    meta = {}
    try:
        meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
    except Exception:
        pass
    info = (coord.data.get(addr) or {}).get("info", {})
    code = meta.get("code") or info.get("code") or ""
    if code:
        return slug_code(code)
    return str(addr)


DEVICE = main_device()


def device_for_block(block: str, entry_id: str | None = None, tab: str | None = None, name_prefix: str = "foxair", slave_id: int | None = None, host: str | None = None, port: int | None = None) -> DeviceInfo:
    # NOTE: no _ensure_cfg() here — file I/O on the HA event loop is blocked
    # by HA 2026's loop guard. Globals are populated by apply_config(), called
    # from the coordinator's _load_config() (executor-loaded) before any
    # entity setup. Off-loop (tools/tests/CLI) the eager _ensure_cfg() above
    # already populated them.
    ident_main = (DOMAIN, entry_id) if entry_id else (DOMAIN, "foxair")
    if not block or block not in BLOCK_SHORT:
        return main_device(entry_id, name_prefix, slave_id, host, port)
    label = BLOCK_SHORT.get(tab or block, BLOCK_SHORT.get(block, block))
    suffix = tab or block
    prefix_display = name_prefix.title() if name_prefix else "FoxAir"
    name = f"{prefix_display} — {label} [{suffix}]"
    if slave_id is not None and slave_id != 1:
        name = f"{name} (slave {slave_id})"
    port_str = f":{port}" if port and port != 8899 else ""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{ident_main[1]}_{suffix}")},
        name=name,
        manufacturer="FoxAir/PHNIX",
        model=f"Tab {suffix} ({host}{port_str})" if host else f"Tab {suffix}" + (f" (slave {slave_id})" if slave_id is not None else ""),
        via_device=ident_main,
    )


def device_for_addr(addr: int, block: str | None, entry_id: str | None = None, tab: str | None = None, name_prefix: str = "foxair", slave_id: int | None = None, host: str | None = None, port: int | None = None) -> DeviceInfo:
    if addr in CORE_MAIN_ADDRS:
        return main_device(entry_id, name_prefix, slave_id, host, port)
    return device_for_block(block or "", entry_id, tab, name_prefix, slave_id, host, port)


def bind_device_info(hass, entry_id, info):
    """Resolve DeviceInfo via_device identifiers to via_device_id.

    HA deprecated the via_device parameter (warns since 2026, removal
    2027.8): sub-devices must link by registry id. The main device is
    pre-created in async_setup_entry, so the lookup always hits at entity
    setup. Falls back to the unmodified info when hass/lookup is missing
    (offline tools, tests) rather than breaking setup.
    """
    try:
        via = (info or {}).get("via_device")
    except Exception:
        return info
    if not via or hass is None or not entry_id:
        return info
    try:
        from homeassistant.helpers import device_registry as _dr
        reg = _dr.async_get(hass)
        get_by_id = getattr(reg, "async_get_device_by_identifier", None)
        if get_by_id is not None:
            dev = get_by_id(tuple(via), entry_id)
        else:
            # HA < 2025.x fallback (no deprecation warning there)
            dev = reg.async_get_device(identifiers={tuple(via)})
        if dev is not None:
            d = dict(info)
            d.pop("via_device", None)
            d["via_device_id"] = dev.id
            return d
    except Exception:
        pass
    return info


# Generic word bit-twiddling for bit_split registers (spec in
# foxair_config.json -> metadata format/bits/mask; entities built by
# switch.py/button.py). Momentary trigger bits are set-only.
def word_base(raw) -> int:
    """Current raw word as int (0 when unknown)."""
    try:
        return int(raw) & 0xFFFF
    except (TypeError, ValueError):
        return 0


def word_set(base: int, bit: int) -> int:
    return base | (1 << bit)


def word_clear(base: int, bit: int) -> int:
    return base & ~(1 << bit)


def word_is_set(base: int, bit: int) -> bool:
    return bool(base & (1 << bit))


def word_mask(bits: dict) -> int:
    mask = 0
    for bit in (bits or {}):
        mask |= 1 << int(bit)
    return mask


# Generic BITFIELD expansion (binary_sensor platform): any R/O register with
# a bit_map in foxair_phnix_registers.json is split into per-bit entities
# instead of a meaningless raw decimal. Word is None until first poll.
def bitfield_word(raw) -> int | None:
    try:
        return int(raw) & 0xFFFF
    except (TypeError, ValueError):
        return None


def bitfield_is_set(word: int | None, bit: int) -> bool | None:
    if word is None:
        return None
    return bool(word & (1 << bit))


# Bit labels matching this are spare/unknown docs — no entity is created.
BITFIELD_RESERVED_RE = r"reserv|unbekannt|unknown|spare|nicht belegt"


def bitfield_expanded_bits(bit_map: dict) -> list[tuple[int, str]]:
    import re as _re
    out = []
    for bit, label in (bit_map or {}).items():
        try:
            b = int(bit)
        except (TypeError, ValueError):
            continue
        if _re.search(BITFIELD_RESERVED_RE, str(label), _re.I):
            continue
        out.append((b, str(label)))
    return sorted(out)

# (module-level POLL_BLOCKS / POPULAR_ADDRS are declared near the top so
# _apply_dict() can mutate them in place; config extension is applied there.)
