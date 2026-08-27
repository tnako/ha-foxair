"""Separate power On/Off switch (register 1011) for the FoxAir heat pump.

The combined operation mode lives in register 1012; power is independent in
1011. Exposing 1011 as its own switch keeps the climate card's On/Off from
being overloaded onto the mode selection.
"""
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import main_device
import logging

_LOGGER = logging.getLogger(__name__)

POWER_ADDR = 1011  # 0 = Aus, 1 = Ein


class FoxAirPowerSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "foxair_power"
    _attr_icon = "mdi:power"

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = "foxair_power"
        self._optimistic = None  # on/off shown during a write round-trip
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        self._attr_device_info = main_device(entry_id)

    @property
    def is_on(self):
        if self._optimistic is not None:
            return self._optimistic
        rec = self.coordinator.data.get(POWER_ADDR)
        if not rec:
            return False
        return rec.get("raw") == 1

    async def async_turn_on(self, **kwargs):
        # show ON instantly so the toggle doesn't appear frozen during the
        # Modbus write + read-back round-trip
        self._optimistic = True
        self._attr_assumed_state = True
        self.async_write_ha_state()
        ok = await self.coordinator.async_write_register(POWER_ADDR, 1.0)
        self._optimistic = None
        self._attr_assumed_state = False
        self.async_write_ha_state()
        if not ok:
            raise ValueError("Failed to power ON")

    async def async_turn_off(self, **kwargs):
        self._optimistic = False
        self._attr_assumed_state = True
        self.async_write_ha_state()
        ok = await self.coordinator.async_write_register(POWER_ADDR, 0.0)
        self._optimistic = None
        self._attr_assumed_state = False
        self.async_write_ha_state()
        if not ok:
            raise ValueError("Failed to power OFF")


async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    add_entities([FoxAirPowerSwitch(coord)])
