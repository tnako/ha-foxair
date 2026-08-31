"""Time platform for v0.4 — TIME_HHMM timer start/stop registers.

These are 16-bit registers where the high byte is hours (0-23) and the low
byte is minutes (0-59), per the FoxAir/Phnix Modbus protocol. The 'time'
platform gives users a proper HH:MM time picker UI in Lovelace instead of
a boolean/select or raw integer.
"""
import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE, POPULAR_ADDRS, device_for_addr, entity_sort_key

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    for addr_str, meta in sorted(
        (coord._metadata or {}).items(),
        key=lambda kv: entity_sort_key(
            int(kv[0]) if kv[0].isdigit() else 99999,
            kv[1].get("code", ""),
            kv[1].get("block", ""),
        ),
    ):
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        if meta.get("platform") != "time" or not meta.get("editable"):
            continue
        if meta.get("hidden"):
            continue
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        ents.append(FoxTime(coord, addr, meta))
    add_entities(ents)


class FoxTime(CoordinatorEntity, TimeEntity):
    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta):
        super().__init__(coord)
        self._addr = addr
        self._meta = meta
        self._optimistic = None
        self._attr_unique_id = f"foxair_time_{addr}"
        self._attr_translation_key = f"foxair_{addr}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord, "config_entry", None) and getattr(coord.config_entry, "entry_id", None)
        block = meta.get("block") or ""
        tab = meta.get("tab") or block
        self._attr_device_info = device_for_addr(addr, block, entry_id, tab)
        self._attr_icon = meta.get("icon") or "mdi:timer-outline"
        risk = meta.get("risk")
        code = meta.get("code", "")
        if risk == "dangerous":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False
        elif risk == "advanced":
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_entity_registry_enabled_default = addr in POPULAR_ADDRS
        else:
            # safe: visible if has a tab code (user-facing control like KG timers)
            # or in popular addrs; otherwise diagnostic
            if code or addr in POPULAR_ADDRS:
                self._attr_entity_category = None
                self._attr_entity_registry_enabled_default = True
            else:
                self._attr_entity_category = EntityCategory.DIAGNOSTIC
                self._attr_entity_registry_enabled_default = False

    @property
    def available(self):
        if self._meta.get("requires_expert") and not self.coordinator.entry.options.get("enable_expert"):
            return False
        return super().available

    @property
    def native_value(self):
        if self._optimistic is not None:
            return self._optimistic
        rec = self.coordinator.data.get(self._addr)
        if not rec:
            return None
        raw = rec.get("raw")
        if raw is None:
            return None
        return _raw_to_time(raw)

    async def async_set_value(self, value: time) -> None:
        self._optimistic = value
        self._attr_assumed_state = True
        self.async_write_ha_state()
        raw = _time_to_raw(value)
        ok = await self.coordinator.async_write_register(self._addr, float(raw))
        if not ok:
            self._optimistic = None
            self._attr_assumed_state = False
            self.async_write_ha_state()
            raise ValueError(f"Write rejected {self._addr}")
        self._optimistic = None
        self.async_write_ha_state()


def _raw_to_time(raw: int) -> time | None:
    """Convert a TIME_HHMM raw register value to a datetime.time.

    High byte = hours (0-23), low byte = minutes (0-59).
    """
    raw = int(raw) & 0xFFFF
    h = (raw >> 8) & 0xFF
    m = raw & 0xFF
    if 0 <= h <= 23 and 0 <= m <= 59:
        return time(h, m)
    _LOGGER.warning("TIME_HHMM raw %s out of HH:MM range", raw)
    return None


def _time_to_raw(value: time) -> int:
    """Convert a datetime.time to a TIME_HHMM raw register value."""
    return ((value.hour & 0xFF) << 8) | (value.minute & 0xFF)
