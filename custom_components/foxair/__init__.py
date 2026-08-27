from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from .coordinator import FoxAirCoordinator
from .const import DOMAIN
from .views import FoxAirCurveSvgView, FoxAirCurvePanelView

PLATFORMS = ["sensor", "climate", "number", "select"]

async def _cleanup_orphaned_devices(hass: HomeAssistant):
    """Remove legacy per-block devices left from <0.2.3 (foxair_H, foxair_A, etc).
    Single device is (DOMAIN, "foxair"); everything (DOMAIN, "foxair_*") is orphan."""
    try:
        registry = dr.async_get(hass)
        for device in list(registry.devices.values()):
            for ident in list(device.identifiers):
                if ident[0] == DOMAIN and ident[1] != "foxair" and ident[1].startswith("foxair"):
                    registry.async_remove_device(device.id)
                    break
    except Exception:
        pass

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # register HTTP views (idempotent)
    try:
        hass.http.register_view(FoxAirCurveSvgView())
        hass.http.register_view(FoxAirCurvePanelView())
    except Exception:
        pass
    # auto sidebar panel (iframe) — no Lovelace edit required
    try:
        from homeassistant.components.frontend import async_register_built_in_panel
        # frontend is optional in some core installs
        if hasattr(hass, "components") and hasattr(hass.components, "frontend"):
            await async_register_built_in_panel(
                hass,
                component_name="iframe",
                sidebar_title="FoxAir Curve",
                sidebar_icon="mdi:chart-bell-curve",
                frontend_url_path="foxair_curve",
                config={"url": "/api/foxair/heating-curve-panel"},
                require_admin=False,
            )
    except Exception:
        pass
    coord = FoxAirCoordinator(hass, entry)
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault("foxair", {})[entry.entry_id] = coord
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hass.async_create_task(_cleanup_orphaned_devices(hass))
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data["foxair"].pop(entry.entry_id, None)
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if coord and getattr(coord, "client", None):
        try: coord.client.close()
        except: pass
    return True
