#!/usr/bin/env python3
"""Offline multi-pump tests (no HA installed).

Covers the 2+ heat-pump hardening:
 - conflict matrix (_check_conflicts): fresh ok, prefix reuse, bus reuse,
   excluded entry ignored, legacy entry without name_prefix defaults foxair
 - device names carry prefix + slave; identifiers stay entry_id-scoped
 - translation_key is prefix-stable (foxair_*) on all platforms
 - suggested_object_id is prefix-scoped on all platforms
 - reconfigure step + prefix_in_use error exist in strings + en/de/ru
 - diagnostics exposes name_prefix
 - views require entry_id and return error SVG/HTML when missing
 - views list entries when no entry_id provided to panel

Run: pytest tests/test_multi_pump.py -v
"""
import importlib.util
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _stub_modules():
    ha = types.ModuleType("homeassistant")
    ha.config_entries = types.ModuleType("homeassistant.config_entries")
    ha.core = types.ModuleType("homeassistant.core")
    ha.helpers = types.ModuleType("homeassistant.helpers")
    ha.helpers.entity = types.ModuleType("homeassistant.helpers.entity")
    ha.components = types.ModuleType("homeassistant.components")

    class FakeFlow:
        def __init_subclass__(cls, **kw):
            pass

    ha.config_entries.ConfigFlow = FakeFlow
    ha.config_entries.OptionsFlow = FakeFlow

    def callback(fn):
        return fn

    ha.core.callback = callback

    class DeviceInfo(dict):
        def __init__(self, identifiers=None, name=None, manufacturer=None,
                     model=None, via_device=None):
            super().__init__(identifiers=identifiers, name=name,
                             manufacturer=manufacturer, model=model,
                             via_device=via_device)

    ha.helpers.entity.DeviceInfo = DeviceInfo
    for m in (ha, ha.config_entries, ha.core, ha.helpers, ha.helpers.entity,
              ha.components):
        sys.modules[m.__name__] = m

    vol = types.ModuleType("voluptuous")

    class _V:
        def __init__(self, *a, **k):
            pass

        def __call__(self, *a, **k):
            return self

    for n in ("Schema", "Optional", "Required", "In", "Coerce"):
        setattr(vol, n, _V)
    sys.modules["voluptuous"] = vol

    pm = types.ModuleType("pymodbus.client")

    class AsyncModbusTcpClient:
        def __init__(self, *a, **k):
            pass

    pm.AsyncModbusTcpClient = AsyncModbusTcpClient
    sys.modules["pymodbus"] = types.ModuleType("pymodbus")
    sys.modules["pymodbus.client"] = pm


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_stub_modules()
const = _load("foxair_const_test", CC / "const.py")
pkg = types.ModuleType("foxair_pkg")
pkg.__path__ = []
sys.modules["foxair_pkg"] = pkg
sys.modules["foxair_pkg.const"] = const
_src = (CC / "config_flow.py").read_text().replace(
    "from .const import", "from foxair_pkg.const import")
cf = types.ModuleType("foxair_config_flow_test")
sys.modules["foxair_config_flow_test"] = cf
exec(compile(_src, str(CC / "config_flow.py"), "exec"), cf.__dict__)


class FakeEntry:
    def __init__(self, entry_id, data):
        self.entry_id = entry_id
        self.data = data


class FakeCoord:
    """Minimal coordinator stub for views testing."""
    def __init__(self, entry):
        self.entry = entry
        self.data = {}

    def marker(self, name):
        return {"addr_single": {
            "slope": 1234, "offset": 1235, "at_comp_en": 1236,
            "live_target": 2014, "at_sensor": 2048,
            "r10_min": 1164, "r11_max": 1165,
            "r31_at_lo": 1166, "r34_at_hi": 1167,
        }}


def test_conflict_matrix():
    e1 = FakeEntry("e1", {"host": "h", "port": 8899, "slave": 1,
                          "name_prefix": "foxair"})
    entries = [e1]
    assert cf._check_conflicts(entries, "h", 8899, 2, "house1") is None
    assert cf._check_conflicts(entries, "h", 8899, 2, "foxair") == "name_prefix"
    assert cf._check_conflicts(entries, "h", 8899, 1, "house1") == "base"
    assert cf._check_conflicts(entries, "h", 8899, 1, "foxair",
                               exclude_entry_id="e1") is None


def test_legacy_entry_defaults_foxair():
    legacy = FakeEntry("old", {"host": "h", "port": 8899, "slave": 9})
    assert cf._check_conflicts([legacy], "h", 8899, 2, "foxair") == "name_prefix"
    assert const.get_device_prefix(legacy) == "foxair"


def test_device_names_carry_prefix_and_slave():
    main = const.main_device("e1", "house1", 2)
    assert "House1" in main["name"] and "slave 2" in main["name"]
    assert ("foxair", "e1") in main["identifiers"]
    sub = const.device_for_addr(2050, "T", "e1", "T", "house1", 2)
    assert "slave 2" in sub["name"] and "House1" in sub["name"]
    via = sub.get("via_device")
    assert via == ("foxair", "e1")


def test_translation_key_stable_and_object_id_prefixed():
    for plat, uid_pat in (("sensor", None), ("number", "_num_"),
                          ("select", "_sel_"), ("switch", "_switch_"),
                          ("time", "_time_")):
        src = (CC / f"{plat}.py").read_text()
        assert 'f"foxair_{addr}"' in src or '"foxair_{addr}"' in src, plat
        assert 'translation_key = f"{prefix}' not in src, plat
        assert "_attr_suggested_object_id" in src, plat
    climate = (CC / "climate.py").read_text()
    assert '"foxair_climate"' in climate
    assert "_attr_suggested_object_id" in climate
    image = (CC / "image.py").read_text()
    assert '"foxair_heating_curve"' in image


def test_reconfigure_strings_all_langs():
    for rel in ("strings.json", "translations/en.json",
                "translations/de.json", "translations/ru.json"):
        d = json.loads((CC / rel).read_text())
        assert "reconfigure" in d["config"]["step"], rel
        assert "prefix_in_use" in d["config"]["error"], rel


def test_diagnostics_exposes_prefix():
    src = (CC / "diagnostics.py").read_text()
    assert "name_prefix" in src


class FakeRequest:
    """Minimal aiohttp request stub."""
    def __init__(self, query_params, hass_data):
        self.query = query_params
        self.app = {"hass": types.SimpleNamespace(data=hass_data)}


def test_views_require_entry_id():
    """Views should return error SVG/HTML when entry_id missing or invalid."""
    views_src = (CC / "views.py").read_text()
    # SVG view checks entry_id and returns error SVG
    assert 'entry_id' in views_src
    assert 'entry_id not in foxair_data' in views_src
    # Panel view lists entries when no entry_id
    assert 'entries_html' in views_src
    assert 'entry_id' in views_src


def test_views_list_entries_no_entry_id():
    """Panel view should show picker when no entry_id provided."""
    # Load views module
    views_src = (CC / "views.py").read_text()
    # The panel view should have fallback HTML listing entries
    assert 'No pumps configured' in views_src
    assert 'entry_id' in views_src
    assert 'heating_curve.svg' in views_src


if __name__ == "__main__":
    test_conflict_matrix()
    test_legacy_entry_defaults_foxair()
    test_device_names_carry_prefix_and_slave()
    test_translation_key_stable_and_object_id_prefixed()
    test_reconfigure_strings_all_langs()
    test_diagnostics_exposes_prefix()
    test_views_require_entry_id()
    test_views_list_entries_no_entry_id()
    print("All tests passed!")
