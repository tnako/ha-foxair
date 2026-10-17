"""Button platform — momentary trigger bits of bit_split words.

Spec in foxair_config.json -> metadata (format=bit_split, bits/mask):
each kind==button bit becomes a set-only trigger button. Writes are
read-modify-write so sibling bits survive.
"""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    bind_device_info,
    device_for_addr,
    device_for_block,
    get_device_prefix,
    get_slave_id,
    word_base,
    word_set,
    write_rejected,
)


async def async_setup_entry(hass, entry, add_entities):
    coord = entry.runtime_data
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents = []
    for addr_str, meta in (coord._metadata or {}).items():
        if meta.get("format") != "bit_split" or not meta.get("editable") or meta.get("hidden"):
            continue
        if meta.get("min_firmware") and not coord._fw_gte(meta.get("min_firmware")):
            continue
        try:
            addr = int(addr_str)
        except ValueError:
            continue
        for bit, spec in (meta.get("bits") or {}).items():
            if spec.get("kind") == "button":
                ents.append(FoxBitButton(coord, addr, meta, int(bit), spec.get("slug", f"bit{bit}"), spec.get("key", f"{addr}_{bit}"), spec.get("icon")))
    if getattr(coord, "efficiency", None) is not None:
        ents += [FoxEfficiencyApplyButton(coord), FoxEfficiencyUndoButton(coord)]
    add_entities(ents)


class FoxEfficiencyButton(CoordinatorEntity, ButtonEntity):
    """Button on the Efficiency sub-device; unavailable while busy."""
    _attr_has_entity_name = True
    _key = ""

    def __init__(self, coord):
        super().__init__(coord)
        prefix = get_device_prefix(coord.entry)
        entry_id = coord.entry.entry_id
        self._attr_unique_id = f"{prefix}_efficiency_{self._key}"
        self.entity_id = f"button.{prefix}_efficiency_{self._key}"
        self._attr_translation_key = f"foxair_efficiency_{self._key}"
        self._attr_device_info = bind_device_info(
            getattr(coord, "hass", None), entry_id,
            device_for_block("EFF", entry_id, None, prefix, get_slave_id(coord.entry)))
        self._busy = False

    def _ready(self) -> bool:
        return True

    @property
    def available(self) -> bool:
        return not self._busy and super().available and self._ready()

    async def _run(self) -> None:
        raise NotImplementedError

    async def async_press(self) -> None:
        from homeassistant.exceptions import HomeAssistantError
        if self._busy:
            return
        self._busy = True
        self.async_write_ha_state()
        try:
            await self._run()
        except ValueError as e:
            raise HomeAssistantError(str(e)) from e
        finally:
            self._busy = False
            self.coordinator.async_update_listeners()


class FoxEfficiencyApplyButton(FoxEfficiencyButton):
    """Do what the efficiency status suggests: write the one setting, or keep the current settings."""
    _key = "apply"

    def _ready(self) -> bool:
        import time
        eff = self.coordinator.efficiency
        return eff.analyser.status(time.time(), eff.tz())["apply"] is not None

    async def _run(self) -> None:
        await self.coordinator.efficiency.async_apply()


class FoxEfficiencyUndoButton(FoxEfficiencyButton):
    """Write back what EEF changed (E02) to its value before EEF and forget every test result."""
    _key = "undo"

    async def _run(self) -> None:
        await self.coordinator.efficiency.async_undo()


class FoxBitButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coord, addr, meta, bit, slug, key, icon=None):
        super().__init__(coord)
        self._addr = addr
        self._bit = bit
        prefix = get_device_prefix(coord.entry)
        self._attr_unique_id = f"{prefix}_{slug}"
        self.entity_id = f"button.{prefix}_{slug}"
        self._attr_translation_key = f"foxair_{key}"
        entry_id = getattr(coord, "_entry_id", None) or getattr(getattr(coord, "config_entry", None), "entry_id", None)
        slave_id = get_slave_id(coord.entry)
        host = coord.entry.data.get("host")
        port = coord.entry.data.get("port")
        self._attr_device_info = bind_device_info(getattr(coord, "hass", None), entry_id, device_for_addr(addr, meta.get("block") or "", entry_id, meta.get("tab") or meta.get("block") or "", prefix, slave_id, host, port))
        self._attr_icon = icon or "mdi:gesture-tap-button"

    def _base(self) -> int:
        rec = self.coordinator.data.get(self._addr) or {}
        raw = rec.get("raw")
        if raw is None:
            raw = rec.get("value")
        return word_base(raw)

    async def async_press(self) -> None:
        if not await self.coordinator.async_write_register(self._addr, word_set(self._base(), self._bit)):
            write_rejected(self)
