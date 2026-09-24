#!/usr/bin/env python3
"""Climate follows the H25 control source (outlet/room/buffer/inlet).

Covers current_temperature, target register, H36 curve gating, cooling
setpoint, and the write address, all driven by foxair_config.json markers.

Run: pytest tests/test_climate_control_source.py -v
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
MARKERS = CFG["markers"]
CS = MARKERS["control_source"]
SELECTOR = CS["addr_single"]["selector"]
STATUS = MARKERS["status"]["addr_single"]
HC = MARKERS["heat_curve"]["addr_single"]
SP = MARKERS["setpoints"]["addr_single"]
META = json.loads((CC / "data/foxair_metadata.json").read_text(encoding="utf-8"))
MODE = MARKERS["status"]["mode_values"]


def _stub_ha():
    climate = types.ModuleType("homeassistant.components.climate")

    class ClimateEntity:
        min_temp = 7.0
        max_temp = 35.0

        def async_write_ha_state(self):
            pass

    class _Enum:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    climate.ClimateEntity = ClimateEntity
    climate.HVACMode = _Enum(OFF="off", HEAT="heat")
    climate.HVACAction = _Enum(OFF="off", HEATING="heating", COOLING="cooling", IDLE="idle", DEFROSTING="defrosting")
    climate.ClimateEntityFeature = _Enum(TARGET_TEMPERATURE=1, PRESET_MODE=16)
    const = types.ModuleType("homeassistant.const")
    const.UnitOfTemperature = _Enum(CELSIUS="°C")
    uc = types.ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __init__(self, coord):
            self.coordinator = coord

    uc.CoordinatorEntity = CoordinatorEntity
    pkg = types.ModuleType("foxair_climate_pkg")
    pkg.__path__ = []
    fconst = types.ModuleType("foxair_climate_pkg.const")
    fconst.main_device = lambda *a, **k: {}
    fconst.get_device_prefix = lambda e: "foxair"
    fconst.get_slave_id = lambda e: 1
    fconst.bind_device_info = lambda h, e, info: info
    mods = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.components.climate": climate,
        "homeassistant.const": const,
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.update_coordinator": uc,
        "foxair_climate_pkg": pkg,
        "foxair_climate_pkg.const": fconst,
    }
    sys.modules.update(mods)
    for name in ("heating_curve", "computed"):
        dep = types.ModuleType(f"foxair_climate_pkg.{name}")
        sys.modules[dep.__name__] = dep
        dep_src = (CC / f"{name}.py").read_text().replace("from .", "from foxair_climate_pkg.")
        exec(compile(dep_src, str(CC / f"{name}.py"), "exec"), dep.__dict__)
    src = (CC / "climate.py").read_text().replace("from .", "from foxair_climate_pkg.")
    mod = types.ModuleType("foxair_climate_pkg.climate")
    sys.modules[mod.__name__] = mod
    exec(compile(src, str(CC / "climate.py"), "exec"), mod.__dict__)
    return mod


climate = _stub_ha()


class FakeCoord:
    def __init__(self, data):
        self.data = data
        self.entry = types.SimpleNamespace(entry_id="t", data={"host": "h", "port": 1}, options={})
        self.writes = []

    def marker(self, name):
        return MARKERS.get(name, {})

    def get_metadata(self, addr):
        return {}

    async def async_write_register(self, addr, value):
        self.writes.append((addr, value))
        return True

    async def async_write_many(self, mapping):
        self.writes.append(dict(mapping))
        return True


LIMITS = {"heating_min": 20.0, "heating_max": 55.0, "cooling_min": 7.0, "cooling_max": 25.0}


def _data(h25=None, h36=0, mode=MODE["heating"]):
    d = {STATUS["mode"]: {"raw": mode, "value": mode}, HC["at_comp_en"]: {"raw": h36, "value": h36},
         HC["live_target"]: {"value": 33.3}, SP["heating_target"]: {"value": 40.0},
         SP["cooling_target"]: {"value": 18.0}}
    for key, v in LIMITS.items():
        d[SP[key]] = {"value": v}
    if h25 is not None:
        d[SELECTOR] = {"raw": h25, "value": h25}
    for raw, e in CS["by_value"].items():
        d[e["current"]] = {"value": 100.0 + int(raw)}
        if e.get("target"):
            d[e["target"]] = {"value": 21.5}
    return d


def _ent(**kw):
    return climate.FoxAirClimate(FakeCoord(_data(**kw)))


@pytest.mark.parametrize("raw", sorted(CS["by_value"]))
def test_current_temperature_follows_h25(raw):
    ent = _ent(h25=int(raw))
    assert ent.current_temperature == 100.0 + int(raw)
    assert ent.extra_state_attributes["control_source"] == CS["by_value"][raw]["key"]


def test_unknown_h25_falls_back_to_default():
    ent = _ent(h25=None)
    default = CS["by_value"][str(CS["default"])]
    assert ent.current_temperature == 100.0 + int(CS["default"])
    assert ent.extra_state_attributes["current_addr"] == default["current"]


@pytest.mark.parametrize("raw", sorted(CS["by_value"]))
@pytest.mark.parametrize("h36", [0, 1])
@pytest.mark.parametrize("mode", [MODE["heating"], MODE["cooling"], MODE["heating_dhw"], MODE["cooling_dhw"]])
def test_target_matrix(raw, h36, mode):
    src = CS["by_value"][raw]
    ent = _ent(h25=int(raw), h36=h36, mode=mode)
    cooling = mode in (MODE["cooling"], MODE["cooling_dhw"])
    if src.get("target"):
        assert ent.target_temperature == 21.5
        assert ent.extra_state_attributes["target_addr"] == src["target"]
    elif cooling:
        assert ent.target_temperature == 18.0
        assert ent.extra_state_attributes["target_addr"] == SP["cooling_target"]
    elif h36 == 1:
        assert ent.target_temperature == 33.3
        assert ent.min_temp == ent.max_temp == 33.3
    else:
        assert ent.target_temperature == 40.0
        assert ent.extra_state_attributes["target_addr"] == SP["heating_target"]


@pytest.mark.parametrize("raw", sorted(CS["by_value"]))
def test_set_temperature_writes_active_setpoint(raw):
    src = CS["by_value"][raw]
    ent = _ent(h25=int(raw), h36=1 if src.get("target") else 0)
    asyncio.run(ent.async_set_temperature(temperature=22.0, hvac_mode="heat"))
    assert ent.coordinator.writes == [(src.get("target") or SP["heating_target"], 22.0)]


def test_set_temperature_cooling_ignores_hvac_mode_kwarg():
    ent = _ent(h25=0, mode=MODE["cooling"])
    asyncio.run(ent.async_set_temperature(temperature=17.0, hvac_mode="heat"))
    assert ent.coordinator.writes == [(SP["cooling_target"], 17.0)]


def test_curve_heating_water_source_blocks_write():
    ent = _ent(h25=next(int(k) for k, v in CS["by_value"].items() if not v.get("target")), h36=1)
    with pytest.raises(ValueError):
        asyncio.run(ent.async_set_temperature(temperature=22.0))
    assert ent.coordinator.writes == []


def test_marker_addrs_are_polled_non_expert():
    meta = json.loads((CC / "data/foxair_metadata.json").read_text(encoding="utf-8"))
    addrs = {SELECTOR}
    for e in CS["by_value"].values():
        addrs.add(e["current"])
        if e.get("target"):
            addrs.add(e["target"])
    for a in addrs:
        m = meta[str(a)]
        assert m.get("poll_tier") == "quick", a
        assert not m.get("hidden") and not m.get("requires_expert") and m.get("risk") != "blocked", a


@pytest.mark.parametrize("mode,prefix", [(MODE["heating"], "heating"), (MODE["cooling"], "cooling")])
def test_water_limits_follow_device_setpoint_limits(mode, prefix):
    ent = _ent(h25=0, mode=mode)
    assert (ent.min_temp, ent.max_temp) == (LIMITS[f"{prefix}_min"], LIMITS[f"{prefix}_max"])


def test_limits_fall_back_to_ha_defaults_without_data():
    ent = climate.FoxAirClimate(FakeCoord({}))
    assert (ent.min_temp, ent.max_temp) == (7.0, 35.0)


def test_power_on_from_dhw_only_mode_selects_heating():
    ent = _ent(h25=0, mode=MODE["dhw_only"])
    assert ent.preset_mode == "Heating + Hot Water"
    asyncio.run(ent.async_set_hvac_mode("heat"))
    assert ent.coordinator.writes == [{STATUS["power"]: 1.0, STATUS["mode"]: float(MODE["heating"])}]


def test_power_on_keeps_existing_preset():
    ent = _ent(h25=0, mode=MODE["cooling_dhw"])
    asyncio.run(ent.async_set_hvac_mode("heat"))
    assert ent.coordinator.writes == [{STATUS["power"]: 1.0}]
    assert ent._opt_hvac is None


def test_power_off():
    ent = _ent(h25=0)
    asyncio.run(ent.async_set_hvac_mode("off"))
    assert ent.coordinator.writes == [{STATUS["power"]: 0.0}]


@pytest.mark.parametrize("run,expected", [(0, "cooling"), (1, "heating"), (2, "defrosting"), (3, "heating"), (4, "heating"), (None, "idle")])
def test_hvac_action_from_run_status(run, expected):
    d = _data(h25=0)
    d[STATUS["run_status"]] = {"raw": run, "value": run}
    assert climate.FoxAirClimate(FakeCoord(d)).hvac_action == expected


def test_hvac_action_off_when_powered_off():
    d = _data(h25=0)
    d[STATUS["power"]] = {"raw": 0, "value": 0}
    d[STATUS["run_status"]] = {"raw": 1, "value": 1}
    assert climate.FoxAirClimate(FakeCoord(d)).hvac_action == "off"


def test_control_source_keys_match_h25_select_options():
    strings = json.loads((CC / "strings.json").read_text(encoding="utf-8"))
    code = json.loads((CC / "data/foxair_metadata.json").read_text(encoding="utf-8"))[str(SELECTOR)]["code"].lower()
    options = set(strings["entity"]["select"][f"foxair_{code}"]["state"])
    assert {e["key"] for e in CS["by_value"].values()} == options


@pytest.mark.parametrize("preset,key", list(climate.FoxAirClimate.PRESET_KEY.items()))
def test_preset_roundtrip(preset, key):
    ent = _ent(h25=0, mode=MODE[key])
    assert ent.preset_mode == preset
    asyncio.run(ent.async_set_preset_mode(preset))
    assert ent.coordinator.writes == [{STATUS["power"]: 1.0, STATUS["mode"]: float(MODE[key])}]


@pytest.mark.parametrize("raw", sorted(CS["by_value"]))
@pytest.mark.parametrize("mode", [MODE["heating"], MODE["cooling"]])
def test_active_control_registers_exist_and_follow_source(raw, mode):
    src = CS["by_value"][raw]
    coord = FakeCoord(_data(h25=int(raw), mode=mode))
    ctl = climate.active_control(coord)
    side = "cooling" if mode == MODE["cooling"] else "heating"
    regs = src if src.get("target") else SP
    for k in ("start", "stop"):
        assert ctl[k] == regs.get(f"{side}_{k}")
        assert str(ctl[k]) in META, (raw, side, k)
    assert ctl["current"] == src["current"] and str(ctl["target"]) in META
