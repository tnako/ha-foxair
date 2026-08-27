from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature, HVACAction
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN
import logging
_LOGGER = logging.getLogger(__name__)

# 1011 ON/OFF, 1012 mode: 0=DHW,1=Heat,2=Cool,3=DHW+Heat,4=DHW+Cool
# HA has 4 hvac_modes, so we collapse 3/4 to HEAT_COOL and expose DHW via attribute
HVAC_MAP = {0: HVACMode.OFF, 1: HVACMode.HEAT, 2: HVACMode.COOL, 3: HVACMode.HEAT_COOL, 4: HVACMode.HEAT_COOL}
HVAC_REV = {HVACMode.HEAT: 1, HVACMode.COOL: 2, HVACMode.HEAT_COOL: 3, HVACMode.OFF: 0}
MODE_TO_TEMP_ADDR = {HVACMode.HEAT: 1158, HVACMode.COOL: 1159, HVACMode.HEAT_COOL: 1158, HVACMode.OFF: 1158}
# Cooling logic: if raw mode 4 (DHW+Cool) we treat target as COOL setpoint, else HEAT for HEAT_COOL
RAW_MODE_TO_TARGET = {0: 1158, 1: 1158, 2: 1159, 3: 1158, 4: 1159}

class FoxAirClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "foxair_climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]
    _attr_min_temp = 15
    _attr_max_temp = 55

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = "foxair_climate"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "foxair")}, name="FoxAir Modbus Heat Pump", manufacturer="FoxAir/PHNIX", model="Modbus TCP Heat Pump")
        # dynamic limits from metadata
        meta_heat = coord.get_metadata(1158) if hasattr(coord, "get_metadata") else {}
        meta_cool = coord.get_metadata(1159) if hasattr(coord, "get_metadata") else {}
        if meta_heat.get("min") is not None: self._attr_min_temp = float(meta_heat["min"])
        if meta_heat.get("max") is not None: self._attr_max_temp = float(meta_heat["max"])

    def _raw_mode(self):
        rec = self.coordinator.data.get(1012)
        return rec["raw"] if rec else 1

    @property
    def current_temperature(self):
        # outlet water T02 2046 is control temp per H25
        rec = self.coordinator.data.get(2046)
        return rec["value"] if rec else None

    @property
    def target_temperature(self):
        raw_mode = self._raw_mode()
        addr = RAW_MODE_TO_TARGET.get(raw_mode, 1158)
        rec = self.coordinator.data.get(addr)
        return rec["value"] if rec else None

    @property
    def hvac_mode(self):
        off = self.coordinator.data.get(1011)
        if off and off["raw"] == 0:
            return HVACMode.OFF
        raw = self._raw_mode()
        return HVAC_MAP.get(raw, HVACMode.HEAT)

    @property
    def hvac_action(self):
        # derive from compressor freq 2072 + mode
        off = self.coordinator.data.get(1011)
        if off and off["raw"] == 0:
            return HVACAction.OFF
        freq = self.coordinator.data.get(2072)
        if freq and freq.get("value", 0) > 0:
            return HVACAction.HEATING if self.hvac_mode in (HVACMode.HEAT, HVACMode.HEAT_COOL) else HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self):
        raw_mode = self._raw_mode()
        return {"raw_mode": raw_mode, "mode_code": {0:"DHW",1:"Heat",2:"Cool",3:"DHW+Heat",4:"DHW+Cool"}.get(raw_mode, str(raw_mode)), "target_addr": RAW_MODE_TO_TARGET.get(raw_mode)}

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is None: return
        raw_mode = self._raw_mode()
        # if caller also sets hvac_mode, respect it
        hvac = kwargs.get("hvac_mode")
        if hvac:
            addr = MODE_TO_TEMP_ADDR.get(hvac, RAW_MODE_TO_TARGET.get(raw_mode, 1158))
        else:
            addr = RAW_MODE_TO_TARGET.get(raw_mode, 1158)
        ok = await self.coordinator.async_write_register(addr, float(temp))
        if not ok:
            raise ValueError(f"Set temp {temp} rejected (addr {addr})")

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode == HVACMode.OFF:
            ok = await self.coordinator.async_write_register(1011, 0)
            if not ok: raise ValueError("Failed to set OFF")
            return
        # ensure power ON
        ok = await self.coordinator.async_write_register(1011, 1)
        if not ok: raise ValueError("Failed to set ON")
        raw_target = HVAC_REV.get(hvac_mode, 1)
        # HEAT_COOL default to 3 (DHW+Heat); if currently 4 and user selects HEAT_COOL keep 4 when cooling season? Keep 3 as safe
        # Check ambient vs logic? keep 3
        ok = await self.coordinator.async_write_register(1012, float(raw_target))
        if not ok: raise ValueError(f"Failed to set mode {hvac_mode}")

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    add_entities([FoxAirClimate(coord)])
