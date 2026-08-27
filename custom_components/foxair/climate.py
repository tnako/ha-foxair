from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature, HVACAction
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import main_device
import logging
_LOGGER = logging.getLogger(__name__)

# 1011 ON/OFF, 1012 mode: 0=DHW only,1=Heat,2=Cool,3=DHW+Heat,4=DHW+Cool
HVAC_MAP = {0: HVACMode.HEAT, 1: HVACMode.HEAT, 2: HVACMode.COOL, 3: HVACMode.HEAT_COOL, 4: HVACMode.HEAT_COOL}
MODE_TO_TEMP_ADDR = {HVACMode.HEAT: 1158, HVACMode.COOL: 1159, HVACMode.HEAT_COOL: 1158, HVACMode.OFF: 1158}
RAW_MODE_TO_TARGET = {0: 1157, 1: 1158, 2: 1159, 3: 1158, 4: 1159}
HVAC_REV = {HVACMode.HEAT: 1, HVACMode.COOL: 2, HVACMode.HEAT_COOL: 3, HVACMode.OFF: 0}

class FoxAirClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "foxair_climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]
    _attr_preset_modes = ["dhw_only","heat_only","cool_only","dhw+heat","dhw+cool"]

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = "foxair_climate"
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        self._attr_device_info = main_device(entry_id)

    def _raw_mode(self):
        rec = self.coordinator.data.get(1012)
        return rec["raw"] if rec else 1

    @property
    def min_temp(self):
        addr = RAW_MODE_TO_TARGET.get(self._raw_mode(), 1158)
        meta = self.coordinator.get_metadata(addr) if hasattr(self.coordinator, "get_metadata") else {}
        lo = meta.get("min")
        return float(lo) if lo is not None else (15.0 if addr==1158 else 7.0)
    @property
    def max_temp(self):
        addr = RAW_MODE_TO_TARGET.get(self._raw_mode(), 1158)
        meta = self.coordinator.get_metadata(addr) if hasattr(self.coordinator, "get_metadata") else {}
        hi = meta.get("max")
        return float(hi) if hi is not None else (60.0 if addr==1158 else 28.0)

    @property
    def current_temperature(self):
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
        if raw == 0:
            return HVACMode.HEAT
        return HVAC_MAP.get(raw, HVACMode.HEAT)

    @property
    def preset_mode(self):
        raw = self._raw_mode()
        return {0:"dhw_only",1:"heat_only",2:"cool_only",3:"dhw+heat",4:"dhw+cool"}.get(raw)

    @property
    def hvac_action(self):
        off = self.coordinator.data.get(1011)
        if off and off["raw"] == 0:
            return HVACAction.OFF
        status = self.coordinator.data.get(2012)
        if status:
            raw = status.get("raw")
            if raw == 1: return HVACAction.HEATING
            if raw == 0: return HVACAction.COOLING
            if raw == 2: return HVACAction.DEFROSTING if hasattr(HVACAction, "DEFROSTING") else HVACAction.HEATING
            if raw == 4: return HVACAction.HEATING
            if raw == 3: return HVACAction.IDLE
        freq = self.coordinator.data.get(2072)
        if freq and freq.get("value", 0) > 0:
            raw_mode = self._raw_mode()
            if raw_mode in (2,4): return HVACAction.COOLING
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self):
        raw_mode = self._raw_mode()
        return {"raw_mode": raw_mode, "mode_code": {0:"DHW",1:"Heat",2:"Cool",3:"DHW+Heat",4:"DHW+Cool"}.get(raw_mode, str(raw_mode)), "target_addr": RAW_MODE_TO_TARGET.get(raw_mode), "dhw_mode": raw_mode in (0,3,4), "control_mode": "weather_curve" if self.coordinator.data.get(1236, {}).get("raw")==1 else "fixed"}

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is None: return
        raw_mode = self._raw_mode()
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
        ok = await self.coordinator.async_write_register(1011, 1)
        if not ok: raise ValueError("Failed to set ON")
        raw_target = HVAC_REV.get(hvac_mode, 1)
        if hvac_mode == HVACMode.HEAT_COOL:
            prev_raw = self._raw_mode()
            if prev_raw in (4,2):
                raw_target = 4
            else:
                raw_target = 3
        ok = await self.coordinator.async_write_register(1012, float(raw_target))
        if not ok: raise ValueError(f"Failed to set mode {hvac_mode}")

    async def async_set_preset_mode(self, preset_mode):
        mapping = {"dhw_only":0,"heat_only":1,"cool_only":2,"dhw+heat":3,"dhw+cool":4}
        raw = mapping.get(preset_mode)
        if raw is None: raise ValueError(f"Unknown preset {preset_mode}")
        ok = await self.coordinator.async_write_register(1011, 1)
        if not ok: raise ValueError("Failed power ON")
        ok = await self.coordinator.async_write_register(1012, float(raw))
        if not ok: raise ValueError(f"Failed set preset {preset_mode}")

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    add_entities([FoxAirClimate(coord)])
