"""Binary-sensor platform — BITFIELD expansion.

Any read-only register with a bit_map in foxair_phnix_registers.json is
split into one binary_sensor per documented bit (spare/unknown bits are
skipped). Replaces meaningless raw-decimal sensors (S01 switch states,
O load outputs, ERR fault words). Generic: future bitfields are picked
up with zero code changes (names come from translations).
"""

import json
import pathlib

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    bind_device_info,
    bitfield_expanded_bits,
    device_for_block,
    bitfield_is_set,
    bitfield_word,
    device_for_addr,
    entity_sort_key,
    get_device_prefix,
    get_slave_id,
    entity_suffix,
)

# Per-register presentation: device class + fallback icon.
_GROUP = {
    "ERR": (None, "mdi:alert"),
    "S": (None, "mdi:electric-switch"),
    "": (None, "mdi:toggle-switch"),
}


def _fault_names():
    """English per-bit names (entity.binary_sensor) so the summary attribute is readable beyond German."""
    try:
        data = json.loads((pathlib.Path(__file__).parent / "translations/en.json").read_text(encoding="utf-8"))
        return {k: v.get("name") for k, v in data["entity"]["binary_sensor"].items() if isinstance(v, dict)}
    except (OSError, ValueError, KeyError):
        return {}


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
    coord = entry.runtime_data
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
    faults = [(addr, meta, bits) for addr, meta, bits in _expanded_addrs(coord) if (meta.get("tab") or meta.get("block")) == "ERR" and not meta.get("requires_expert")]
    if faults:
        names = await hass.async_add_executor_job(_fault_names)
        ents.append(FoxFaultSummarySensor(coord, faults, names))
    add_entities(ents)


class FoxBitSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta, bit, device_class, icon):
        super().__init__(coord)
        self._addr = addr
        self._bit = bit
        prefix = get_device_prefix(coord.entry)
        suffix = entity_suffix(coord, addr)
        self._attr_unique_id = f"{prefix}_{suffix}_bit{bit}"
        self.entity_id = f"binary_sensor.{prefix}_{suffix}_bit{bit}"
        self._attr_translation_key = f"foxair_{suffix}_bit{bit}"
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
        self.entity_id = f"binary_sensor.{prefix}_{slug}"
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


class FoxFaultSummarySensor(CoordinatorEntity, BinarySensorEntity):
    """On while any documented fault bit is set; active_faults lists them by code and bit."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert"
    _attr_translation_key = "foxair_fault"

    def __init__(self, coord, faults, names=None):
        super().__init__(coord)
        names = names or {}
        self._faults = []
        for addr, meta, bits in faults:
            code = meta.get("code") or str(addr)
            key = entity_suffix(coord, addr)
            self._faults.append((addr, code, [(bit, names.get(f"foxair_{key}_bit{bit}") or f"{code} {label}") for bit, label in bits]))
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_fault"
        self.entity_id = f"binary_sensor.{prefix}_fault"
        entry_id = getattr(coord, "_entry_id", None) or getattr(getattr(coord, "config_entry", None), "entry_id", None)
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, device_for_block("ERR", entry_id, "ERR", prefix, get_slave_id(coord.entry), coord.entry.data.get("host"), coord.entry.data.get("port")))

    def _active(self):
        data = self.coordinator.data or {}
        out = []
        for addr, code, bits in self._faults:
            rec = data.get(addr) or {}
            word = bitfield_word(rec.get("raw") if rec.get("raw") is not None else rec.get("value"))
            out += [(code, bit, label) for bit, label in bits if bitfield_is_set(word, bit)]
        return out

    @property
    def available(self):
        data = self.coordinator.data or {}
        return any(addr in data for addr, _, _ in self._faults) and super().available

    @property
    def is_on(self):
        return bool(self._active())

    @property
    def extra_state_attributes(self):
        active = self._active()
        return {
            "active_faults": [label for _, _, label in active],
            "fault_keys": [f"{code.lower()}_bit{bit}" for code, bit, _ in active],
        }
