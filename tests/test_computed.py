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

import pytest

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
    def __init__(self, data, hass=None, fw=33):
        self.data = data
        self.hass = hass or FakeHass({})
        self._fw = fw

    def fw_version(self):
        return self._fw


def _opts(source, entity="sensor.meter10_power"):
    return {"elec_source": source, "external_meter_entity": entity}


def test_register_source_kw_to_w():
    coord = FakeCoord({2054: {"value": 0.5}})
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) == 500.0


def test_register_source_zero_falls_through_to_fallback():
    # His unit reports T54/T59/T60 = 0 while actually heating (flow 1.45,
    # deltaT 1.6K). 0 means "unit does not compute it", not 0 W.
    coord = FakeCoord({2054: {"value": 0.0}, 2059: {"value": 0.0},
                       2077: {"value": 1.45}, 2045: {"value": 43.3},
                       2046: {"value": 44.9}})
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) is None
    assert comp.compute_heating_power(coord) == pytest.approx(
        1.45 * 1000 * 4186 * 1.6 / 3600)


def test_register_source_missing_is_none():
    coord = FakeCoord({})
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) is None


def test_pre33_fw_falls_back_to_ac_va():
    # fw 13 (v1.3) unit: T54 reads 0 while heating (diagnostics-confirmed);
    # apparent power = AC volts (2062) x amps (2057, 0.1 A scaling).
    coord = FakeCoord({2054: {"value": 0.0}, 2062: {"value": 231.0},
                       2057: {"value": 4.8}}, fw=13)
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) == pytest.approx(1108.8)


def test_pre33_fw_missing_va_inputs_are_none():
    coord = FakeCoord({2054: {"value": 0.0}, 2062: {"value": 231.0}}, fw=13)
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) is None
    coord = FakeCoord({2054: {"value": 0.0}}, fw=13)
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) is None


def test_pre33_fw_t54_wins_when_nonzero():
    coord = FakeCoord({2054: {"value": 0.5}, 2062: {"value": 231.0},
                       2057: {"value": 4.8}}, fw=13)
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) == 500.0


def test_fw_unknown_gets_no_va_estimate():
    coord = FakeCoord({2054: {"value": 0.0}, 2062: {"value": 231.0},
                       2057: {"value": 4.8}}, fw=0)
    assert comp.compute_electrical_power(coord, _opts("foxair_register")) is None


def test_cop_from_ac_va_on_pre33_fw():
    # Same shape as the reporter's diagnostics snapshot: flow 1.45, dT 1.6 K.
    coord = FakeCoord({2059: {"value": 0.0}, 2077: {"value": 1.45},
                       2045: {"value": 43.3}, 2046: {"value": 44.9},
                       2062: {"value": 231.0}, 2057: {"value": 4.8}}, fw=13)
    hp = 1.45 * 1000 * 4186 * 1.6 / 3600
    assert comp.compute_cop(coord, _opts("foxair_register")) == pytest.approx(
        round(hp / 1108.8, 2))


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


def test_heating_power_fallback_flow_delta_t():
    # Fallback: P = flow * 1000 * 4186 * dT / 3600
    # Inlet is 2045 (T01), outlet 2046 (T02); 2047 is the DHW tank, not inlet.
    coord = FakeCoord({2077: {"value": 1.0}, 2046: {"value": 35.0},
                       2045: {"value": 30.0}, 2047: {"value": 50.0}})
    assert comp.compute_heating_power(coord) == pytest.approx(1.0 * 1000 * 4186 * 5.0 / 3600)


def test_pump_only_t59_phantom_is_suppressed():
    # v3.3+/v3.4: compressor off (T31 = 0) but T59 keeps counting heat while
    # the water pump circulates -> heating power must be None, not phantom kW.
    coord = FakeCoord({2072: {"value": 0.0}, 2059: {"value": 2.5}})
    assert comp.compute_heating_power(coord) is None


