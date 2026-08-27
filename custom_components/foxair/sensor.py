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
    "DIGI4": (None, None, SensorStateClass.MEASUREMENT),
    "DIGI5": (None, None, SensorStateClass.MEASUREMENT),
    "DIGI6": (None, None, SensorStateClass.MEASUREMENT),
    "DIGI19": (None, None, SensorStateClass.MEASUREMENT),
    "FLOW_M3H_X100": (None, "m³/h", SensorStateClass.MEASUREMENT),
    "FLOW_M3H_X10": (None, "m³/h", SensorStateClass.MEASUREMENT),
    "BAR_X10": (SensorDeviceClass.PRESSURE, "bar", SensorStateClass.MEASUREMENT),
    "AMP_X10": (SensorDeviceClass.CURRENT, "A", SensorStateClass.MEASUREMENT),
    "AMP_X2": (SensorDeviceClass.CURRENT, "A", SensorStateClass.MEASUREMENT),
    "POWER_KW_X10": (SensorDeviceClass.POWER, "kW", SensorStateClass.MEASUREMENT),
    "KWH": (SensorDeviceClass.ENERGY, "kWh", SensorStateClass.TOTAL_INCREASING),
    "WATT": (SensorDeviceClass.POWER, "W", SensorStateClass.MEASUREMENT),
    "RPM": (None, "rpm", SensorStateClass.MEASUREMENT),
    "COP_X100": (None, None, SensorStateClass.MEASUREMENT),
    "STEPS_N": (None, "steps", SensorStateClass.MEASUREMENT),
    "MINUTES": (SensorDeviceClass.DURATION, "min", SensorStateClass.MEASUREMENT),
    "SECONDS": (SensorDeviceClass.DURATION, "s", SensorStateClass.MEASUREMENT),
    "HOURS": (SensorDeviceClass.DURATION, "h", SensorStateClass.MEASUREMENT),
    "DAYS": (SensorDeviceClass.DURATION, "days", SensorStateClass.MEASUREMENT),
    "TIME_HHMM": (None, None, None),
    "BITFIELD": (None, None, None),
    "TIMER_BITPAIR": (None, None, None),
    "TIMER_MODE": (None, None, None),
    "SG_MODE": (None, None, None),
    "MODE_0_4": (None, None, None),
    "RAW": (None, None, None),
    "BLOCK": (None, None, None),
}

HIDDEN = {2057}
DEVICE = DeviceInfo(identifiers={(DOMAIN, "foxair")}, name="FoxAir Modbus Heat Pump", manufacturer="FoxAir/PHNIX", model="Modbus TCP Heat Pump")

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    ents = []
    for addr, rec in coord.data.items():
        if rec.get("info", {}).get("type") == "BLOCK":
            continue
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
        self._attr_device_info = DEVICE
        dtype = info.get("type","RAW")
        dc, unit, sc = DTYPE_MAP.get(dtype, (None, info.get("unit") or None, None))
        if dc: self._attr_device_class = dc
        if unit: self._attr_native_unit_of_measurement = unit
        elif info.get("unit"): self._attr_native_unit_of_measurement = info.get("unit")
        if sc: self._attr_state_class = sc
        if dtype in ("TEMP1","TEMP","TEMP05"): self._attr_suggested_display_precision = 1
        elif dtype in ("VOLT","BAR_X10","POWER_KW_X10"): self._attr_suggested_display_precision = 1
        elif dtype == "FLOW_M3H_X100": self._attr_suggested_display_precision = 2
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
