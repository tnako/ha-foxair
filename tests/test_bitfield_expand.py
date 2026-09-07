#!/usr/bin/env python3
"""Offline tests for BITFIELD expansion into binary_sensors (no HA installed).

Raw-decimal sensors for bit-word registers (S01, O outputs, ERR faults)
are meaningless — binary_sensor.py expands every BITFIELD with a bit_map
into per-bit entities (reserved/unknown bits skipped).

Run: pytest tests/test_bitfield_expand.py -v
"""
import asyncio
import importlib.util
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
    ha.components.binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")

    class DeviceInfo(dict):
        def __init__(self, identifiers=None, name=None, manufacturer=None,
                     model=None, via_device=None):
            super().__init__(identifiers=identifiers, name=name,
                             manufacturer=manufacturer, model=model,
                             via_device=via_device)

    class BinarySensorDeviceClass:
        PROBLEM = "problem"

    class CoordinatorEntity:
        def __init__(self, coord):
            self.coordinator = coord

        @property
        def available(self):
            return True

    class BinarySensorEntity:
        pass

    ha.helpers.entity.DeviceInfo = DeviceInfo
    ha.components.binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    ha.components.binary_sensor.BinarySensorEntity = BinarySensorEntity
    ha.helpers.update_coordinator.CoordinatorEntity = CoordinatorEntity
    for m in (ha, ha.helpers, ha.helpers.entity,
              ha.helpers.update_coordinator, ha.components,
              ha.components.binary_sensor):
        sys.modules[m.__name__] = m


def _load_pkg():
    _stub_modules()
    pkg = types.ModuleType("foxpkgbits")
    pkg.__path__ = []
    sys.modules["foxpkgbits"] = pkg
    mods = {}
    for name in ("const", "binary_sensor"):
        src = (CC / f"{name}.py").read_text().replace(
            "from .const import", "from foxpkgbits.const import")
        mod = types.ModuleType(f"foxpkgbits.{name}")
        mod.__dict__["__file__"] = str(CC / f"{name}.py")
        sys.modules[f"foxpkgbits.{name}"] = mod
        exec(compile(src, str(CC / f"{name}.py"), "exec"), mod.__dict__)
        mods[name] = mod
    return mods


MODS = _load_pkg()
const = MODS["const"]
bs = MODS["binary_sensor"]

REGS = json.loads((CC / "data/foxair_phnix_registers.json").read_text(encoding="utf-8-sig"))
META = json.loads((CC / "data/foxair_metadata.json").read_text(encoding="utf-8-sig"))


class FakeEntry:
    def __init__(self, expert=False):
        self.entry_id = "eid"
        self.data = {"name_prefix": "foxair", "host": "h", "port": 8899, "slave": 1}
        self.options = {"enable_expert": expert}


class FakeCoord:
    def __init__(self, expert=False, data=None):
        self.entry = FakeEntry(expert)
        self._entry_id = "eid"
        self.data = data if data is not None else {}
        self._metadata = META
        self._regmap = REGS

    def _fw_gte(self, v):
        return True


def _setup(expert=False, data=None):
    coord = FakeCoord(expert, data)
    hass = types.SimpleNamespace(data={"foxair": {"eid": coord}})
    added = []
    asyncio.new_event_loop().run_until_complete(
        bs.async_setup_entry(hass, coord.entry, added.extend))
    return added


def test_word_and_decode():
    assert const.bitfield_word(15460) == 15460
    assert const.bitfield_word(None) is None
    assert const.bitfield_word("unknown") is None
    assert const.bitfield_is_set(0x3000, 12) is True
    assert const.bitfield_is_set(0x3000, 0) is False
    assert const.bitfield_is_set(None, 12) is None  # unknown, not off


