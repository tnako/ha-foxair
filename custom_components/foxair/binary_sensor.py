"""Binary-sensor platform — BITFIELD expansion.

Any read-only register with a bit_map in foxair_phnix_registers.json is
split into one binary_sensor per documented bit (spare/unknown bits are
skipped). Replaces meaningless raw-decimal sensors (S01 switch states,
O load outputs, ERR fault words). Generic: future bitfields are picked
up with zero code changes (names come from translations).
"""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    bind_device_info,
    bitfield_expanded_bits,
    bitfield_is_set,
    bitfield_word,
    device_for_addr,
    entity_sort_key,
    get_device_prefix,
    get_slave_id,
)

# Per-register presentation: device class + fallback icon.
_GROUP = {
    "ERR": (None, "mdi:alert"),
    "S": (None, "mdi:electric-switch"),
    "": (None, "mdi:toggle-switch"),
}


def _expanded_addrs(coord):
    """Yield (addr, meta, [(bit, label)]) for expandable registers."""
    regmap = getattr(coord, "_regmap", None) or {}
    for addr_str, meta in sorted(
        (coord._metadata or {}).items(),
        key=lambda kv: entity_sort_key(int(kv[0]) if kv[0].isdigit() else 99999, kv[1].get("code", ""), kv[1].get("block", "")),
    ):
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        if (meta.get("type") or "").upper() != "BITFIELD":
            continue
        if meta.get("hidden") or meta.get("editable"):
            continue
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
            continue
        bits = bitfield_expanded_bits((regmap.get(addr_str) or {}).get("bit_map"))
        if bits:
            yield addr, meta, bits


async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    expert = bool(entry.options.get("enable_expert"))
    ents = []
    for addr, meta, bits in _expanded_addrs(coord):
        if meta.get("requires_expert") and not expert:
            continue
        tab = meta.get("tab") or meta.get("block") or ""
        dclass, icon = _GROUP.get(tab, _GROUP[""])
        if tab == "ERR":
            dclass = BinarySensorDeviceClass.PROBLEM
        for bit, _label in bits:
            ents.append(FoxBitSensor(coord, addr, meta, bit, dclass, icon))
    # bit_split kind==status bits: read-only status from a R/W word
    for addr_str, meta in (coord._metadata or {}).items():
        if meta.get("format") != "bit_split" or meta.get("hidden"):
            continue
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
            continue
        if meta.get("requires_expert") and not expert:
            continue
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        for bit, spec in (meta.get("bits") or {}).items():
            if spec.get("kind") == "status":
                ents.append(FoxWordStatusSensor(coord, addr, meta, int(bit), spec.get("slug", f"bit{bit}"), spec.get("key", f"{addr}_{bit}"), spec.get("icon")))
    add_entities(ents)


class FoxBitSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta, bit, device_class, icon):
        super().__init__(coord)
        self._addr = addr
        self._bit = bit
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_bin_{addr}_{bit}"
        self._attr_suggested_object_id = f"{prefix}_bin_{addr}_{bit}"
        self._attr_translation_key = f"foxair_{addr}_bit{bit}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(getattr(coord, "config_entry", None), "entry_id", None)
        slave_id = get_slave_id(coord.entry)
        host = coord.entry.data.get("host")
        port = coord.entry.data.get("port")
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, device_for_addr(addr, meta.get("block") or "", entry_id, meta.get("tab") or meta.get("block") or "", prefix, slave_id, host, port))
        self._attr_device_class = device_class
        self._attr_icon = icon

    @property
    def available(self):
        if self.coordinator.data is not None and self._addr not in self.coordinator.data:
            return False
        return super().available

    @property
    def is_on(self):
        rec = (self.coordinator.data or {}).get(self._addr) or {}
        raw = rec.get("raw")
        if raw is None:
            raw = rec.get("value")
        return bitfield_is_set(bitfield_word(raw), self._bit)


class FoxWordStatusSensor(CoordinatorEntity, BinarySensorEntity):
    """Read-only status bit of a bit_split R/W word (e.g. silent active)."""

    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta, bit, slug, key, icon=None):
        super().__init__(coord)
        self._addr = addr
        self._bit = bit
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

    @property
    def available(self):
        if self.coordinator.data is not None and self._addr not in self.coordinator.data:
            return False
        return super().available

    @property
    def is_on(self):
        rec = (self.coordinator.data or {}).get(self._addr) or {}
        raw = rec.get("raw")
        if raw is None:
            raw = rec.get("value")
        return bitfield_is_set(bitfield_word(raw), self._bit)
