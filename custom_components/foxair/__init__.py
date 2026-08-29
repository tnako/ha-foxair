from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_registry import async_get as er_async_get
from .const import DOMAIN, EXPERT_BLOCKS
import logging

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "climate", "number", "select", "image"]


async def _cleanup_orphaned_entities(hass: HomeAssistant, entry: ConfigEntry, enable_expert: bool):
    """Remove entity-registry entries for entities that should no longer exist.

    When expert mode is disabled, entities from expert-only blocks and
    dangerous-risk addresses are not re-created by platforms. Without cleanup,
    they linger in the entity registry as stale/unavailable entries.
    """
    if enable_expert:
        return  # no cleanup needed when expert mode is on
    try:
        registry = er_async_get(hass)
        coord = hass.data.get("foxair", {}).get(entry.entry_id)
        metadata = getattr(coord, "_metadata", {}) or {}
        removed = 0
        for ent in list(registry.entities.values()):
            if ent.config_entry_id != entry.entry_id:
                continue
            # FoxAir entity_ids end with the register address: foxair_<addr>, foxair_num_<addr>, etc.
            # Unique IDs follow the same pattern: foxair_<addr>, foxair_num_<addr>.
            uid = ent.unique_id
            addr = None
            for prefix in ("foxair_", "foxair_num_", "foxair_sel_"):
                if uid.startswith(prefix):
                    rest = uid[len(prefix):]
                    if rest.isdigit():
                        addr = int(rest)
                        break
            if addr is None:
                continue
            meta = metadata.get(str(addr), {})
            block = meta.get("block", "")
            requires_expert = meta.get("requires_expert", False)
            if requires_expert or block in EXPERT_BLOCKS:
                registry.async_remove(ent.entity_id)
                removed += 1
        if removed:
            _LOGGER.debug("Cleanup removed %d stale expert-mode entities", removed)
    except Exception as e:
        _LOGGER.debug("cleanup orphaned entities failed: %s", e)


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
    from .coordinator import FoxAirCoordinator

    coord = FoxAirCoordinator(hass, entry)
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault("foxair", {})[entry.entry_id] = coord
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    enable_expert = bool(entry.options.get("enable_expert"))
    if not enable_expert:
        await _cleanup_orphaned_entities(hass, entry, enable_expert)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hass.async_create_task(_cleanup_orphaned_devices(hass))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Cleanup happens in async_setup_entry after the first refresh loads metadata.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get("foxair", {}).pop(entry.entry_id, None)
    if coord and getattr(coord, "client", None):
        try:
            coord.client.close()
        except Exception as e:
            _LOGGER.debug("client close failed: %s", e)
    return ok


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
