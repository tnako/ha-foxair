#!/usr/bin/env python3
"""Mode-gated power / per-mode COP / energy accumulation tests.

Covers:
- active_mode classification from register 2012 (incl. defrost=heating,
  sterilization=dhw)
- compute_thermal_power / compute_cooling_power mode gating
- compute_cop_mode per-mode COP
- coordinator energy accumulation (mocked, no HA)

Run: pytest tests/test_modes_energy.py -v
"""
import importlib.util
import pathlib
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
const = _load("foxair_const_modes_test", CC / "const.py")
pkg = types.ModuleType("foxair_pkg_modes")
pkg.__path__ = []
sys.modules["foxair_pkg_modes"] = pkg
sys.modules["foxair_pkg_modes.const"] = const
_src = (CC / "computed.py").read_text().replace(
    "from .const import", "from foxair_pkg_modes.const import")
comp = types.ModuleType("foxair_modes_test")
sys.modules["foxair_modes_test"] = comp
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


def _opts(source="foxair_register"):
    return {"elec_source": source}


def _heating_data(rs=1, t59=2.0, t54=0.5):
    return {2012: {"raw": rs}, 2059: {"value": t59}, 2054: {"value": t54},
            2072: {"value": 40.0}}


# ---------- active_mode ----------

def test_active_mode_mapping():
    for rs, expected in ((1, "heating"), (0, "cooling"), (4, "dhw"),
                         (2, "defrost"), (3, "dhw")):
        assert comp.active_mode(FakeCoord({2012: {"raw": rs}})) == expected


def test_active_mode_unknown_when_missing():
    assert comp.active_mode(FakeCoord({})) is None
    assert comp.active_mode(FakeCoord({2012: {"raw": None}})) is None


# ---------- compute_thermal_power ----------

def test_thermal_heating_only_when_heating():
    coord = FakeCoord(_heating_data(rs=1))
    assert comp.compute_thermal_power(coord, "heating") == 2000.0
    assert comp.compute_thermal_power(coord, "cooling") is None
    assert comp.compute_thermal_power(coord, "dhw") is None


def test_thermal_cooling_mode_yields_none_via_t59_gating():
    # While status=Cooling the heating path is not valid for the cooling
    # bucket: compute_thermal_power('cooling') returns the heating-power
    # computation only if mode matches; T59 value itself is not cooling.
    coord = FakeCoord(_heating_data(rs=0))
    assert comp.compute_thermal_power(coord, "cooling") == 2000.0
    assert comp.compute_thermal_power(coord, "heating") is None


def test_thermal_missing_2012_falls_back_heating_only():
    coord = FakeCoord({2059: {"value": 2.0}})
    assert comp.compute_thermal_power(coord, "heating") == 2000.0
    assert comp.compute_thermal_power(coord, "cooling") is None
    assert comp.compute_thermal_power(coord, "dhw") is None


# ---------- compute_cooling_power ----------

def test_cooling_power_from_inverted_delta_t():
    # Cooling: outlet colder than inlet. T02=18, T01=21 -> dT=3K
    coord = FakeCoord({2012: {"raw": 0}, 2077: {"value": 1.0},
                       2046: {"value": 18.0}, 2045: {"value": 21.0}})
    assert comp.compute_cooling_power(coord) == pytest.approx(
        1.0 * 1000 * 4186 * 3.0 / 3600)


def test_cooling_power_none_when_not_cooling():
    coord = FakeCoord({2012: {"raw": 1}, 2077: {"value": 1.0},
                       2046: {"value": 18.0}, 2045: {"value": 21.0}})
    assert comp.compute_cooling_power(coord) is None


def test_cooling_power_none_when_outlet_not_colder():
    coord = FakeCoord({2012: {"raw": 0}, 2077: {"value": 1.0},
                       2046: {"value": 21.0}, 2045: {"value": 21.0}})
    assert comp.compute_cooling_power(coord) is None


# ---------- compute_cop_mode ----------

def test_cop_mode_heating():
    coord = FakeCoord(_heating_data(rs=1, t59=2.0, t54=0.5))
    assert comp.compute_cop_mode(coord, _opts(), "heating") == 4.0
    assert comp.compute_cop_mode(coord, _opts(), "cooling") is None


def test_cop_mode_cooling_uses_cooling_power():
    coord = FakeCoord({2012: {"raw": 0}, 2077: {"value": 1.0},
                       2046: {"value": 18.0}, 2045: {"value": 21.0},
                       2054: {"value": 0.4}})
    cool_w = 1.0 * 1000 * 4186 * 3.0 / 3600
    assert comp.compute_cop_mode(coord, _opts(), "cooling") == pytest.approx(
        round(cool_w / 400.0, 2))


def test_cop_mode_dhw_only_in_dhw_status():
    coord = FakeCoord(_heating_data(rs=4))
    assert comp.compute_cop_mode(coord, _opts(), "dhw") == 4.0
    assert comp.compute_cop_mode(coord, _opts(), "heating") is None