def test_pump_only_delta_t_offset_is_suppressed():
    # v3.4 pump-only: no compressor, but flow + small sensor-offset dT
    # (T02 20.0 vs T01 19.7) produced phantom watts via the fallback.
    coord = FakeCoord({2072: {"value": 0.0}, 2077: {"value": 1.45},
                       2045: {"value": 19.7}, 2046: {"value": 20.0}})
    assert comp.compute_heating_power(coord) is None


def test_pump_only_2019_bit0_fallback_gate():
    # T31 missing -> bit 0 of 2019 ("Kompressor läuft") gates instead.
    # raw bit0=0 (pump only, 0x10 = pump output bit 4):
    coord = FakeCoord({2019: {"raw": 0x10}, 2059: {"value": 2.5}})
    assert comp.compute_heating_power(coord) is None
    # raw bit0=1 (compressor running): T59 trusted again.
    coord = FakeCoord({2019: {"raw": 0x11}, 2059: {"value": 2.5}})
    assert comp.compute_heating_power(coord) == 2500.0


def test_compressor_running_keeps_t59_trust():
    # Compressor on (T31 > 0): unchanged behaviour, register wins.
    coord = FakeCoord({2072: {"value": 42.0}, 2059: {"value": 7.8}})
    assert comp.compute_heating_power(coord) == pytest.approx(7800.0)


def test_missing_compressor_evidence_keeps_old_behaviour():
    # No T31 and no 2019 in data (older units / partial polls): do NOT gate,
    # pre-v3.3 COP fix relied on the fallback path with such data.
    coord = FakeCoord({2077: {"value": 1.45}, 2045: {"value": 43.3},
                       2046: {"value": 44.9}})
    assert comp.compute_heating_power(coord) == pytest.approx(
        1.45 * 1000 * 4186 * 1.6 / 3600)
    coord = FakeCoord({2059: {"value": 2.0}})
    assert comp.compute_heating_power(coord) == 2000.0


def test_v13_diagnostics_snapshot_unaffected():
    # Replay of the real v1.3 diagnostics dump (config_entry-...-4.json):
    # compressor running (T31=47, 2019=0b10101) while heating, T54/T59/T60
    # all report 0 (old firmware never computes them). The gate must not
    # change the outcome: fallback flow/dT heating power + V*A electrical
    # power keep COP alive exactly as the v1.3 fix intended.
    coord = FakeCoord({2012: {"raw": 1}, 2019: {"raw": 21},
                       2045: {"value": 43.3}, 2046: {"value": 44.9},
                       2054: {"value": 0.0}, 2059: {"value": 0.0},
                       2060: {"value": 0.0}, 2062: {"value": 231.0},
                       2057: {"value": 4.8}, 2072: {"value": 47.0},
                       2077: {"value": 1.45}}, fw=13)
    hp = comp.compute_heating_power(coord)
    assert hp == pytest.approx(1.45 * 1000 * 4186 * 1.6 / 3600)
    ep = comp.compute_electrical_power(coord, _opts("foxair_register"))
    assert ep == pytest.approx(1108.8)
    assert comp.compute_cop(coord, _opts("foxair_register")) == pytest.approx(
        round(hp / 1108.8, 2))


def test_cop_none_when_pump_only():
    # End to end: pump-only phantom T59 must not produce a COP.
    coord = FakeCoord({2072: {"value": 0.0}, 2059: {"value": 2.5},
                       2054: {"value": 0.3}})
    assert comp.compute_cop(coord, _opts("foxair_register")) is None


def test_elec_source_options_all_handled():
    flow = (CC / "config_flow.py").read_text()
    m = re.search(r'"elec_source".*?vol\.In\(\[(.*?)\]\)', flow, re.S)
    assert m, "elec_source vol.In not found in config_flow.py"
    offered = set(re.findall(r'"([^"]+)"', m.group(1)))
    src = (CC / "computed.py").read_text()
    handled = set(re.findall(r'source == "([^"]+)"', src))
    assert offered <= handled, f"unhandled elec_source: {offered - handled}"
