"""Switch platform — single-bit On/Off registers (SWITCH dtype)."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import POPULAR_ADDRS, device_for_addr, entity_sort_key, get_device_prefix


async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    for addr_str, meta in sorted(
        (coord._metadata or {}).items(),
        key=lambda kv: entity_sort_key(int(kv[0]) if kv[0].isdigit() else 99999, kv[1].get("code", ""), kv[1].get("block", "")),
    ):
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        if meta.get("platform") != "switch" or not meta.get("editable"):
            continue
        if meta.get("hidden"):
            continue
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        ents.append(FoxSwitch(coord, addr, meta))
    add_entities(ents)


class FoxSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta):
        super().__init__(coord)
        self._addr = addr
        self._meta = meta
        self._optimistic = None
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_switch_{addr}"
        self._attr_translation_key = f"{prefix}_{addr}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(getattr(coord, "config_entry", None), "entry_id", None)
        self._attr_device_info = device_for_addr(addr, meta.get("block") or "", entry_id, meta.get("tab") or meta.get("block") or "", prefix)
        self._attr_icon = meta.get("icon") or "mdi:toggle-switch"
        risk = meta.get("risk")
        code = meta.get("code", "")
        if risk == "dangerous":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False
        elif risk == "advanced":
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
        else:
            if code or addr in POPULAR_ADDRS:
                self._attr_entity_category = None
                self._attr_entity_registry_enabled_default = True
            else:
                self._attr_entity_category = EntityCategory.DIAGNOSTIC
                self._attr_entity_registry_enabled_default = False

    @property
    def available(self):
        """Dynamic availability: hide expert entities when expert mode is off."""
        if self._meta.get("requires_expert") and not self.coordinator.entry.options.get("enable_expert"):
            return False
        return super().available

    @property
    def is_on(self):
        rec = self.coordinator.data.get(self._addr)
        if not rec:
            return None
        val = rec.get("value")
        if val is None:
            return None
        return bool(val)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_write_register(self._addr, 1, self._meta)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_write_register(self._addr, 0, self._meta)

    @property
    def extra_state_attributes(self):
        rec = self.coordinator.data.get(self._addr)
        if not rec:
            return {}
        info = rec.get("info", {})
        meta = {}
        try:
            meta = self.coordinator.get_metadata(self._addr)
        except Exception:
            pass
        return {"raw": rec.get("raw"), "address": self._addr, "block": info.get("block"), "code": info.get("code"), "type": info.get("type"), "group": meta.get("group"), "risk": meta.get("risk"), "editable": meta.get("editable"), "min": meta.get("min"), "max": meta.get("max")}