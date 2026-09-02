"""Select platform for v0.3 — DIGI1/TIMER/SG as selects with HA state translation."""
import logging
import re

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import POPULAR_ADDRS, device_for_addr, entity_sort_key, get_device_prefix

_LOGGER = logging.getLogger(__name__)

# Mirror of GER_TO_EN used to generate strings.json — must stay in sync with tools/build
GER_TO_EN = {
    "Aus": "Off",
    "Ein": "On",
    "Nein": "No",
    "Ja": "Yes",
    "nicht zulassen": "Disabled",
    "zulassen": "Enabled",
    "kein EVI": "No EVI",
    "EVI bei Kühlung": "EVI for Cooling",
    "EVI bei Heizung": "EVI for Heating",
    "EVI bei Heizung und Kühlung": "EVI for Heating and Cooling",
    "ohne Warmwasserfunktion": "Without DHW",
    "mit Warmwasserfunktion": "With DHW",
    "Nur Warmwasser / Only DHW": "DHW Only",
    "Celsius": "Celsius",
    "Fahrenheit": "Fahrenheit",
    "Silent-Modus aus": "Silent Off",
    "Silent-Modus ein": "Silent On",
    "Elektrische Heizstufe 1": "Electric Stage 1",
    "Elektrische Heizstufe 2": "Electric Stage 2",
    "Elektrische Heizstufe 3": "Electric Stage 3",
    "3-Wege-Ventil EIN im Warmwasser-Modus": "3-Way Valve ON in DHW",
    "3-Wege-Ventil AUS im Warmwasser-Modus": "3-Way Valve OFF in DHW",
    "Auslasswassertemperatur": "Outlet Water Temp",
    "Raumtemperatur": "Room Temperature",
    "Puffertanktemperatur": "Buffer Tank Temperature",
    "keine Durchflusserkennung": "No Flow Detection",
    "Wärmepumpe / Wassertank-Temperatursensor": "Heat Pump / Tank Sensor",
    "Modbus / Zentralregler": "Modbus / Central Controller",
    "Master/Hauptregler": "Primary Controller",
    "Slave/Nebenregler": "Secondary Controller",
    "Kühlfunktion nicht vorhanden/aus": "Cooling Disabled",
    "Kühlfunktion vorhanden/ein": "Cooling Enabled",
    "Nein / kein ERP-Test": "No ERP Test",
    "35 °C Testbedingung": "35°C Test Condition",
    "55 °C Testbedingung": "55°C Test Condition",
    "Warmwasser": "DHW",
    "Heizen": "Heating",
    "Kühlen": "Cooling",
    "Warmwasser + Heizen": "DHW + Heating",
    "Warmwasser + Kühlen": "DHW + Cooling",
    "WP Aus oder SG deaktiviert": "HP Off / SG Disabled",
    "SG Mode 1 / Schlafmodus": "SG Mode 1 / Sleep",
    "SG Mode 2 / wenig PV": "SG Mode 2 / Low PV",
    "SG Mode 3 / mittel PV": "SG Mode 3 / Medium PV",
    "SG Mode 4 / High PV": "SG Mode 4 / High PV",
    "Normalbetrieb": "Normal Operation",
    "Einfach / 1 Kontakt": "Single Contact",
    "2 Kontakte": "Dual Contacts",
    "2K Sensortyp": "2K Sensor Type",
    "5K Sensortyp": "5K Sensor Type",
    "Abtau-Modus verfügbar": "Defrost Available",
    "Abtauen": "Defrost",
    "Einlasswassertemperatur": "Inlet Water Temp",
    "Doppellüfter": "Dual Fan",
    "Einzellüfter": "Single Fan",
    "Heizseite / Pufferspeicher": "Heating Side / Buffer",
    "WW-Seite / WW-Tank": "DHW Side / Tank",
    "Keine Zone": "No Zone",
    "Manuell": "Manual",
    "Heating water circuit": "Heating Circuit",
    "Hot Water Pump / Warmwasserpumpe": "Hot Water Pump",
    "Warm Water Circulation Pump / Warmwasser-Zirkulationspumpe": "DHW Circulation Pump",
    "Sterilisieren": "Sterilization",
    "keinen Modus ändern / Code 9": "Keep Mode / Code 9",
    "nicht umschalten": "No Switch",
    "Off Signal when defrosting / Aus-Signal beim Abtauen": "Off During Defrost",
    "Always On": "Always On",
    "Interval": "Interval",
    "Legacy: Hochgeschwindigkeits-Lüfter": "Legacy: High-Speed Fan",
    "Legacy: zweistufiger Lüfter": "Legacy: 2-Stage Fan",
    "Auto": "Auto",
    "Manual": "Manual",
}

