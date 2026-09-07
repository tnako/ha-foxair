#!/usr/bin/env python3
"""Offline tests for bit_split + alias_switch JSON formats (no HA installed).

bit_split words (foxair_config.json -> metadata format/bits/mask) expose
each bit as read-modify-write entities instead of a raw select: kind
switch -> FoxBitSwitch, button -> FoxBitButton, status -> read-only
binary_sensor. alias_switch exposes a plain register (e.g. H22 silent
enable) as a normal-mode switch. Everything here is driven by metadata —
no hardcoded addresses.

Run: pytest tests/test_bit_split.py -v
"""
import asyncio
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _stub_modules():
    ha = types.ModuleType("homeassistant")
    ha.helpers = types.ModuleType("homeassistant.helpers")
    ha.helpers.entity = types.ModuleType("homeassistant.helpers.entity")
    ha.helpers.update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    ha.components = types.ModuleType("homeassistant.components")
    ha.components.switch = types.ModuleType("homeassistant.components.switch")
    ha.components.button = types.ModuleType("homeassistant.components.button")
    ha.components.binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")

    class DeviceInfo(dict):
        def __init__(self, identifiers=None, name=None, manufacturer=None,
                     model=None, via_device=None):
            super().__init__(identifiers=identifiers, name=name,
                             manufacturer=manufacturer, model=model,
                             via_device=via_device)

    class EntityCategory:
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    class CoordinatorEntity:
        def __init__(self, coord):
            self.coordinator = coord

        @property
        def available(self):
            return True

        def async_write_ha_state(self):
            pass

    class SwitchEntity:
        pass

    class ButtonEntity:
        pass

    class BinarySensorDeviceClass:
        PROBLEM = "problem"

    class BinarySensorEntity:
        pass

    ha.helpers.entity.DeviceInfo = DeviceInfo
    ha.helpers.entity.EntityCategory = EntityCategory
    ha.helpers.update_coordinator.CoordinatorEntity = CoordinatorEntity
    ha.components.switch.SwitchEntity = SwitchEntity
    ha.components.button.ButtonEntity = ButtonEntity
    ha.components.binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    ha.components.binary_sensor.BinarySensorEntity = BinarySensorEntity
    for m in (ha, ha.helpers, ha.helpers.entity,
              ha.helpers.update_coordinator, ha.components,
              ha.components.switch, ha.components.button,
              ha.components.binary_sensor):
        sys.modules[m.__name__] = m


def _load_pkg():
    _stub_modules()
    pkg = types.ModuleType("foxpkgsplit")
    pkg.__path__ = []
    sys.modules["foxpkgsplit"] = pkg
    mods = {}
    for name in ("const", "switch", "button", "binary_sensor"):
        src = (CC / f"{name}.py").read_text().replace(
            "from .const import", "from foxpkgsplit.const import")
        mod = types.ModuleType(f"foxpkgsplit.{name}")
        mod.__dict__["__file__"] = str(CC / f"{name}.py")
        sys.modules[f"foxpkgsplit.{name}"] = mod
        exec(compile(src, str(CC / f"{name}.py"), "exec"), mod.__dict__)
        mods[name] = mod
    return mods


MODS = _load_pkg()
const = MODS["const"]
META = json.loads((CC / "data/foxair_metadata.json").read_text(encoding="utf-8-sig"))
SPLIT = {int(a): m for a, m in META.items() if a.isdigit() and m.get("format") == "bit_split"}
ALIAS = {int(a): (m, m["alias_switch"]) for a, m in META.items() if a.isdigit() and m.get("alias_switch")}
assert SPLIT, "no bit_split entries in metadata"
assert ALIAS, "no alias_switch entries in metadata"


class FakeEntry:
    def __init__(self):
        self.entry_id = "eid"
        self.data = {"name_prefix": "foxair", "host": "h", "port": 8899, "slave": 1}
        self.options = {}


class FakeCoord:
    def __init__(self, data=None):
        self.entry = FakeEntry()
        self._entry_id = "eid"
        self.data = data if data is not None else {}
        self._metadata = META
        self._regmap = json.loads((CC / "data/foxair_phnix_registers.json").read_text(encoding="utf-8-sig"))
        self.writes = []

    async def async_write_register(self, addr, value):
        self.writes.append((addr, value))
        return True

    def _fw_gte(self, v):
        return True


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _hass(coord):
    return types.SimpleNamespace(data={"foxair": {"eid": coord}})


def test_word_helpers():
    assert const.word_set(0b101, 1) == 0b111
    assert const.word_clear(0b111, 1) == 0b101
    assert const.word_is_set(0b101, 0) is True
    assert const.word_is_set(0b101, 1) is False
    assert const.word_base(None) == 0
    assert const.word_mask({"0": {}, "2": {}}) == 0b101


