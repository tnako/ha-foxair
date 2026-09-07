#!/usr/bin/env python3
"""Offline tests for const.bind_device_info (no HA installed).

HA deprecated DeviceInfo via_device (removal 2027.8): sub-devices must
link by registry id. bind_device_info resolves identifiers -> id and
falls back to the unmodified info when hass/lookup is unavailable.

Run: pytest tests/test_device_bind.py -v
"""
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _stub_modules(with_registry=True):
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
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.helpers"] = ha.helpers
    sys.modules["homeassistant.helpers.entity"] = ha.helpers.entity
    if with_registry:
        dr = types.ModuleType("homeassistant.helpers.device_registry")

        class FakeDevice:
            id = "main-dev-id"

        class FakeReg:
            def __init__(self):
                self.seen = None

            def async_get_device_by_identifier(self, identifier, config_entry_id):
                self.seen = (identifier, config_entry_id)
                return FakeDevice()

        reg = FakeReg()
        dr.async_get = lambda hass: reg
        sys.modules["homeassistant.helpers.device_registry"] = dr
        return reg
    sys.modules.pop("homeassistant.helpers.device_registry", None)
    return None


def _load_const():
    for m in [m for m in list(sys.modules) if m.startswith("foxpkgbind")]:
        del sys.modules[m]
    _stub_modules(with_registry=True)
    pkg = types.ModuleType("foxpkgbind")
    pkg.__path__ = []
    sys.modules["foxpkgbind"] = pkg
    src = (CC / "const.py").read_text().replace(
        "from .const import", "from foxpkgbind.const import")
    mod = types.ModuleType("foxpkgbind.const")
    mod.__dict__["__file__"] = str(CC / "const.py")
    sys.modules["foxpkgbind.const"] = mod
    exec(compile(src, str(CC / "const.py"), "exec"), mod.__dict__)
    return mod


const = _load_const()


def test_sub_device_binds_to_registry_id():
    info = const.device_for_block("T", "eid", "T_Live", "foxair", 1, "h", 502)
    assert info.get("via_device") == ("foxair", "eid")
    bound = const.bind_device_info(object(), "eid", info)
    assert bound.get("via_device_id") == "main-dev-id"
    assert "via_device" not in bound  # deprecated param gone

def test_main_device_untouched():
    info = const.main_device("eid", "foxair", 1, "h", 502)
    assert const.bind_device_info(object(), "eid", info) == info


def test_fallbacks_keep_unmodified_info():
    info = const.device_for_block("T", "eid", "T_Live", "foxair", 1, "h", 502)
    assert const.bind_device_info(None, "eid", info) == info  # no hass (tests/tools)
    assert const.bind_device_info(object(), None, info) == info  # no entry
    _stub_modules(with_registry=False)  # device_registry unimportable
    assert const.bind_device_info(object(), "eid", info) == info
