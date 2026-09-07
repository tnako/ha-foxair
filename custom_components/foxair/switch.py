"""Switch platform — single-bit On/Off registers (SWITCH dtype)."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    POPULAR_ADDRS,
    bind_device_info,
    device_for_addr,
    entity_sort_key,
    get_device_prefix,
    get_slave_id,
    word_base,
    word_clear,
    word_is_set,
    word_set,
)


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
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
            continue
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        ents.append(FoxSwitch(coord, addr, meta))
    # bit_split words (foxair_config.json): one switch per kind==switch bit
    # alias_switch (foxair_config.json): normal-mode switch backed by a plain
    # register (e.g. H22 silent enable) — exposed regardless of expert gate
    for addr_str, meta in (coord._metadata or {}).items():
        if meta.get("hidden"):
            continue
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
            continue
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        if meta.get("format") == "bit_split" and meta.get("editable"):
            for bit, spec in (meta.get("bits") or {}).items():
                if spec.get("kind") == "switch":
                    ents.append(FoxBitSwitch(coord, addr, meta, int(bit), spec.get("slug", f"bit{bit}"), spec.get("key", f"{addr}_{bit}"), spec.get("icon")))
        alias = meta.get("alias_switch")
        if alias and meta.get("editable"):
            ents.append(FoxAliasSwitch(coord, addr, meta, alias))
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
        self._attr_suggested_object_id = f"{prefix}_switch_{addr}"
        self._attr_translation_key = f"foxair_{addr}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(getattr(coord, "config_entry", None), "entry_id", None)
        slave_id = get_slave_id(coord.entry)
        host = coord.entry.data.get("host")
        port = coord.entry.data.get("port")
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, device_for_addr(addr, meta.get("block") or "", entry_id, meta.get("tab") or meta.get("block") or "", prefix, slave_id, host, port))
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
        """Dynamic availability: expert gating + registry depends_on."""
        if self._meta.get("requires_expert") and not self.coordinator.entry.options.get("enable_expert"):
            return False
        dep = self._meta.get("depends_on")
        if dep is not None:
            try:
                rec = self.coordinator.data.get(int(dep))
                if not rec:
                    return False
                raw = rec.get("raw")
                if raw is None:
                    raw = rec.get("value")
                if raw is None:
                    return False
                s = str(raw).strip().lower()
                if s in ("0", "0.0", "off", "no", "false", ""):
                    return False
                try:
                    if float(raw) == 0:
                        return False
                except Exception:
                    pass
            except Exception:
                pass
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
        await self.coordinator.async_write_register(self._addr, 1)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_write_register(self._addr, 0)

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


class FoxBitSwitch(CoordinatorEntity, SwitchEntity):
    """One persistent bit of a bit_split word as a real switch.

    Read-modify-write so sibling bits are preserved.
    """

    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta, bit, slug, key, icon=None):
        super().__init__(coord)
        self._addr = addr
        self._bit = bit
        self._optimistic = None
        self._optimistic_base = None
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_{slug}"
        self._attr_suggested_object_id = f"{prefix}_{slug}"
        self._attr_translation_key = f"foxair_{key}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(getattr(coord, "config_entry", None), "entry_id", None)
        slave_id = get_slave_id(coord.entry)
        host = coord.entry.data.get("host")
        port = coord.entry.data.get("port")
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, device_for_addr(addr, meta.get("block") or "", entry_id, meta.get("tab") or meta.get("block") or "", prefix, slave_id, host, port))
        self._attr_icon = icon or "mdi:toggle-switch"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS

    def _base(self) -> int:
        rec = self.coordinator.data.get(self._addr) or {}
        raw = rec.get("raw")
        if raw is None:
            raw = rec.get("value")
        return word_base(raw)

    @property
    def is_on(self):
        if self._addr not in (self.coordinator.data or {}):
            return None
        base = self._base()
        if self._optimistic is not None:
            if base != self._optimistic_base:
                self._optimistic = None  # poll caught up with the write
            else:
                return self._optimistic
        return word_is_set(base, self._bit)

    async def async_turn_on(self, **kwargs):
        base = self._base()
        if await self.coordinator.async_write_register(self._addr, word_set(base, self._bit)):
            self._optimistic, self._optimistic_base = True, base
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        base = self._base()
        if await self.coordinator.async_write_register(self._addr, word_clear(base, self._bit)):
            self._optimistic, self._optimistic_base = False, base
            self.async_write_ha_state()


class FoxAliasSwitch(CoordinatorEntity, SwitchEntity):
    """Normal-mode switch backed by a plain register (alias_switch in JSON).

    Reads addr (on when raw == on_value), writes on/off values. Exposed
    regardless of the expert gate — that is its purpose (e.g. H22 silent
    enable lives in expert block H but is user-facing).
    """

    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta, alias):
        super().__init__(coord)
        self._addr = addr
        self._on = alias["on"]
        self._off = alias["off"]
        self._optimistic = None
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_{alias['key']}"
        self._attr_suggested_object_id = f"{prefix}_{alias['key']}"
        self._attr_translation_key = f"foxair_{alias['key']}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(getattr(coord, "config_entry", None), "entry_id", None)
        slave_id = get_slave_id(coord.entry)
        host = coord.entry.data.get("host")
        port = coord.entry.data.get("port")
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, device_for_addr(addr, meta.get("block") or "", entry_id, meta.get("tab") or meta.get("block") or "", prefix, slave_id, host, port))
        self._attr_icon = alias.get("icon") or "mdi:toggle-switch"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS

    def _raw(self):
        rec = self.coordinator.data.get(self._addr) or {}
        raw = rec.get("raw")
        if raw is None:
            raw = rec.get("value")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @property
    def is_on(self):
        if self._addr not in (self.coordinator.data or {}):
            return None
        if self._optimistic is not None:
            if self._raw() != (self._on if self._optimistic else self._off):
                return self._optimistic
            self._optimistic = None
        raw = self._raw()
        return None if raw is None else raw == self._on

    async def async_turn_on(self, **kwargs):
        if await self.coordinator.async_write_register(self._addr, self._on):
            self._optimistic = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        if await self.coordinator.async_write_register(self._addr, self._off):
            self._optimistic = False
            self.async_write_ha_state()