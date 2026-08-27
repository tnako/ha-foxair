from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from .coordinator import FoxAirCoordinator
from .const import DOMAIN
from .views import FoxAirCurveSvgView, FoxAirCurvePanelView

PLATFORMS = ["sensor", "climate", "number", "select", "image"]

async def _cleanup_orphaned_devices(hass: HomeAssistant):
    try:
        registry = dr.async_get(hass)
        for device in list(registry.devices.values()):
            for ident in list(device.identifiers):
                if ident[0] == DOMAIN and ident[1] == "foxair":
                    registry.async_remove_device(device.id)
                    break
                if ident[0] == DOMAIN and ident[1].startswith("foxair_") and "_" not in ident[1][7:]:
                    registry.async_remove_device(device.id)
                    break
    except Exception:
        pass

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    try:
        hass.http.register_view(FoxAirCurveSvgView())
        hass.http.register_view(FoxAirCurvePanelView())
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("FoxAir views already registered: %s", e)
    try:
        from homeassistant.components.frontend import async_register_built_in_panel
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
    # expose local brand assets explicitly so frontend can load them directly instead of relying on HACS resource copies or CDN
    try:
        from pathlib import Path
        brand_dir = Path(__file__).parent / "brand"
        if brand_dir.is_dir():
            hass.http.register_static_path("/foxair/brand", str(brand_dir), cache_headers=False)
    except Exception:
        pass
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get("foxair", {}).pop(entry.entry_id, None)
    if coord and getattr(coord, "client", None):
        try: coord.client.close()
        except: pass
    return ok
