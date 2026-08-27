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
    # ensure metadata ready for category logic
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    for addr, rec in coord.data.items():
        if rec.get("info", {}).get("type") == "BLOCK":
            continue
        # hide blocked headers already via BLOCK, but also honor metadata blocked
        meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        if meta.get("risk") == "blocked":
            continue
        ents.append(FoxSensor(coord, addr))
    # heating curve computed target (always visible, no expert needed)
    ents.append(FoxHeatingCurveTargetSensor(coord))
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
        # v0.3 metadata-aware category
        try:
            meta = coord.get_metadata(addr) if hasattr(coord, "get_metadata") else {}
        except: meta={}
        risk = meta.get("risk")
        if addr in HIDDEN or risk == "blocked":
            self._attr_entity_registry_enabled_default = False
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif risk == "dangerous":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            # keep enabled per POPULAR but diagnostic still hides
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
            if addr not in POPULAR_ADDRS:
                self._attr_entity_registry_enabled_default = False
        elif risk == "advanced":
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
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
        meta = {}
        try: meta = self.coordinator.get_metadata(self._addr)
        except: pass
        return {"raw": rec.get("raw"), "address": self._addr, "block": info.get("block"), "code": info.get("code"), "type": info.get("type"), "group": meta.get("group"), "risk": meta.get("risk"), "editable": meta.get("editable"), "min": meta.get("min"), "max": meta.get("max")}
class FoxHeatingCurveTargetSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "foxair_heating_curve_target"
    _attr_name = "Heating Curve Target"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-bell-curve"
    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = "foxair_heating_curve_target"
        self._attr_device_info = DEVICE
    @property
    def native_value(self):
        try:
            from .heating_curve import curve_target_for_at
            at = self.coordinator.data.get(2048, {}).get("value")
            if at is None: return None
            v = curve_target_for_at(self.coordinator, float(at))
            return round(v,1) if v is not None else None
        except: return None
    @property
    def extra_state_attributes(self):
        try:
            at = self.coordinator.data.get(2048, {}).get("value")
            slope = self.coordinator.data.get(1234, {}).get("value")
            offset = self.coordinator.data.get(1235, {}).get("value")
            en = self.coordinator.data.get(1236, {}).get("raw")
            fixed = self.coordinator.data.get(1158, {}).get("value")
            after = self.coordinator.data.get(2014, {}).get("value")
            r10 = self.coordinator.data.get(1164, {}).get("value")
            r11 = self.coordinator.data.get(1165, {}).get("value")
            return {"at": at, "slope": slope, "offset": offset, "h36_enable": en, "fixed_r02": fixed, "after_comp_2014": after, "r10_min": r10, "r11_max": r11, "panel": "/api/foxair/heating-curve-panel", "svg": "/api/foxair/heating_curve.svg"}
        except: return {}

