"""Time platform — timer registers as HH:MM pickers.

- TIME_HHMM   : one register, High byte=hour Low byte=minute  (KG 1256+, ASM 1281+)
- TIME_DECIMAL: one register, decimal HHMM e.g. 730=07:30      (circ pump 1326-1331)
- TIME_SPLIT  : two registers: this addr=hour, addr+1=minute   (silent 1245/1248)
"""

import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import POPULAR_ADDRS, device_for_addr, entity_sort_key, get_device_prefix

_LOGGER = logging.getLogger(__name__)

# Silent-mode composites: primary hour addr -> slave minute addr
SPLIT_PAIRS = {1245: 1246, 1248: 1249}


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
        # hide minute slaves — they are written via the composite entity
        if addr in (1246, 1249):
            continue
        if meta.get("platform") != "time" or not meta.get("editable"):
            continue
        if meta.get("hidden"):
            continue
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
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
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_time_{addr}"
        self._attr_translation_key = f"{prefix}_{addr}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(coord.config_entry, "entry_id", None)
        block = meta.get("block") or ""
        tab = meta.get("tab") or block
        self._attr_device_info = device_for_addr(addr, block, entry_id, tab, prefix)
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
    def native_value(self):
        if self._optimistic is not None:
            return self._optimistic
        rec = self.coordinator.data.get(self._addr)
        if not rec or rec.get("raw") is None:
            return None
        dtype = (self._meta.get("type") or "").upper()
        raw = int(rec["raw"])
        if dtype == "TIME_SPLIT":
            minute_addr = SPLIT_PAIRS.get(self._addr)
            rec2 = self.coordinator.data.get(minute_addr) if minute_addr else None
            minute = int(rec2["raw"]) if rec2 and rec2.get("raw") is not None else None
            return _split_to_time(raw, minute)
        if dtype == "TIME_DECIMAL":
            return _decimal_to_time(raw)
        return _raw_to_time(raw)

    async def async_set_value(self, value: time) -> None:
        self._optimistic = value
        self._attr_assumed_state = True
        self.async_write_ha_state()
        dtype = (self._meta.get("type") or "").upper()
        try:
            if dtype == "TIME_SPLIT":
                minute_addr = SPLIT_PAIRS.get(self._addr)
                if not minute_addr:
                    raise ValueError("No minute slave for split time")
                ok1 = await self.coordinator.async_write_register(self._addr, float(value.hour))
                ok2 = await self.coordinator.async_write_register(minute_addr, float(value.minute))
                ok = ok1 and ok2
            elif dtype == "TIME_DECIMAL":
                raw = _time_to_decimal(value)
                ok = await self.coordinator.async_write_register(self._addr, float(raw))
            else:
                raw = _time_to_raw(value)
                ok = await self.coordinator.async_write_register(self._addr, float(raw))
        except Exception as e:
            _LOGGER.error("time write %s failed: %s", self._addr, e)
            ok = False
        if not ok:
            self._optimistic = None
            self._attr_assumed_state = False
            self.async_write_ha_state()
            raise ValueError(f"Write rejected {self._addr}")
        self._optimistic = None
        self.async_write_ha_state()


def _raw_to_time(raw: int) -> time | None:
    raw = int(raw) & 0xFFFF
    h = (raw >> 8) & 0xFF
    m = raw & 0xFF
    if 0 <= h <= 23 and 0 <= m <= 59:
        return time(h, m)
    _LOGGER.warning("TIME_HHMM raw %s out of HH:MM range", raw)
    return None


def _time_to_raw(value: time) -> int:
    return ((value.hour & 0xFF) << 8) | (value.minute & 0xFF)


def _decimal_to_time(raw: int) -> time | None:
    raw = int(raw) & 0xFFFF
    # signed
    if raw & 0x8000:
        raw -= 0x10000
    if raw < 0 or raw > 2359:
        return None
    h = raw // 100
    m = raw % 100
    if 0 <= h <= 23 and 0 <= m <= 59:
        return time(h, m)
    _LOGGER.warning("TIME_DECIMAL raw %s out of HH:MM range", raw)
    return None


def _time_to_decimal(value: time) -> int:
    return value.hour * 100 + value.minute


def _split_to_time(hour_raw: int, minute_raw: int | None) -> time | None:
    if minute_raw is None:
        return None
    h = int(hour_raw) & 0xFFFF
    m = int(minute_raw) & 0xFFFF
    if h & 0x8000:
        h -= 0x10000
    if m & 0x8000:
        m -= 0x10000
    if 0 <= h <= 23 and 0 <= m <= 59:
        return time(h, m)
    return None
