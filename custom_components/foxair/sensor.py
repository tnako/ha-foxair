from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from .const import DOMAIN, POPULAR_ADDRS

DTYPE_MAP = {
    "TEMP1": (SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT),
    "TEMP": (SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT),
    "TEMP05": (SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT),
    "VOLT": (SensorDeviceClass.VOLTAGE, "V", SensorStateClass.MEASUREMENT),
    "HZ": (SensorDeviceClass.FREQUENCY, "Hz", SensorStateClass.MEASUREMENT),
    "PERCENT": (None, "%", SensorStateClass.MEASUREMENT),
    "DIGI1": (None, None, SensorStateClass.MEASUREMENT),
    "DIGI5": (None, None, SensorStateClass.MEASUREMENT),
    "FLOW_M3H_X100": (None, "m³/h", SensorStateClass.MEASUREMENT),
    "BAR_X10": (SensorDeviceClass.PRESSURE, "bar", SensorStateClass.MEASUREMENT),
    "AMP_X10": (SensorDeviceClass.CURRENT, "A", SensorStateClass.MEASUREMENT),
    "RAW": (None, None, None),
}

# 2057 is unknown - keep but disabled
HIDDEN = {2057}

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    ents = []
    for addr, rec in coord.data.items():
        # only sensor entities (read or r/w that are readable)
        # keep all, but hide 2057 and unsafe will be diagnostic disabled
        ents.append(FoxSensor(coord, addr))
    add_entities(ents)

class FoxSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coord, addr):
        super().__init__(coord)
        self._addr = addr
        rec = coord.data.get(addr, {})
        info = rec.get("info", {}) if rec else {}
        self._attr_unique_id = f"foxair_{addr}"
        self._attr_translation_key = f"foxair_{addr}"
        # keep object_id English - will be derived from strings.json English
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "foxair")}, name="FoxAir Modbus Heat Pump", manufacturer="FoxAir/PHNIX", model="Modbus TCP")
        dtype = info.get("type","RAW")
        dc, unit, sc = DTYPE_MAP.get(dtype, (None, info.get("unit") or None, SensorStateClass.MEASUREMENT))
        if dc: self._attr_device_class = dc
        if unit: self._attr_native_unit_of_measurement = unit
        elif info.get("unit"): self._attr_native_unit_of_measurement = info.get("unit")
        if sc: self._attr_state_class = sc
        if dtype in ("TEMP1","TEMP","TEMP05"): self._attr_suggested_display_precision = 1
        elif dtype in ("VOLT","BAR_X10"): self._attr_suggested_display_precision = 1
        # 2057 and unsafe hidden
        if addr in HIDDEN:
            self._attr_entity_registry_enabled_default = False
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        else:
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
            if addr not in POPULAR_ADDRS:
                self._attr_entity_category = EntityCategory.DIAGNOSTIC
    @property
    def native_value(self):
        rec = self.coordinator.data.get(self._addr)
        return rec["value"] if rec else None
    @property
    def extra_state_attributes(self):
        rec = self.coordinator.data.get(self._addr)
        if not rec: return {}
        info = rec.get("info",{})
        return {"raw": rec.get("raw"), "address": self._addr, "block": info.get("block"), "code": info.get("code"), "type": info.get("type")}
