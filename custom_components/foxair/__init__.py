from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .coordinator import FoxAirCoordinator

PLATFORMS = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    coord = FoxAirCoordinator(hass, entry)
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault("foxair", {})[entry.entry_id] = coord
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data["foxair"].pop(entry.entry_id, None)
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if coord and coord.client:
        try: coord.client.close()
        except: pass
    return True
