"""Number platform for v0.3 — editable registers with min/max + expert guard."""
import logging
from homeassistant.components.number import NumberEntity, NumberMode, NumberDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import POPULAR_ADDRS, device_for_addr, entity_sort_key, get_device_prefix

_LOGGER = logging.getLogger(__name__)

# map type to device class/icon fallback
DTYPE_CLASS = {
    "TEMP1": NumberDeviceClass.TEMPERATURE,
    "TEMP": NumberDeviceClass.TEMPERATURE,
    "TEMP05": NumberDeviceClass.TEMPERATURE,
    "BAR_X10": NumberDeviceClass.PRESSURE,
    "POWER_KW_X10": NumberDeviceClass.POWER,
    "HZ": NumberDeviceClass.FREQUENCY,
    "MINUTES": None,
    "SECONDS": None,
    "HOURS": None,
    "DAYS": None,
    "PERCENT": None,
    "STEPS_N": None,
    "RPM": None,
}

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    # ensure metadata loaded
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    # each menu and each entity in needed order (tabs.txt)
    for addr_str, meta in sorted((coord._metadata or {}).items(), key=lambda kv: entity_sort_key(int(kv[0]) if kv[0].isdigit() else 99999, kv[1].get("code",""), kv[1].get("block",""))):
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        if meta.get("platform") != "number" or not meta.get("editable"):
            continue
        # permanently hidden (reserved/system/header addrs): never create
        if meta.get("hidden"):
            continue
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
            continue
        if addr in (1246, 1249):
            continue  # silent-minute slaves handled by time composite
        # expert filter: if requires_expert and expert not enabled, skip creation
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        ents.append(FoxNumber(coord, addr, meta))
    add_entities(ents)

class FoxNumber(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True
    def __init__(self, coord, addr, meta):
        super().__init__(coord)
        self._addr = addr
        self._meta = meta
        self._optimistic = None  # value shown during a write round-trip
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_num_{addr}"
        self._attr_translation_key = f"{prefix}_{addr}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        block = meta.get("block") or ""
        tab = meta.get("tab") or block
        self._attr_device_info = device_for_addr(addr, block, entry_id, tab, prefix)
        self._attr_icon = meta.get("icon") or "mdi:heat-pump"
        risk = meta.get("risk")
        hc = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
        hc_addrs = hc.get("addr_single", {}) if isinstance(hc, dict) else {}
        # heat curve slope/offset: visible, not diagnostic
        if addr in (hc_addrs.get("slope"), hc_addrs.get("offset")):
            self._attr_entity_category = None
            self._attr_entity_registry_enabled_default = True
        elif risk == "dangerous":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False
        elif risk == "advanced":
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
        else:
            # safe: visible only if popular, else diagnostic hidden
            if addr in POPULAR_ADDRS:
                self._attr_entity_category = None
                self._attr_entity_registry_enabled_default = True
            else:
                self._attr_entity_category = EntityCategory.DIAGNOSTIC
                self._attr_entity_registry_enabled_default = False
        # limits
        lo, hi, step = meta.get("min"), meta.get("max"), meta.get("step") or 1
        if lo is not None:
            self._attr_native_min_value = float(lo)
        if hi is not None:
            self._attr_native_max_value = float(hi)
        if step is not None:
            self._attr_native_step = float(step)
        # mode: dangerous = box (precise), safe = slider
        self._attr_mode = NumberMode.BOX if risk == "dangerous" else NumberMode.SLIDER
        # unit/device class
        unit = meta.get("unit")
        if unit:
            self._attr_native_unit_of_measurement = unit
        dc = DTYPE_CLASS.get(meta.get("type"))
        if dc:
            self._attr_device_class = dc

    @property
    def available(self):
        """Dynamic availability: expert gating + registry depends_on."""
        if self._meta.get("requires_expert") and not self.coordinator.entry.options.get("enable_expert"):
            return False
        dep = self._meta.get("depends_on")
        if dep is not None:
            try:
                rec = self.coordinator.data.get(int(dep))
                if not rec:
                    return False
                raw = rec.get("raw")
                if raw is None:
                    raw = rec.get("value")
                if raw is None:
                    return False
                s = str(raw).strip().lower()
                if s in ("0", "0.0", "off", "no", "false", ""):
                    return False
                try:
                    if float(raw) == 0:
                        return False
                except Exception:
                    pass
            except Exception:
                pass
        return super().available

    @property
    def native_value(self):
        # optimistic value shown while a write round-trip is in flight
        if self._optimistic is not None:
            return self._optimistic
        rec = self.coordinator.data.get(self._addr)
        if rec is None:
            return None
        v = rec.get("value")
        try:
            return float(v)
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        value = float(value)
        # show the new value immediately so the slider doesn't appear frozen
        # while the Modbus write + read-back round-trip (can be ~1-2s) happens
        self._optimistic = value
        self._attr_assumed_state = True
        self.async_write_ha_state()
        ok = await self.coordinator.async_write_register(self._addr, value)
        if not ok:
            _LOGGER.error("number write failed %s", self._addr)
            # roll back optimistic value; next poll will restore real value
            self._optimistic = None
            self._attr_assumed_state = False
            self.async_write_ha_state()
            raise ValueError(f"Write rejected for {self._addr}")
        # keep optimistic value until the read-back/poll confirms; clear on next
        # coordinator update so we always converge to the real device value
        self._optimistic = None
        self.async_write_ha_state()