# Virtual SG 8801 / 2133 use nice short slugs (must match strings.json override)
VIRTUAL_SG_MAP = {
    2133: {"0": "off_disabled", "1": "sg1_sleep", "2": "sg2_low_pv", "3": "sg3_medium_pv", "4": "sg4_high_pv", "5": "normal"},
    8801: {"0": "off_disabled", "1": "sg1_sleep", "2": "sg2_low_pv", "3": "sg3_medium_pv", "4": "sg4_high_pv", "5": "normal"},
    1236: {"0": "fixed", "1": "curve"},
}


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "option"
    if s[0].isdigit():
        s = "opt_" + s
    return s


def _build_option_maps(vm: dict, app_values: dict | None, addr: int):
    """Return (options list of slugs, map raw->slug, reverse slug->raw)."""
    if addr in VIRTUAL_SG_MAP:
        vm_keys = VIRTUAL_SG_MAP[addr]
        options = list(vm_keys.values())
        raw_to_slug = {k: v for k, v in vm_keys.items()}
        slug_to_raw = {v: k for k, v in vm_keys.items()}
        return options, raw_to_slug, slug_to_raw
    raw_to_slug = {}
    slug_to_raw = {}
    options = []
    used = set()
    for raw in sorted(vm.keys(), key=lambda x: int(x) if x.lstrip("-").isdigit() else x):
        ger = vm[raw]
        en_label = (app_values or {}).get(raw)
        if en_label:
            if en_label == "NO":
                en_label = "No"
            elif en_label == "YES":
                en_label = "Yes"
            elif en_label == "no EVI":
                en_label = "No EVI"
        else:
            en_label = GER_TO_EN.get(ger, ger)
        slug = _slugify(en_label)
        base = slug
        i = 2
        while slug in used:
            slug = f"{base}_{i}"
            i += 1
        used.add(slug)
        options.append(slug)
        raw_to_slug[raw] = slug
        slug_to_raw[slug] = raw
    return options, raw_to_slug, slug_to_raw