def test_bit_switch_rmw_and_optimistic():
    meta = {"block": "", "tab": ""}
    sw = MODS["switch"].FoxBitSwitch(FakeCoord({1016: {"raw": 5}}), 1016, meta, 1, "t", "t")
    assert sw.is_on is False
    c = FakeCoord({1016: {"raw": 5}})
    sw = MODS["switch"].FoxBitSwitch(c, 1016, meta, 1, "t", "t")
    _run(sw.async_turn_on())  # 5 -> 7: only the bit added, instant UI
    assert c.writes == [(1016, 7)]
    assert sw.is_on is True
    c.data[1016]["raw"] = 7  # poll catches up
    assert sw.is_on is True and sw._optimistic is None
    _run(sw.async_turn_off())
    assert c.writes[-1] == (1016, 5)
    assert MODS["switch"].FoxBitSwitch(FakeCoord(), 1016, meta, 1, "t", "t").is_on is None


def test_button_bits_set_only_their_bit():
    for addr, meta in SPLIT.items():
        for bit, spec in meta["bits"].items():
            if spec["kind"] != "button":
                continue
            bit = int(bit)
            base = const.word_mask(meta["bits"]) & ~(1 << bit)
            c = FakeCoord({addr: {"raw": base}})
            _run(MODS["button"].FoxBitButton(c, addr, meta, bit, spec["slug"], spec["key"]).async_press())
            assert c.writes == [(addr, base | (1 << bit))]


def test_alias_switch_reads_writes_plain_register():
    for addr, (meta, alias) in ALIAS.items():
        sw_cls = MODS["switch"].FoxAliasSwitch
        assert sw_cls(FakeCoord({addr: {"raw": alias["on"]}}), addr, meta, alias).is_on is True
        assert sw_cls(FakeCoord({addr: {"raw": alias["off"]}}), addr, meta, alias).is_on is False
        assert sw_cls(FakeCoord(), addr, meta, alias).is_on is None
        sw = sw_cls(FakeCoord({addr: {"raw": alias["off"]}}), addr, meta, alias)
        assert sw._attr_translation_key == f"foxair_{alias['key']}"
        assert sw._attr_unique_id == f"foxair_{alias['key']}"
        c = FakeCoord({addr: {"raw": alias["off"]}})
        _run(sw_cls(c, addr, meta, alias).async_turn_on())
        assert c.writes == [(addr, alias["on"])]
        _run(sw_cls(c, addr, meta, alias).async_turn_off())
        assert c.writes[-1] == (addr, alias["off"])


def test_status_bits_become_readonly_binaries():
    coord = FakeCoord({1016: {"raw": 2}})
    added = []
    _run(MODS["binary_sensor"].async_setup_entry(_hass(coord), coord.entry, added.extend))
    status = [e for e in added if isinstance(e, MODS["binary_sensor"].FoxWordStatusSensor)]
    n_status = sum(1 for m in SPLIT.values() for s in m["bits"].values() if s["kind"] == "status")
    assert len(status) == n_status  # driven by spec; 1016 bit1 proven manual-override flag, not shown


def test_platforms_build_from_spec_and_skip_raw():
    coord = FakeCoord()
    added_sw, added_btn = [], []
    _run(MODS["switch"].async_setup_entry(_hass(coord), coord.entry, added_sw.extend))
    _run(MODS["button"].async_setup_entry(_hass(coord), coord.entry, added_btn.extend))
    for addr, meta in SPLIT.items():
        for spec in meta["bits"].values():
            key = f"foxair_{spec['key']}"
            if spec["kind"] == "switch":
                assert any(e._attr_translation_key == key for e in added_sw), key
            elif spec["kind"] == "button":
                assert any(e._attr_translation_key == key for e in added_btn), key
    for addr, (meta, alias) in ALIAS.items():
        key = f"foxair_{alias['key']}"
        assert any(e._attr_translation_key == key for e in added_sw), key
    src = (CC / "select.py").read_text()
    assert 'meta.get("format") == "bit_split"' in src  # raw select retired generically
    coord_src = (CC / "coordinator.py").read_text()
    assert 'meta.get("format") == "bit_split"' in coord_src  # 0..mask write gate


def test_split_keys_translated():
    for lang, path in (("strings", CC / "strings.json"),
                       ("en", CC / "translations/en.json"),
                       ("de", CC / "translations/de.json"),
                       ("ru", CC / "translations/ru.json")):
        d = json.loads(path.read_text(encoding="utf-8-sig"))
        names = {}
        for plat, items in d["entity"].items():
            for k, v in items.items():
                if isinstance(v, dict) and "name" in v:
                    names[k] = v["name"]
        for addr, meta in SPLIT.items():
            for spec in meta["bits"].values():
                assert names.get(f"foxair_{spec['key']}"), f"{lang}: bit key"
        for addr, (meta, alias) in ALIAS.items():
            assert names.get(f"foxair_{alias['key']}"), f"{lang}: alias key"