def test_overall_cop_suppressed_when_not_heating():
    # "COP — Heating" (uid foxair_cop) must not count while the unit is
    # cooling or in DHW: T59 may still report capacity there.
    coord = FakeCoord(_heating_data(rs=0))  # cooling status
    assert comp.compute_cop(coord, _opts()) is None
    coord = FakeCoord(_heating_data(rs=4))  # DHW status
    assert comp.compute_cop(coord, _opts()) is None
    # Defrost counts as heating.
    coord = FakeCoord(_heating_data(rs=2))
    assert comp.compute_cop(coord, _opts()) == 4.0
    # 2012 missing -> old behaviour preserved.
    coord = FakeCoord({2059: {"value": 2.0}, 2054: {"value": 0.5}})
    assert comp.compute_cop(coord, _opts()) == 4.0


def test_cooling_power_gated_on_compressor():
    # Pump-only circulation in cooling mode must not produce phantom watts.
    coord = FakeCoord({2012: {"raw": 0}, 2077: {"value": 1.0},
                       2046: {"value": 18.0}, 2045: {"value": 21.0},
                       2072: {"value": 0.0}})
    assert comp.compute_cooling_power(coord) is None
    # Compressor evidence missing -> old behaviour (ungated).
    coord = FakeCoord({2012: {"raw": 0}, 2077: {"value": 1.0},
                       2046: {"value": 18.0}, 2045: {"value": 21.0}})
    assert comp.compute_cooling_power(coord) == pytest.approx(
        1.0 * 1000 * 4186 * 3.0 / 3600)


# ---------- coordinator energy accumulation ----------

def _mk_coord_cls(comp_mod):
    """Load coordinator.py with computed patched to the test module."""
    # Stub the HA/pymodbus imports coordinator.py needs at module level.
    ha_uc = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        def __init__(self, *a, **k):
            pass

    ha_uc.DataUpdateCoordinator = DataUpdateCoordinator
    ha_uc.UpdateFailed = type("UpdateFailed", (Exception,), {})
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_uc
    ha_ex = types.ModuleType("homeassistant.exceptions")

    class ConfigEntryNotReady(Exception):
        pass

    ha_ex.ConfigEntryNotReady = ConfigEntryNotReady
    sys.modules["homeassistant.exceptions"] = ha_ex
    pm = types.ModuleType("pymodbus")
    pmc = types.ModuleType("pymodbus.client")
    pmc.AsyncModbusTcpClient = object
    sys.modules["pymodbus"] = pm
    sys.modules["pymodbus.client"] = pmc
    pmr = types.ModuleType("pymodbus Register None")

    class _Exc(Exception):
        pass

    pmr.ModbusException = _Exc
    sys.modules["pymodbus.exceptions"] = pmr

    src = (CC / "coordinator.py").read_text()
    src = src.replace("from .const import", "from foxair_pkg_modes.const import")
    src = src.replace("from . import const as _const", "import foxair_pkg_modes.const as _const")
    src = src.replace("from . import computed as _computed",
                      "import foxair_modes_test as _computed")
    src = src.replace("from .computed import", "from foxair_modes_test import")
    mod = types.ModuleType("foxair_coord_modes_test")
    sys.modules["foxair_coord_modes_test"] = mod
    mod.__dict__["__file__"] = str(CC / "coordinator.py")
    exec(compile(src, str(CC / "coordinator.py"), "exec"), mod.__dict__)
    mod.time = types.SimpleNamespace(monotonic=lambda: 1000.0)
    return mod


def test_accumulate_energy_heating(tmp_path):
    mod = _mk_coord_cls(comp)

    class FakeEntry:
        data = {}
        options = {}

    c = object.__new__(mod.FoxAirCoordinator)
    c.entry = FakeEntry()
    c.energy_kwh = {"heating": 0.0, "cooling": 0.0, "dhw": 0.0,
                    "defrost": 0.0, "electrical": 0.0}
    c._energy_last_ts = None
    # first call only stamps the timestamp
    c._accumulate_energy()
    assert c.energy_kwh == {"heating": 0.0, "cooling": 0.0, "dhw": 0.0,
                            "defrost": 0.0, "electrical": 0.0}
    # second call 30s later, heating active: T59=2kW, T54=0.5kW
    c.data = _heating_data(rs=1)
    c._energy_last_ts = c._energy_last_ts - 30  # 30s ago
    c._accumulate_energy()
    assert c.energy_kwh["heating"] == pytest.approx(2000 * 30 / 3600 / 1000)
    assert c.energy_kwh["electrical"] == pytest.approx(500 * 30 / 3600 / 1000)
    assert c.energy_kwh["cooling"] == 0.0


def test_accumulate_energy_defrost_separate_bucket(tmp_path):
    mod = _mk_coord_cls(comp)

    class FakeEntry:
        data = {}
        options = {}

    c = object.__new__(mod.FoxAirCoordinator)
    c.entry = FakeEntry()
    c.energy_kwh = {"heating": 0.0, "cooling": 0.0, "dhw": 0.0,
                    "defrost": 0.0, "electrical": 0.0}
    c._energy_last_ts = None
    c._accumulate_energy()
    # defrost status (2012=2): thermal power books to the defrost bucket,
    # not heating; electrical still accumulates
    c.data = _heating_data(rs=2)
    c._energy_last_ts = c._energy_last_ts - 30
    c._accumulate_energy()
    assert c.energy_kwh["defrost"] == pytest.approx(2000 * 30 / 3600 / 1000)
    assert c.energy_kwh["heating"] == 0.0
    assert c.energy_kwh["electrical"] == pytest.approx(500 * 30 / 3600 / 1000)