def _build_timer_bitpair_options(addr: int):
    """Build named day-combination options for TIMER_BITPAIR weekday bitmask registers.

    Each 16-bit register encodes two 8-bit timer bytes (low=timer1, high=timer2).
    Each byte: bit7 = active flag, bits0-6 = Monday(1) through Sunday(64).

    Generates a compact set of named options covering common day combinations
    plus individual days, rather than 128 raw numeric values.
    """
    day_names_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_names_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    # Build options for single-byte values (0-127, all valid day combinations)
    # Map each raw byte value to a named day combination
    raw_to_slug = {}
    slug_to_raw = {}
    options = []
    used = set()

    # Always include "Off"
    def add_option(raw_val, label_en, label_ru):
        # Use English label as the slug (HA select options use translation keys)
        slug = _slugify(label_en)
        base = slug
        i = 2
        while slug in used:
            slug = f"{base}_{i}"
            i += 1
        used.add(slug)
        options.append(slug)
        raw_to_slug[str(raw_val)] = slug
        slug_to_raw[slug] = str(raw_val)

    add_option(0, "Off", "Выкл")

    # Individual days with active flag (0x80 | day_bit)
    for i, (en, ru) in enumerate(zip(day_names_en, day_names_ru)):
        add_option(0x80 | (1 << i), en, ru)

    # Common combinations: weekdays, weekends, all days
    weekdays = 0x80 | 0x01 | 0x02 | 0x04 | 0x08 | 0x10  # Mon-Fri
    weekends = 0x80 | 0x20 | 0x40  # Sat-Sun
    all_days = 0x80 | 0x7F  # Mon-Sun

    add_option(weekdays, "Weekdays (Mon-Fri)", "Будние (Пн-Пт)")
    add_option(weekends, "Weekends (Sat-Sun)", "Выходные (Сб-Вс)")
    add_option(all_days, "Every Day (Mon-Sun)", "Каждый день (Пн-Вс)")

    # Add 2-day combos
    add_option(0x80 | 0x01 | 0x02, "Mon-Tue", "Пн-Вт")
    add_option(0x80 | 0x04 | 0x08, "Wed-Thu", "Ср-Чт")
    add_option(0x80 | 0x10 | 0x20, "Fri-Sat", "Пт-Сб")

    return options, raw_to_slug, slug_to_raw


def load_value_map(coord, addr):
    """Return (value_map, app_values) from the coordinator's already-async-loaded _regmap.

    The coordinator loads foxair_phnix_registers.json once via _load_map()
    (async_add_executor_job, off the event loop).  Previously this helper
    re-read the 5770-line JSON file synchronously here, which blocked the
    event loop and triggered HA's blocking-call detector — on HA 2026.8+ the
    resulting delay/warning killed entity setup so select entities (e.g. SG01)
    never got their options populated and showed "unknown".
    """
    try:
        regmap = getattr(coord, "_regmap", None)
        if regmap is None:
            return None, None
        rec = regmap.get(str(addr), {})
        return rec.get("value_map"), rec.get("app_values")
    except Exception:
        return None, None


async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    for addr_str, meta in sorted((coord._metadata or {}).items(), key=lambda kv: entity_sort_key(int(kv[0]) if kv[0].isdigit() else 99999, kv[1].get("code",""), kv[1].get("block",""))):
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        if meta.get("platform") != "select" or not meta.get("editable"):
            continue
        # permanently hidden (reserved/system/factory-test addrs): never create
        if meta.get("hidden"):
            continue
        if addr in (1246, 1249):
            continue  # silent-minute slaves handled by time composite
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        ents.append(FoxSelect(coord, addr, meta))
    add_entities(ents)


class FoxSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta):
        super().__init__(coord)
        self._addr = addr
        self._meta = meta
        self._optimistic = None  # slug shown during a write round-trip
        self._is_timer_bitpair = False  # set to True for TIMER_BITPAIR entities
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_sel_{addr}"
        self._attr_translation_key = f"{prefix}_{addr}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        block = meta.get("block") or ""
        tab = meta.get("tab") or block
        self._attr_device_info = device_for_addr(addr, block, entry_id, tab, prefix)
        self._attr_icon = meta.get("icon") or "mdi:heat-pump"
        risk = meta.get("risk")
        hc = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
        hc_addrs = hc.get("addr_single", {}) if isinstance(hc, dict) else {}
        if addr == hc_addrs.get("at_comp_en", 1236):
            self._attr_entity_category = None
            self._attr_entity_registry_enabled_default = True
        elif risk == "dangerous":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False
        elif risk == "advanced":
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
        else:
            # safe: visible if has a tab code (user-facing control like KG timers)
            # or in popular addrs; otherwise diagnostic hidden
            code = meta.get("code", "")
            if code or addr in POPULAR_ADDRS:
                self._attr_entity_category = None
                self._attr_entity_registry_enabled_default = True
            else:
                self._attr_entity_category = EntityCategory.DIAGNOSTIC
                self._attr_entity_registry_enabled_default = False

        vm, app_vals = load_value_map(coord, addr)
        if vm:
            opts, r2s, s2r = _build_option_maps(vm, app_vals, addr)
            self._attr_options = opts
            self._raw_to_slug = r2s
            self._slug_to_raw = s2r
        elif meta.get("type") == "TIMER_BITPAIR":
            # Generate named day-combination options for weekday bitmasks.
            # Each 16-bit register encodes two timer bytes (low=timer1, high=timer2).
            # Each byte: bit7=active, bits0-6=Mon-Su.
            opts, r2s, s2r = _build_timer_bitpair_options(addr)
            self._attr_options = opts
            self._raw_to_slug = r2s
            self._slug_to_raw = s2r
            self._is_timer_bitpair = True
        else:
            lo, hi = meta.get("min"), meta.get("max")
            if lo is not None and hi is not None:
                self._attr_options = [str(int(i)) for i in range(int(lo), int(hi) + 1)]
                self._raw_to_slug = {str(i): str(int(i)) for i in range(int(lo), int(hi) + 1)}
                self._slug_to_raw = {v: k for k, v in self._raw_to_slug.items()}
            else:
                self._attr_options = ["0", "1"]
                self._raw_to_slug = {"0": "0", "1": "1"}
                self._slug_to_raw = {"0": "0", "1": "1"}

    @property
    def available(self):
        """Dynamic availability: hide expert entities when expert mode is off."""
        if self._meta.get("requires_expert") and not self.coordinator.entry.options.get("enable_expert"):
            return False
        return super().available

    @property
    def current_option(self):
        if self._optimistic is not None:
            return self._optimistic
        rec = self.coordinator.data.get(self._addr)
        if not rec:
            return None
        raw = str(rec.get("raw"))
        # TIMER_BITPAIR: register is 16-bit, decode low byte (timer 1)
        if self._is_timer_bitpair:
            try:
                raw_int = int(raw)
                low_byte = raw_int & 0xFF
            except (ValueError, TypeError):
                return None
            slug = self._raw_to_slug.get(str(low_byte))
            if slug in (self._attr_options or []):
                return slug
            return None
        # direct slug lookup
        slug = self._raw_to_slug.get(raw)
        if slug in (self._attr_options or []):
            return slug
        # fallback: try int compare
        for k, v in self._raw_to_slug.items():
            try:
                if int(k) == int(raw):
                    return v
            except Exception:
                pass
        return str(raw) if str(raw) in (self._attr_options or []) else None

    async def async_select_option(self, option: str) -> None:
        # show the new option immediately so the control doesn't appear frozen
        # during the Modbus write + read-back round-trip (~1-2s)
        self._optimistic = option
        self._attr_assumed_state = True
        self.async_write_ha_state()
        # option is a slug like "single_contact" or numeric "1"
        raw_str = self._slug_to_raw.get(option)
        if raw_str is None:
            # fallback: option may be legacy "0: Aus" or direct raw
            raw_str = option.split(":", 1)[0].strip()
            # if still slug-like, try to resolve via reverse
            if raw_str not in self._slug_to_raw.values():
                # last resort: treat as int
                pass
            else:
                option = raw_str
                raw_str = self._slug_to_raw.get(option, raw_str)
        try:
            val = int(raw_str)
        except Exception:
            try:
                val = int(option)
            except Exception:
                self._optimistic = None
                self._attr_assumed_state = False
                self.async_write_ha_state()
                raise ValueError(f"Unknown option {option} for {self._addr}")
        # TIMER_BITPAIR: write the same byte to both timer slots in the 16-bit register
        if self._is_timer_bitpair:
            val = (val & 0xFF) | ((val & 0xFF) << 8)
        ok = await self.coordinator.async_write_register(self._addr, float(val))
        if not ok:
            self._optimistic = None
            self._attr_assumed_state = False
            self.async_write_ha_state()
            raise ValueError(f"Write rejected {self._addr}")
        self._optimistic = None
        self.async_write_ha_state()
