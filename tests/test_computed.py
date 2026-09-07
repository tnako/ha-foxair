#!/usr/bin/env python3
"""Offline computed-sensor tests (no HA installed).

Regression cover for the 2026-09-07 incidents:
- external electric meter source was offered in Options but unimplemented
  (compute_electrical_power returned None for anything but foxair_register,
  so electrical power + COP stayed unknown)
- Options/backend parity: every elec_source choice in config_flow must be
  handled in computed.py

Run: pytest tests/test_computed.py -v
"""
import importlib.util
import pathlib
import re
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _stub_modules():
    ha = types.ModuleType("homeassistant")
    ha.helpers = types.ModuleType("homeassistant.helpers")
    ha.helpers.entity = types.ModuleType("homeassistant.helpers.entity")

    class DeviceInfo(dict):
        def __init__(self, identifiers=None, name=None, manufacturer=None,
                     model=None, via_device=None):
            super().__init__(identifiers=identifiers, name=name,
                             manufacturer=manufacturer, model=model,
                             via_device=via_device)

    ha.helpers.entity.DeviceInfo = DeviceInfo
    for m in (ha, ha.helpers, ha.helpers.entity):
        sys.modules[m.__name__] = m


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_stub_modules()
const = _load("foxair_const_computed_test", CC / "const.py")
pkg = types.ModuleType("foxair_pkg_computed")
pkg.__path__ = []
sys.modules["foxair_pkg_computed"] = pkg
sys.modules["foxair_pkg_computed.const"] = const
_src = (CC / "computed.py").read_text().replace(
    "from .const import", "from foxair_pkg_computed.const import")
comp = types.ModuleType("foxair_computed_test")
sys.modules["foxair_computed_test"] = comp
exec(compile(_src, str(CC / "computed.py"), "exec"), comp.__dict__)


class FakeState:
    def __init__(self, state, unit=None):
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit else {}


class FakeStates:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, entity_id):
        return self._m.get(entity_id)


class FakeHass:
    def __init__(self, mapping):
        self.states = FakeStates(mapping)


class FakeCoord:
    def __init__(self, data, hass=None):
        self.data = data
        self.hass = hass or FakeHass({})


def _opts(source, entity="sensor.meter10_power"):
    return {"elec_source": source, "external_meter_entity": entity}


def test_register_source_kw_to_w():
    coord = FakeCoord({2054: {"value": 0.5}})
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) == 500.0


def test_register_source_missing_is_none():
    coord = FakeCoord({})
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) is None


def test_external_meter_watts_passthrough():
    hass = FakeHass({"sensor.meter10_power": FakeState("9", "W")})
    coord = FakeCoord({}, hass)
    assert comp.compute_electrical_power(coord, _opts("external_meter")) == 9.0


def test_external_meter_kw_converted_to_w():
    hass = FakeHass({"sensor.meter10_power": FakeState("1.5", "kW")})
    coord = FakeCoord({}, hass)
    assert comp.compute_electrical_power(coord, _opts("external_meter")) == 1500.0


def test_external_meter_bad_states_are_none():
    for bad in ("unknown", "unavailable", "", "not_a_number"):
        hass = FakeHass({"sensor.meter10_power": FakeState(bad, "W")})
        coord = FakeCoord({}, hass)
        assert comp.compute_electrical_power(coord, _opts("external_meter")) is None
    assert comp.compute_electrical_power(FakeCoord({}, FakeHass({})), _opts("external_meter")) is None
    assert comp.compute_electrical_power(FakeCoord({}), _opts("external_meter", "")) is None


def test_cop_from_external_meter():
    hass = FakeHass({"sensor.meter10_power": FakeState("500", "W")})
    coord = FakeCoord({2059: {"value": 2.0}}, hass)
    assert comp.compute_cop(coord, _opts("external_meter")) == 4.0


def test_cop_gated_below_min_power():
    hass = FakeHass({"sensor.meter10_power": FakeState("50", "W")})
    coord = FakeCoord({2059: {"value": 2.0}}, hass)
    assert comp.compute_cop(coord, _opts("external_meter")) is None


def test_elec_source_options_all_handled():
    flow = (CC / "config_flow.py").read_text()
    m = re.search(r'"elec_source".*?vol\.In\(\[(.*?)\]\)', flow, re.S)
    assert m, "elec_source vol.In not found in config_flow.py"
    offered = set(re.findall(r'"([^"]+)"', m.group(1)))
    src = (CC / "computed.py").read_text()
    handled = set(re.findall(r'source == "([^"]+)"', src))
    assert offered <= handled, f"unhandled elec_source: {offered - handled}"
