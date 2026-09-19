from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import async_entries_for_config_entry as dr_entries_for_entry
from homeassistant.helpers.entity_registry import async_get as er_async_get
from homeassistant.helpers.entity_registry import async_entries_for_config_entry as er_entries_for_entry
from homeassistant.util import slugify
from .const import DOMAIN, EXPERT_BLOCKS, POPULAR_ADDRS, slug_code
import logging
import re

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "climate", "number", "select", "switch", "time", "image", "button", "binary_sensor"]

# Retired unique_id suffixes: entities removed/renamed by design (not
# hidden/expert), whose registry entries must be cleaned so they don't
# linger as unavailable.
# 2026-09: code-based entity naming (no _num_/_switch_/_sel_/_time_/_bin_
# intermediates): old addr-based patterns cleaned by the new regex below.
RETIRED_UID_SUFFIXES = (
    "_sel_1016", "_switch_1016", "_switch_1016_silent",
    "_btn_1016_defrost", "_btn_1016_boost", "_silent_status", "_silent_mode",
    # addr-based patterns being replaced by code-based naming
    "_num_", "_switch_", "_sel_", "_time_", "_bin_",
)


async def _cleanup_orphaned_entities(hass: HomeAssistant, entry: ConfigEntry, enable_expert: bool):
    """Remove entity-registry entries for entities that should no longer exist.

    Two classes of stale entities:
    - hidden addrs (reserved/block-header/system/wifi/factory-test): removed ALWAYS.
    - expert-gated addrs: removed when expert mode is disabled; without cleanup
      they linger in the entity registry as stale/unavailable entries.
    - renamed prefix: after a reconfigure prefix change, old-prefix unique_ids
      no longer match any entity and would linger as unavailable duplicates.
    """
    try:
        registry = er_async_get(hass)
        coord = hass.data.get("foxair", {}).get(entry.entry_id)
        metadata = getattr(coord, "_metadata", {}) or {}
        prefix = entry.data.get("name_prefix", "foxair") or "foxair"
        removed = 0
        reenabled = 0
        renamed = 0
        # Reverse map: slugified code -> addr (mirrors const.entity_suffix).
        code_to_addr = {}
        for a_str, a_meta in (metadata or {}).items():
            c = a_meta.get("code")
            if c:
                code_to_addr.setdefault(slug_code(c), int(a_str))
        for ent in er_entries_for_entry(registry, entry.entry_id):
            uid = ent.unique_id or ""
            if not uid.startswith(f"{prefix}_"):
                registry.async_remove(ent.entity_id)
                removed += 1
                continue
            # Legacy entities with midfixes (_num_, _switch_, _sel_, _time_,
            # _bin_) or specific retired suffixes are removed unconditionally.
            if uid.endswith(RETIRED_UID_SUFFIXES) or re.search(
                r"_num_|_switch_|_sel_|_time_|_bin_", uid
            ):
                registry.async_remove(ent.entity_id)
                removed += 1
                continue
            # FoxAir unique_ids: code-based (foxair_<code or addr>) or
            # legacy addr-based (foxair_num_<addr>, foxair_switch_<addr>,
            # foxair_sel_<addr>, foxair_time_<addr>, foxair_bin_<addr>_<bit>).
            # Extract addr so we can look up metadata for hidden/expert/fw checks.
            uid = ent.unique_id
            addr = None
            m = re.match(r"^.+?_bin_(\d+)_\d+$", uid or "")
            if m:
                addr = int(m.group(1))
            else:
                # Legacy midfix patterns: foxair_<midfix>_<addr>
                m = re.match(r"^.+?_(?:num_|switch_|sel_|time_)?(\d+)$", uid or "")
                if m:
                    addr = int(m.group(1))
                else:
                    # Code-based: foxair_<suffix> — suffix is code or addr
                    # Strip _bit<n> for bitfield binary sensors
                    m2 = re.match(r"^.+?_(.*?)(?:_bit\d+)?$", uid or "")
                    if m2:
                        suffix = m2.group(1)
                        if suffix.isdigit():
                            addr = int(suffix)
                        else:
                            # Reverse lookup: slugified code -> addr
                            addr = code_to_addr.get(suffix)
            if addr is None:
                continue
            meta = metadata.get(str(addr), {})
            # Legacy plain-addr uid (foxair_<addr>) on a register that now has
            # a code-based uid (foxair_<code>): drop it, platform setup
            # recreates the entity under the code-based identity. Registers
            # without a code keep the numeric uid — that is the current scheme.
            if uid == f"{prefix}_{addr}" and meta.get("code"):
                registry.async_remove(ent.entity_id)
                removed += 1
                continue
            # Newly popular/ungated addrs (H22, H32): rows created by older
            # releases stay integration-disabled forever — re-enable them.
            # Never touches user-disabled rows.
            if addr in POPULAR_ADDRS and str(ent.disabled_by) in ("integration", "DisabledBy.INTEGRATION"):
                registry.async_update_entity(ent.entity_id, disabled_by=None)
                reenabled += 1
            # Expanded BITFIELDs live as per-bit binary_sensors now — drop
            # retired raw-decimal sensor entities (generic: any bit_map addr).
            _rm = (getattr(coord, "_regmap", None) or {}).get(str(addr), {})
            if (meta.get("type") or "").upper() == "BITFIELD" and _rm.get("bit_map"):
                if uid.endswith(f"_{addr}") and "_bin_" not in (uid or ""):
                    registry.async_remove(ent.entity_id)
                    removed += 1
                    continue
            block = meta.get("block", "")
            requires_expert = meta.get("requires_expert", False)
            min_fw = meta.get("min_firmware")
            drop = meta.get("hidden", False) or (
                not enable_expert and (requires_expert or block in EXPERT_BLOCKS)
            )
            if min_fw and not coord._fw_gte(min_fw):
                drop = True
            if drop:
                registry.async_remove(ent.entity_id)
                removed += 1
        # Object-id normalization: registry entries created by pre-code-naming
        # builds (has_entity_name=True) carry the device slug + IP inside the
        # entity_id (e.g. sensor.foxair_live_t_live_172_16_79_26_t02_...).
        # suggested_object_id only applies at FIRST registration, so those ids
        # never self-heal — force entity_id back to the current scheme
        # (object_id == slugify(unique_id)) for every surviving entry.
        for ent in er_entries_for_entry(registry, entry.entry_id):
            uid = ent.unique_id or ""
            if not uid.startswith(f"{prefix}_"):
                continue
            expected = slugify(uid)
            # HA 2026.x RegistryEntry has no .object_id attr — derive it
            current = ent.entity_id.split(".", 1)[1]
            if current == expected:
                continue
            new_entity_id = f"{ent.domain}.{expected}"
            if registry.async_get(new_entity_id) is not None:
                registry.async_remove(ent.entity_id)
                removed += 1
            else:
                registry.async_update_entity(ent.entity_id, new_entity_id=new_entity_id)
                renamed += 1
        if removed or reenabled or renamed:
            _LOGGER.debug("Cleanup removed %d stale entities, re-enabled %d, renamed %d entity_ids", removed, reenabled, renamed)
    except Exception:
        _LOGGER.exception("cleanup orphaned entities failed")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # ── Ensure main device exists BEFORE any sub-device ──────────
    # HA 2025.12+ warns (and will error) when a device's parent link
    # references a non-existing device. Sub-devices (T_Live, SG etc.) link
    # to the main device via const.bind_device_info (-> via_device_id).
    # If entities for sub-devices set up first, the warning fires. Create
    # main device synchronously here so it always exists first.
    try:
        from .const import main_device
        dev_reg = dr.async_get(hass)
        host = entry.data.get("host")
        port = entry.data.get("port")
        slave_id = entry.data.get("slave")
        prefix = entry.data.get("name_prefix", "foxair")
        dev_info = main_device(entry.entry_id, prefix, slave_id, host, port)
        dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers=dev_info["identifiers"],
            name=dev_info["name"],
            manufacturer=dev_info["manufacturer"],
            model=dev_info["model"],
        )
    except Exception as e:  # pragma: no cover
        _LOGGER.debug("main device pre-create failed: %s", e)
    try:
        from .views import FoxAirCurveSvgView, FoxAirCurvePanelView

        hass.http.register_view(FoxAirCurveSvgView())
        hass.http.register_view(FoxAirCurvePanelView())
    except Exception as e:
        _LOGGER.debug("FoxAir views already registered: %s", e)
    # NOTE: iframe panel is NOT auto-registered because multiple pumps need
    # different entry_id query params. Users can add their own iframe panels:
    # Settings -> Dashboards -> Add panel -> iframe ->
    #   URL: /api/foxair/heating-curve-panel?entry_id=<ENTRY_ID>
    #   Title: FoxAir Curve (House1)
    #   Icon: mdi:chart-bell-curve
    from .coordinator import FoxAirCoordinator

    coord = FoxAirCoordinator(hass, entry)
    await coord._load_config()  # load foxair_config.json off the event loop
    await coord._load_map()     # load regmap + metadata off the event loop
    await coord.async_config_entry_first_refresh()
    hass.data.setdefault("foxair", {})[entry.entry_id] = coord
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    enable_expert = bool(entry.options.get("enable_expert"))
    await _cleanup_orphaned_entities(hass, entry, enable_expert)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hass.async_create_task(_cleanup_orphaned_devices(hass, entry))
    # Expert toggle (or any config change) can make a whole tier of entities
    # appear with Unknown until the next medium/rare cycle (60-90s). Trigger
    # the same force-fetch burst used on first install so they populate in
    # a few seconds. No-op when nothing is missing.
    if enable_expert:
        try:
            burst = getattr(coord, "_burst_task", None)
            if burst and not burst.done():
                # Startup burst already pending with 1.5s delay — for a
                # config change we want the faster 0.5s path; cancel and
                # reschedule so expert entities don't sit at Unknown.
                try:
                    burst.cancel()
                except Exception:
                    pass
            coord._burst_task = hass.async_create_task(coord.async_burst_missing(delay=0.5))
        except Exception as e:
            _LOGGER.debug("post-setup burst schedule failed: %s", e)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Cleanup happens in async_setup_entry after the first refresh loads metadata.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if coord and getattr(coord, "_burst_task", None):
        try:
            coord._burst_task.cancel()
        except Exception:
            pass
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get("foxair", {}).pop(entry.entry_id, None)
    if coord and getattr(coord, "client", None):
        try:
            coord.client.close()
        except Exception as e:
            _LOGGER.debug("client close failed: %s", e)
    return ok


async def _cleanup_orphaned_devices(hass: HomeAssistant, entry: ConfigEntry):
    """Remove legacy devices of this entry (pre multi-pump identifiers).

    Scoped to the entry via async_entries_for_config_entry — no registry
    mapping access (deprecated, removal 2027.9).
    """
    try:
        registry = dr.async_get(hass)
        for device in dr_entries_for_entry(registry, entry.entry_id):
            for ident in list(device.identifiers):
                if ident[0] == DOMAIN and ident[1] == "foxair":
                    registry.async_remove_device(device.id)
                    break
                if ident[0] == DOMAIN and ident[1].startswith("foxair_") and "_" not in ident[1][7:]:
                    registry.async_remove_device(device.id)
                    break
    except Exception as e:
        _LOGGER.debug("cleanup orphaned devices failed: %s", e)