def test_reserved_bits_skipped():
    bits_2034 = const.bitfield_expanded_bits(REGS["2034"]["bit_map"])
    assert [b for b, _ in bits_2034] == [0, 1, 2, 3, 4, 5, 6, 9, 12, 13]
    bits_2019 = const.bitfield_expanded_bits(REGS["2019"]["bit_map"])
    assert [b for b, _ in bits_2019] == [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


def test_expansion_counts_and_expert_gating():
    plain = _setup(expert=False)
    assert len(plain) == 80  # 95 total minus 15 expert-only O bits
    assert not any(e._addr == 2019 for e in plain)
    expert = _setup(expert=True)
    assert len(expert) == 95
    assert sum(1 for e in expert if e._addr == 2019) == 15


def test_identity_and_problem_class():
    ents = _setup(expert=True)
    by_key = {e._attr_translation_key: e for e in ents}
    e = by_key["foxair_2034_bit12"]
    assert e._attr_unique_id == "foxair_bin_2034_12"
    assert e._attr_device_class is None  # contacts, not faults
    assert by_key["foxair_2081_bit0"]._attr_device_class == "problem"
    assert by_key["foxair_2019_bit0"]._attr_device_class is None


def test_state_tracks_word_and_unknown():
    data = {2034: {"raw": 0x3000, "value": 0x3000}}  # SG1+SG2 set
    ents = _setup(expert=False, data=data)
    by_key = {e._attr_translation_key: e for e in ents}
    assert by_key["foxair_2034_bit12"].is_on is True
    assert by_key["foxair_2034_bit13"].is_on is True
    assert by_key["foxair_2034_bit0"].is_on is False
    assert by_key["foxair_2034_bit12"].available is True
    # never polled -> unknown, not off
    ents2 = _setup(expert=False, data={})
    assert ents2[0].is_on is None
    assert ents2[0].available is False


def test_every_bit_translated_with_icons():
    files = {"strings": CC / "strings.json", "en": CC / "translations/en.json",
             "de": CC / "translations/de.json", "ru": CC / "translations/ru.json"}
    icons = json.loads((CC / "icons.json").read_text())["entity"]["binary_sensor"]
    n = 0
    for e in _setup(expert=True):
        k = e._attr_translation_key
        for lang, path in files.items():
            d = json.loads(path.read_text(encoding="utf-8-sig"))
            name = d["entity"]["binary_sensor"].get(k, {}).get("name")
            assert name, f"{lang}: missing {k}"
            if lang == "ru":
                assert re_cyr(name), f"ru: {k} not translated: {name}"
        assert k in icons, f"icons: missing {k}"
        n += 1
    assert n == 95


def re_cyr(s):
    import re
    return bool(re.search(r"[А-Яа-яЁё]", s))


def test_raw_sensors_retired_and_cleanup_covers():
    sensor_src = (CC / "sensor.py").read_text()
    assert 'bit_map' in sensor_src  # raw BITFIELD sensors skipped at setup
    init_src = (CC / "__init__.py").read_text()
    assert "_bin_" in init_src  # registry cleanup parses bin uids + drops retired raw uids
    assert "binary_sensor" in init_src.split("PLATFORMS")[1].split("]")[0]


def test_bits_routed_to_sub_devices_and_polled():
    ents = {e._attr_translation_key: e for e in _setup(expert=True)}
    s01 = ents["foxair_2034_bit12"]
    assert ("foxair", "eid_S") in s01._attr_device_info["identifiers"]  # S device, not main
    err = ents["foxair_2081_bit0"]
    assert ("foxair", "eid_ERR") in err._attr_device_info["identifiers"]
    o = ents["foxair_2019_bit0"]
    assert ("foxair", "eid") in o._attr_device_info["identifiers"]  # O stays main (expert)
    for addr in ("2034", "2081", "2019"):
        assert META[addr]["poll_tier"] in ("rare", "medium")  # in the poll loop
        assert META[addr]["poll_tier"] == "rare"
    assert META["2034"]["requires_expert"] is False  # S contacts without expert
