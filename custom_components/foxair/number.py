"""Number platform for v0.3 — editable registers with min/max + expert guard."""
import logging
from homeassistant.components.number import NumberEntity, NumberMode, NumberDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN, DEVICE, POPULAR_ADDRS, device_for_addr

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
    "BAR_X10": NumberDeviceClass.PRESSURE,
}

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    # ensure metadata loaded
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    for addr_str, meta in (coord._metadata or {}).items():
        try:
            addr = int(addr_str)
        except: continue
        if meta.get("platform") != "number" or not meta.get("editable"):
            continue
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
        self._attr_unique_id = f"foxair_num_{addr}"
        self._attr_translation_key = f"foxair_{addr}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        block = meta.get("block") or ""
        tab = meta.get("tab") or block
        self._attr_device_info = device_for_addr(addr, block, entry_id, tab)
        self._attr_icon = meta.get("icon") or "mdi:heat-pump"
        risk = meta.get("risk")
        if addr in (1234, 1235):
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
        if lo is not None: self._attr_native_min_value = float(lo)
        if hi is not None: self._attr_native_max_value = float(hi)
        if step is not None: self._attr_native_step = float(step)
        # mode: dangerous = box (precise), safe = slider
        self._attr_mode = NumberMode.BOX if risk == "dangerous" else NumberMode.SLIDER
        # unit/device class
        unit = meta.get("unit")
        if unit: self._attr_native_unit_of_measurement = unit
        dc = DTYPE_CLASS.get(meta.get("type"))
        if dc: self._attr_device_class = dc

    @property
    def native_value(self):
        # optimistic value shown while a write round-trip is in flight
        if self._optimistic is not None:
            return self._optimistic
        rec = self.coordinator.data.get(self._addr)
        if rec is None: return None
        v = rec.get("value")
        try: return float(v)
        except: return None

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

