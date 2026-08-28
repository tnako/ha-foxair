from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature, HVACAction
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import main_device
from .heating_curve import curve_target_for_at
import logging
_LOGGER = logging.getLogger(__name__)

AT_ADDR = 2048  # outdoor / ambient temperature used for weather compensation

# 1011 ON/OFF, 1012 mode: 0=DHW only,1=Heat,2=Cool,3=DHW+Heat,4=DHW+Cool
# hvac is now pure On/Off (OFF vs On), preset carries the 4 DHW+Heat/Cool combos
HVAC_MAP = {0: HVACMode.HEAT, 1: HVACMode.HEAT, 2: HVACMode.HEAT, 3: HVACMode.HEAT, 4: HVACMode.HEAT}
MODE_TO_TEMP_ADDR = {HVACMode.HEAT: 1158, HVACMode.OFF: 1158}
RAW_MODE_TO_TARGET = {0: 1158, 1: 1158, 2: 1159, 3: 1158, 4: 1159}
# hvac mode -> raw 1012 (not used now, On keeps current preset)
HVAC_REV = {HVACMode.OFF: 0, HVACMode.HEAT: 1}
# preset = DHW Off/On x Heating/Cooling (4 combos); Hot Water only (0) is legacy read-only
PRESET_RAW = {
    "Heating": 1,
    "Cooling": 2,
    "Heating + Hot Water": 3,
    "Cooling + Hot Water": 4,
}
RAW_PRESET = {v: k for k, v in PRESET_RAW.items()}
# legacy 0 still readable but not selectable
RAW_PRESET[0] = "Heating + Hot Water"

class FoxAirClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "foxair_climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    _attr_icon = "mdi:heat-pump"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = ["Heating", "Cooling", "Heating + Hot Water", "Cooling + Hot Water"]

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = "foxair_climate"
        self._opt_hvac = None    # optimistic hvac_mode during write round-trip
        self._opt_preset = None  # optimistic preset_mode during write round-trip
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        self._attr_device_info = main_device(entry_id)

    def _raw_mode(self):
        rec = self.coordinator.data.get(1012)
        return rec["raw"] if rec else 1

    @property
    def min_temp(self):
        if self.control_mode == "weather_curve":
            # pin the slider to the live curve target so it shows the value
            # but cannot be dragged (target is derived, not settable)
            ct = self._curve_target()
            if ct is not None:
                return ct
        addr = RAW_MODE_TO_TARGET.get(self._raw_mode(), 1158)
        meta = self.coordinator.get_metadata(addr) if hasattr(self.coordinator, "get_metadata") else {}
        lo = meta.get("min")
        return float(lo) if lo is not None else (15.0 if addr==1158 else 7.0)
    @property
    def max_temp(self):
        if self.control_mode == "weather_curve":
            ct = self._curve_target()
            if ct is not None:
                return ct
        addr = RAW_MODE_TO_TARGET.get(self._raw_mode(), 1158)
        meta = self.coordinator.get_metadata(addr) if hasattr(self.coordinator, "get_metadata") else {}
        hi = meta.get("max")
        return float(hi) if hi is not None else (60.0 if addr==1158 else 28.0)

    @property
    def current_temperature(self):
        rec = self.coordinator.data.get(2046)
        return rec["value"] if rec else None

    def _curve_target(self):
        """Live AT-compensation target.

        Prefer the heat pump's own computed target in register 2014
        ("Temperaturwert nach Wetterkompensation während des Heizens", TEMP1 ->
        °C) — this is the exact value the vendor app shows, so it guarantees
        parity. Fall back to the offset/slope formula only if 2014 is missing.
        """
        try:
            dev = self.coordinator.data.get(2014, {}).get("value")
            if dev is not None:
                return round(float(dev), 1)
        except Exception:
            pass
        try:
            at = self.coordinator.data.get(AT_ADDR, {}).get("value")
            if at is None:
                return None
            ct = curve_target_for_at(self.coordinator, float(at))
            return round(ct, 1) if ct is not None else None
        except Exception:
            return None

    @property
    def target_temperature(self):
        # In AT-compensation (weather-curve) mode the effective target is the
        # live curve value computed from outdoor temperature, NOT the fixed
        # setpoint register. Only in fixed mode do we show the fixed setpoint.
        if self.control_mode == "weather_curve":
            return self._curve_target()
        raw_mode = self._raw_mode()
        addr = RAW_MODE_TO_TARGET.get(raw_mode, 1158)
        rec = self.coordinator.data.get(addr)
        return rec["value"] if rec else None

    @property
    def control_mode(self):
        """'weather_curve' when H36 AT-compensation is enabled, else 'fixed'."""
        return "weather_curve" if self.coordinator.data.get(1236, {}).get("raw") == 1 else "fixed"

    @property
    def supported_features(self):
        # The target is always displayed: in fixed mode it is an editable
        # slider; in AT-compensation mode it is the derived curve value with
        # min==max (locked, not draggable) — but still visible. PRESET_MODE
        # lets the user switch operation mode.
        return ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE

    @property
    def hvac_mode(self):
        if self._opt_hvac is not None:
            return self._opt_hvac
        # On/Off is pure power (1011); On always shows as HEAT
        off = self.coordinator.data.get(1011)
        if off and off["raw"] == 0:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def preset_mode(self):
        if self._opt_preset is not None:
            return self._opt_preset
        raw = self._raw_mode()
        # 0 (Hot Water only) is legacy — show as Heating + Hot Water
        if raw == 0:
            return "Heating + Hot Water"
        return RAW_PRESET.get(raw, "Heating")

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
            if raw_mode in (2, 4): return HVACAction.COOLING
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self):
        raw_mode = self._raw_mode()
        at = self.coordinator.data.get(AT_ADDR, {}).get("value")
        return {
            "raw_mode": raw_mode,
            "mode_code": {0: "Heating + Hot Water", 1: "Heating", 2: "Cooling", 3: "Heating + Hot Water", 4: "Cooling + Hot Water"}.get(raw_mode, str(raw_mode)),
            "target_addr": RAW_MODE_TO_TARGET.get(raw_mode),
            "dhw_mode": raw_mode in (0, 3, 4),
            "control_mode": self.control_mode,
            "at": at,
        }

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is None:
            return
        # In AT-compensation mode the target is derived from the curve
        # (offset/slope + outdoor temp), so it cannot be set directly.
        # The fixed setpoint register is ignored by the device in this mode.
        if self.control_mode == "weather_curve":
            raise ValueError(
                "Cannot set target_temperature directly in AT-compensation "
                "(weather-curve) mode. Tune the curve via number.foxair_1234 (slope) "
                "and number.foxair_1235 (offset) instead."
            )
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
        # hvac is pure On/Off — batched with 3s debounce in coordinator (1011+1012 -> one FC16)
        self._opt_hvac = hvac_mode
        self._attr_assumed_state = True
        self.async_write_ha_state()
        try:
            if hvac_mode == HVACMode.OFF:
                ok = await self.coordinator.async_write_register(1011, 0)
                if not ok:
                    raise ValueError("Failed to set OFF")
                return
            # On: power on, keep existing preset (if 0, default to Heating)
            raw = self._raw_mode()
            if raw == 0:
                ok = await self.coordinator.async_write_many({1011: 1.0, 1012: 1.0})
            else:
                ok = await self.coordinator.async_write_register(1011, 1)
            if not ok:
                raise ValueError("Failed to power ON")
        finally:
            self._opt_hvac = None
            self._attr_assumed_state = False
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode):
        raw = PRESET_RAW.get(preset_mode)
        if raw is None:
            raise ValueError(f"Unknown preset {preset_mode}")
        # show the new preset instantly during the write round-trip
        self._opt_preset = preset_mode
        self._attr_assumed_state = True
        self.async_write_ha_state()
        try:
            # Batch 1011+1012 into one FC16 (debounced 3s) — avoids conflict where 1012 written while still Off
            ok = await self.coordinator.async_write_many({1011: 1.0, 1012: float(raw)})
            if not ok:
                raise ValueError(f"Failed set preset {preset_mode}")
        finally:
            self._opt_preset = None
            self._attr_assumed_state = False
            self.async_write_ha_state()

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    add_entities([FoxAirClimate(coord)])
