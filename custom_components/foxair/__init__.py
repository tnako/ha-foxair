from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .coordinator import FoxAirCoordinator

PLATFORMS = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    coord = FoxAirCoordinator(hass, entry)
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault("foxair", {})[entry.entry_id] = coord
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data["foxair"].pop(entry.entry_id, None)
    return True
