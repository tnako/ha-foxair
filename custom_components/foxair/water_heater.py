"""Water heater (DHW tank): target R01, tank temperature T08, limits R36/R37.

Registers come from the dhw marker in foxair_config.json. On/off and the
operation mode are not exposed here: the unit's mode word (1012) combines
heating/cooling with DHW, the climate presets own it.
"""
from homeassistant.components.water_heater import STATE_HEAT_PUMP, WaterHeaterEntity, WaterHeaterEntityFeature
from homeassistant.const import STATE_OFF, UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import bind_device_info, get_device_prefix, get_slave_id, main_device
from .heating_curve import mode_values

DHW_MODES = ("dhw_only", "heating_dhw", "cooling_dhw")


async def async_setup_entry(hass, entry, add_entities):
    coord = entry.runtime_data
    if (coord.marker("dhw").get("addr_single") or {}).get("target"):
        add_entities([FoxAirWaterHeater(coord)])


class FoxAirWaterHeater(CoordinatorEntity, WaterHeaterEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "foxair_dhw"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 0.5
    _attr_precision = 0.1
    _attr_icon = "mdi:water-boiler"
    _attr_operation_list = [STATE_HEAT_PUMP, STATE_OFF]

    def __init__(self, coord):
        super().__init__(coord)
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_dhw"
        self.entity_id = f"water_heater.{prefix}_dhw"
        entry_id = coord.entry.entry_id
        self._attr_device_info = bind_device_info(
            getattr(coord, "hass", None), entry_id,
            main_device(entry_id, prefix, get_slave_id(coord.entry), coord.entry.data.get("host"), coord.entry.data.get("port")),
        )

    def _addr(self, key):
        return (self.coordinator.marker("dhw").get("addr_single") or {}).get(key)

    def _rec(self, key):
        addr = self._addr(key)
        return (self.coordinator.data or {}).get(addr) if addr else None

    def _value(self, key):
        rec = self._rec(key)
        v = rec.get("value") if rec else None
        return float(v) if v is not None else None

    @property
    def available(self):
        enabled = self._rec("enabled")
        if enabled is not None and enabled.get("raw") == 0:
            return False
        return self._rec("target") is not None and super().available

    @property
    def current_operation(self):
        """heat_pump while the 1012 mode includes DHW, else off (read-only, set via the climate presets)."""
        addr = (self.coordinator.marker("status").get("addr_single") or {}).get("mode")
        raw = ((self.coordinator.data or {}).get(addr) or {}).get("raw")
        if raw is None:
            return None
        mv = mode_values(self.coordinator)
        return STATE_HEAT_PUMP if raw in {mv.get(k) for k in DHW_MODES} else STATE_OFF

    @property
    def current_temperature(self):
        return self._value("current")

    @property
    def target_temperature(self):
        return self._value("target")

    @property
    def min_temp(self):
        v = self._value("min")
        return v if v is not None else self.coordinator.get_metadata(self._addr("target")).get("min") or 30.0

    @property
    def max_temp(self):
        v = self._value("max")
        return v if v is not None else self.coordinator.get_metadata(self._addr("target")).get("max") or 60.0

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is None:
            return
        temp = float(temp)
        if not self.min_temp <= temp <= self.max_temp:
            raise ValueError(f"DHW target {temp} outside {self.min_temp}-{self.max_temp}")
        addr = self._addr("target")
        if not await self.coordinator.async_write_register(addr, temp):
            raise ValueError(f"DHW target {temp} rejected (addr {addr})")
