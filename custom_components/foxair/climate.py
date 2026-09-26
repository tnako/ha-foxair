"""Heat pump climate entity.

Sensor, setpoint, curve and limits come from heating_curve.active_control(),
which follows H25 (control source), 1012 (mode) and H36 (curve) via
foxair_config.json markers. With the curve active a new target shifts the
curve offset by the same delta (target = offset - slope * AT is linear). Never hardcode a register here: validate.py fails
on marker register literals, check_regs.py verifies the wiring live.
"""
import time

from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature, HVACAction
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import main_device, get_device_prefix, get_slave_id, bind_device_info
from .computed import active_mode, heat_output_active
from .heating_curve import active_control, curve_target_for_at, mode_values


class FoxAirClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    _attr_icon = "mdi:heat-pump"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_translation_key = "foxair_climate"

    # preset name -> markers.status.mode_values key; dhw_only is read-only and shown as Heating + Hot Water
    PRESET_KEY = {
        "Heating": "heating",
        "Cooling": "cooling",
        "Heating + Hot Water": "heating_dhw",
        "Cooling + Hot Water": "cooling_dhw",
    }
    _attr_preset_modes = list(PRESET_KEY)
    CURVE_HOLD_S = 90

    ACTIVE_ACTION = {
        "heating": HVACAction.HEATING,
        "cooling": HVACAction.COOLING,
        "defrost": getattr(HVACAction, "DEFROSTING", HVACAction.HEATING),
        "dhw": HVACAction.HEATING,
    }

    def __init__(self, coord):
        super().__init__(coord)
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_climate"
        self.entity_id = f"climate.{prefix}_climate"
        self._opt_hvac = None
        self._opt_preset = None
        self._opt_curve = None
        entry_id = coord.entry.entry_id
        self._attr_device_info = bind_device_info(
            getattr(coord, "hass", None), entry_id,
            main_device(entry_id, prefix, get_slave_id(coord.entry), coord.entry.data.get("host"), coord.entry.data.get("port")),
        )

    def _addr(self, marker_name, key):
        return (self.coordinator.marker(marker_name).get("addr_single") or {}).get(key)

    def _rec(self, addr):
        return self.coordinator.data.get(addr) if addr else None

    def _raw(self, marker_name, key):
        rec = self._rec(self._addr(marker_name, key))
        return rec.get("raw") if rec else None

    def _value(self, addr):
        rec = self._rec(addr)
        return rec.get("value") if rec else None

    def _raw_mode(self):
        return self._raw("status", "mode")

    def _mode_key(self):
        raw = self._raw_mode()
        return next((k for k, v in mode_values(self.coordinator).items() if v == raw), None)

    def _control(self):
        return active_control(self.coordinator)

    @property
    def control_mode(self):
        """'weather_curve' when H36 AT-compensation is enabled, else 'fixed'."""
        return "weather_curve" if self._raw("heat_curve", "at_comp_en") == 1 else "fixed"

    def _curve_target(self):
        """Live curve target: device register 2014, formula only as fallback."""
        live = self._value(self._addr("heat_curve", "live_target"))
        if live is not None:
            return round(float(live), 1)
        at = self._value(self._addr("heat_curve", "at_sensor"))
        if at is None:
            return None
        ct = curve_target_for_at(self.coordinator, float(at))
        return round(ct, 1) if ct is not None else None

    def _pending_curve(self, live):
        """(target, offset) of an offset shift the device has not reflected in 2014 yet, else None."""
        if self._opt_curve is not None:
            target, _, until = self._opt_curve
            if time.monotonic() > until or (live is not None and abs(live - target) < 0.05):
                self._opt_curve = None
        return self._opt_curve[:2] if self._opt_curve else None

    def _display_curve_target(self):
        live = self._curve_target()
        pending = self._pending_curve(live)
        return pending[0] if pending else live

    def _limit(self, bound):
        """Device setpoint limit (R08-R11) for water sources, else the setpoint's register metadata."""
        ctl = self._control()
        v = self._value(ctl.get(bound))
        if v is None and ctl.get("target"):
            v = self.coordinator.get_metadata(ctl["target"]).get(bound)
        return float(v) if v is not None else None

    @property
    def target_temperature(self):
        ctl = self._control()
        return self._display_curve_target() if ctl.get("curve") else self._value(ctl.get("target"))

    @property
    def min_temp(self):
        lo = self._limit("min")
        return lo if lo is not None else super().min_temp

    @property
    def max_temp(self):
        hi = self._limit("max")
        return hi if hi is not None else super().max_temp

    @property
    def current_temperature(self):
        return self._value(self._control().get("current"))

    @property
    def hvac_mode(self):
        if self._opt_hvac is not None:
            return self._opt_hvac
        return HVACMode.OFF if self._raw("status", "power") == 0 else HVACMode.HEAT

    @property
    def preset_mode(self):
        if self._opt_preset is not None:
            return self._opt_preset
        key = self._mode_key()
        if key == "dhw_only":
            key = "heating_dhw"
        return next((p for p, k in self.PRESET_KEY.items() if k == key), "Heating")

    @property
    def hvac_action(self):
        if self._raw("status", "power") == 0:
            return HVACAction.OFF
        mode = active_mode(self.coordinator)
        action = self.ACTIVE_ACTION.get(mode)
        if action is not None:
            if mode != "defrost" and heat_output_active(self.coordinator) is False:
                return HVACAction.IDLE
            return action
        freq = self._value(self._addr("status", "compressor_freq"))
        if freq and freq > 0:
            return HVACAction.COOLING if self._control().get("cooling") else HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self):
        key = self._mode_key()
        ctl = self._control()
        return {
            "raw_mode": self._raw_mode(),
            "mode_code": key,
            "dhw_mode": key in ("heating_dhw", "cooling_dhw", "dhw_only"),
            "control_mode": self.control_mode,
            "control_source": ctl.get("source"),
            "current_addr": ctl.get("current"),
            "target_addr": ctl.get("target"),
            "at": self._value(self._addr("heat_curve", "at_sensor")),
        }

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is None:
            return
        ctl = self._control()
        if ctl.get("curve"):
            await self._shift_curve(float(temp))
            return
        addr = ctl.get("target")
        if not await self.coordinator.async_write_register(addr, float(temp)):
            raise ValueError(f"Set temp {temp} rejected (addr {addr})")

    async def _shift_curve(self, temp):
        """Move the whole heating curve so the current curve target becomes temp."""
        live = self._curve_target()
        pending = self._pending_curve(live)
        off_addr = self._addr("heat_curve", "offset")
        base, offset = pending if pending else (live, self._value(off_addr))
        if base is None or offset is None:
            raise ValueError("Heating curve target or offset not read yet, try again after the next poll")
        new_offset = round(float(offset) + temp - base, 1)
        prev = self._opt_curve
        self._opt_curve = (round(temp, 1), new_offset, time.monotonic() + self.CURVE_HOLD_S)
        self.async_write_ha_state()
        if not await self.coordinator.async_write_register(off_addr, new_offset):
            self._opt_curve = prev
            self.async_write_ha_state()
            raise ValueError(f"Heating curve offset {new_offset} rejected (addr {off_addr})")

    async def _optimistic_write(self, attr, value, mapping, error):
        setattr(self, attr, value)
        self._attr_assumed_state = True
        self.async_write_ha_state()
        try:
            if not await self.coordinator.async_write_many(mapping):
                raise ValueError(error)
        finally:
            setattr(self, attr, None)
            self._attr_assumed_state = False
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        power = self._addr("status", "power")
        if hvac_mode == HVACMode.OFF:
            mapping = {power: 0.0}
        elif self._mode_key() in self.PRESET_KEY.values():
            mapping = {power: 1.0}
        else:
            mapping = {power: 1.0, self._addr("status", "mode"): float(mode_values(self.coordinator)["heating"])}
        await self._optimistic_write("_opt_hvac", hvac_mode, mapping, f"Failed to set {hvac_mode}")

    async def async_set_preset_mode(self, preset_mode):
        raw = mode_values(self.coordinator).get(self.PRESET_KEY.get(preset_mode))
        if raw is None:
            raise ValueError(f"Unknown preset {preset_mode}")
        mapping = {self._addr("status", "power"): 1.0, self._addr("status", "mode"): float(raw)}
        await self._optimistic_write("_opt_preset", preset_mode, mapping, f"Failed set preset {preset_mode}")


async def async_setup_entry(hass, entry, add_entities):
    add_entities([FoxAirClimate(entry.runtime_data)])
