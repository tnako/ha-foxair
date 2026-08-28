from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)

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
    except Exception as e:
        _LOGGER.debug("cleanup orphaned devices failed: %s", e)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    try:
        from .views import FoxAirCurveSvgView, FoxAirCurvePanelView

        hass.http.register_view(FoxAirCurveSvgView())
        hass.http.register_view(FoxAirCurvePanelView())
    except Exception as e:
        _LOGGER.debug("FoxAir views already registered: %s", e)
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
    except ImportError as e:
        _LOGGER.debug("frontend panel not available: %s", e)
    except Exception as e:
        _LOGGER.debug("panel registration failed: %s", e)
    from modbus_connection import ModbusTcpParams
    from modbus_connection.pymodbus import ModbusConnection
    from .coordinator import FoxAirCoordinator

    host = entry.data.get("host", "EW11-host")
    port = int(entry.data.get("port", 8899))
    slave = int(entry.data.get("slave", 1))
    conn = ModbusConnection(ModbusTcpParams(host=host, port=port), timeout=8, message_spacing=0.22)
    unit = conn.for_unit(slave)
    coord = FoxAirCoordinator(hass, entry, unit, conn)
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault("foxair", {})[entry.entry_id] = coord
    hass.data.setdefault("foxair_conn", {})[entry.entry_id] = conn
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hass.async_create_task(_cleanup_orphaned_devices(hass))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    conn = hass.data.get("foxair_conn", {}).pop(entry.entry_id, None)
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get("foxair", {}).pop(entry.entry_id, None)
    if conn is not None:
        try:
            await conn.close()
        except Exception as e:
            _LOGGER.debug("conn close failed: %s", e)
    elif coord and getattr(coord, "_conn", None):
        try:
            await coord._conn.close()
        except Exception as e:
            _LOGGER.debug("coord conn close failed: %s", e)
    elif coord and getattr(coord, "unit", None):
        try:
            await coord.unit.disconnect()
        except Exception as e:
            _LOGGER.debug("unit disconnect failed: %s", e)
    return ok
