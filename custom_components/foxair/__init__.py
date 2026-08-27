from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from .coordinator import FoxAirCoordinator
from .const import DOMAIN

PLATFORMS = ["sensor", "climate"]

async def _cleanup_orphaned_devices(hass: HomeAssistant):
    """Remove legacy per-block devices left from <0.2.3 (foxair_H, foxair_A, etc).
    Single device is (DOMAIN, "foxair"); everything (DOMAIN, "foxair_*") is orphan."""
    try:
        registry = dr.async_get(hass)
        for device in list(registry.devices.values()):
            for ident in list(device.identifiers):
                if ident[0] == DOMAIN and ident[1] != "foxair" and ident[1].startswith("foxair"):
                    # only remove if it looks like legacy block device
                    registry.async_remove_device(device.id)
                    break
    except Exception:
        pass

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    coord = FoxAirCoordinator(hass, entry)
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault("foxair", {})[entry.entry_id] = coord
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # cleanup after platforms are set up - fire and forget
    hass.async_create_task(_cleanup_orphaned_devices(hass))
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
