#!/usr/bin/env python3
"""Water heater (DHW tank) entity: registers from the dhw marker, limits R36/R37, H28 gate.

Run: pytest tests/test_water_heater.py -v
"""
import asyncio
import json
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"
CFG = json.loads((CC / "data/foxair_config.json").read_text(encoding="utf-8"))
DHW = CFG["markers"]["dhw"]["addr_single"]
META = json.loads((CC / "data/foxair_metadata.json").read_text(encoding="utf-8"))


def _load():
    wh = types.ModuleType("homeassistant.components.water_heater")

    class WaterHeaterEntity:
        pass

    class WaterHeaterEntityFeature:
        TARGET_TEMPERATURE = 1

    wh.WaterHeaterEntity = WaterHeaterEntity
    wh.WaterHeaterEntityFeature = WaterHeaterEntityFeature
    wh.STATE_HEAT_PUMP = "heat_pump"
    const = types.ModuleType("homeassistant.const")
    const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
    const.STATE_OFF = "off"
    uc = types.ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __init__(self, coord):
            self.coordinator = coord

        @property
        def available(self):
            return True

    uc.CoordinatorEntity = CoordinatorEntity
    fconst = types.ModuleType("foxair_wh_pkg.const")
    fconst.main_device = lambda *a, **k: {"identifiers": {("foxair", a[0])}}
    fconst.get_device_prefix = lambda e: "foxair"
    fconst.get_slave_id = lambda e: 1
    fconst.bind_device_info = lambda h, e, info: info
    pkg = types.ModuleType("foxair_wh_pkg")
    pkg.__path__ = []
    for name, m in {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.components.water_heater": wh,
        "homeassistant.const": const,
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.update_coordinator": uc,
        "foxair_wh_pkg": pkg,
        "foxair_wh_pkg.const": fconst,
    }.items():
        sys.modules[name] = m
    hc = types.ModuleType("foxair_wh_pkg.heating_curve")
    sys.modules[hc.__name__] = hc
    exec(compile((CC / "heating_curve.py").read_text(), str(CC / "heating_curve.py"), "exec"), hc.__dict__)
    src = (CC / "water_heater.py").read_text().replace("from .", "from foxair_wh_pkg.")
    mod = types.ModuleType("foxair_wh_pkg.water_heater")
    exec(compile(src, str(CC / "water_heater.py"), "exec"), mod.__dict__)
    return mod


wh = _load()


class FakeCoord:
    def __init__(self, data):
        self.data = data
        self.entry = types.SimpleNamespace(entry_id="t", data={"host": "h", "port": 1}, options={})
        self.writes = []

    def marker(self, name):
        return CFG["markers"].get(name, {})

    def get_metadata(self, addr):
        return META.get(str(addr), {})

    async def async_write_register(self, addr, value):
        self.writes.append((addr, value))
        return True


MODE_ADDR = CFG["markers"]["status"]["addr_single"]["mode"]
MODES = CFG["markers"]["status"]["mode_values"]


def _ent(h28=1, mode=MODES["heating_dhw"], **over):
    data = {DHW["target"]: {"value": 50.0}, DHW["current"]: {"value": 47.5},
            DHW["min"]: {"value": 15.0}, DHW["max"]: {"value": 53.0}, DHW["enabled"]: {"raw": h28},
            MODE_ADDR: {"raw": mode}}
    data.update(over)
    return wh.FoxAirWaterHeater(FakeCoord(data))


def test_reads_target_tank_and_limits():
    ent = _ent()
    assert (ent.target_temperature, ent.current_temperature) == (50.0, 47.5)
    assert (ent.min_temp, ent.max_temp) == (15.0, 53.0)
    assert ent._attr_unique_id == "foxair_dhw"
    assert ent.available


def test_set_temperature_writes_r01():
    ent = _ent()
    asyncio.run(ent.async_set_temperature(temperature=52.0))
    assert ent.coordinator.writes == [(DHW["target"], 52.0)]


def test_set_temperature_outside_device_limits_rejected():
    ent = _ent()
    with pytest.raises(ValueError):
        asyncio.run(ent.async_set_temperature(temperature=60.0))
    assert ent.coordinator.writes == []


def test_unavailable_without_dhw_function():
    assert not _ent(h28=0).available


def test_limits_fall_back_to_metadata():
    ent = wh.FoxAirWaterHeater(FakeCoord({DHW["target"]: {"value": 50.0}}))
    assert ent.min_temp == META[str(DHW["target"])]["min"]
    assert ent.max_temp == META[str(DHW["target"])]["max"]


def test_dhw_marker_registers_polled_without_expert():
    for key, addr in DHW.items():
        m = META[str(addr)]
        assert not m.get("hidden") and not m.get("requires_expert") and m.get("risk") != "blocked", (key, addr)


@pytest.mark.parametrize("key,state", [("heating_dhw", "heat_pump"), ("cooling_dhw", "heat_pump"), ("dhw_only", "heat_pump"), ("heating", "off"), ("cooling", "off")])
def test_state_follows_dhw_in_mode_word(key, state):
    assert _ent(mode=MODES[key]).current_operation == state


def test_state_unknown_before_mode_polled():
    ent = wh.FoxAirWaterHeater(FakeCoord({DHW["target"]: {"value": 50.0}}))
    assert ent.current_operation is None
