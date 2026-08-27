from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, POPULAR_ADDRS

# mapping dtype -> device_class, unit, state_class
DTYPE_MAP = {
    "TEMP1": (SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT),
    "TEMP": (SensorDeviceClass.TEMPERATURE, "°C", SensorStateClass.MEASUREMENT),
    "VOLT": (SensorDeviceClass.VOLTAGE, "V", SensorStateClass.MEASUREMENT),
    "HZ": (SensorDeviceClass.FREQUENCY, "Hz", SensorStateClass.MEASUREMENT),
    "PERCENT": (None, "%", SensorStateClass.MEASUREMENT),
    "DIGI1": (None, None, SensorStateClass.MEASUREMENT),
    "RAW": (None, None, None),
}

async def async_setup_entry(hass, entry, add_entities):
    coord=hass.data["foxair"][entry.entry_id]
    addrs=(2045,2046,2048,2049,2051,2053,2044,2057,2062,2072)
    ents=[FoxSensor(coord, addr) for addr in addrs if addr in coord.data]
    add_entities(ents)

class FoxSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coord, addr):
        super().__init__(coord)
        self._addr=addr
        rec=coord.data.get(addr, {})
        info=rec.get("info", {}) if rec else {}
        self._attr_unique_id=f"foxair_{addr}"
        self._attr_translation_key=f"foxair_{addr}"
        # device
        self._attr_device_info=DeviceInfo(identifiers={(DOMAIN, "foxair")}, name="FoxAir Modbus Heat Pump", manufacturer="FoxAir/PHNIX", model="Modbus TCP")
        dtype=info.get("type","RAW")
        dc, unit, sc = DTYPE_MAP.get(dtype, (None, info.get("unit") or None, SensorStateClass.MEASUREMENT))
        if dc: self._attr_device_class=dc
        if unit: self._attr_native_unit_of_measurement=unit
        elif info.get("unit"): self._attr_native_unit_of_measurement=info.get("unit")
        if sc: self._attr_state_class=sc
        # precision
        if dtype in ("TEMP1","TEMP"): self._attr_suggested_display_precision=1
        elif dtype=="VOLT": self._attr_suggested_display_precision=0
        self._attr_entity_registry_enabled_default=addr in POPULAR_ADDRS
        if addr not in POPULAR_ADDRS:
            self._attr_entity_category="diagnostic"
    @property
    def native_value(self):
        rec=self.coordinator.data.get(self._addr)
        return rec["value"] if rec else None
    @property
    def extra_state_attributes(self):
        rec=self.coordinator.data.get(self._addr)
        if not rec: return {}
        info=rec.get("info",{})
        return {"raw": rec.get("raw"), "address": self._addr, "block": info.get("block"), "code": info.get("code"), "type": info.get("type")}
