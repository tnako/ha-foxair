#!/usr/bin/env python3
"""V3.5 select options: H36 = 2 (7-point curve) and SG01 = 4 (AI Saving) only on firmware 3.5+.

Options gated by registry value_min_firmware are dropped from the select on older
firmware, and every offered option has a translated state in strings/en/de/ru.

Run: pytest tests/test_v35_select_options.py -v
"""
import json
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"
REGS = json.loads((CC / "data/foxair_phnix_registers.json").read_text(encoding="utf-8"))
META = json.loads((CC / "data/foxair_metadata.json").read_text(encoding="utf-8"))


def _load_select():
    ha = types.ModuleType("homeassistant")
    mods = {
        "homeassistant": ha,
        "homeassistant.components": types.ModuleType("homeassistant.components"),
        "homeassistant.components.select": types.ModuleType("homeassistant.components.select"),
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity": types.ModuleType("homeassistant.helpers.entity"),
        "homeassistant.helpers.update_coordinator": types.ModuleType("homeassistant.helpers.update_coordinator"),
        "foxair_select_pkg": types.ModuleType("foxair_select_pkg"),
        "foxair_select_pkg.const": types.ModuleType("foxair_select_pkg.const"),
    }
    mods["homeassistant.components.select"].SelectEntity = type("SelectEntity", (), {})
    mods["homeassistant.helpers.entity"].EntityCategory = types.SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic")
    mods["homeassistant.helpers.update_coordinator"].CoordinatorEntity = type("CoordinatorEntity", (), {})
    fconst = mods["foxair_select_pkg.const"]
    for name in ("device_for_addr", "entity_sort_key", "get_device_prefix", "get_slave_id", "bind_device_info", "entity_suffix"):
        setattr(fconst, name, lambda *a, **k: None)
    fconst.POPULAR_ADDRS = set()
    sys.modules.update(mods)
    src = (CC / "select.py").read_text().replace("from .", "from foxair_select_pkg.")
    mod = types.ModuleType("foxair_select_pkg.select")
    exec(compile(src, str(CC / "select.py"), "exec"), mod.__dict__)
    return mod


select = _load_select()


class FakeCoord:
    def __init__(self, fw):
        self.fw = fw
        self._regmap = REGS

    def _fw_gte(self, v):
        return self.fw >= v


def _options(addr, fw):
    rec = REGS[str(addr)]
    return select._firmware_filtered(FakeCoord(fw), addr,
                                     *select._build_option_maps(rec["value_map"], rec.get("app_values"), addr))


@pytest.mark.parametrize("fw,expected", [(34, ["fixed", "curve"]), (35, ["fixed", "curve", "points"])])
def test_h36_points_mode_needs_v35(fw, expected):
    opts, r2s, s2r = _options(1236, fw)
    assert opts == expected
    assert set(r2s.values()) == set(expected) == set(s2r)


@pytest.mark.parametrize("fw,has_ai", [(33, False), (34, False), (35, True)])
def test_sg01_ai_saving_needs_v35(fw, has_ai):
    opts, r2s, _ = _options(1334, fw)
    assert ("ai_saving" in opts) is has_ai
    assert (r2s.get("4") == "ai_saving") is has_ai
    assert "modbus_virtueller_sg_eingang" in opts


@pytest.mark.parametrize("addr", sorted(int(a) for a, r in REGS.items() if a.isdigit() and r.get("value_min_firmware")))
def test_gated_options_translated(addr):
    opts, _, _ = _options(addr, 99)
    code = META[str(addr)]["code"].lower() or str(addr)
    for lang in ("strings", "translations/en", "translations/de", "translations/ru"):
        states = json.loads((CC / f"{lang}.json").read_text(encoding="utf-8"))["entity"]["select"][f"foxair_{code}"]["state"]
        assert set(opts) <= set(states), (lang, sorted(set(opts) - set(states)))


def test_outdoor_sensor_select_translated():
    opts, _, _ = _options(1463, 35)
    assert opts == ["internal", "external"]
    for lang in ("strings", "translations/en", "translations/de", "translations/ru"):
        states = json.loads((CC / f"{lang}.json").read_text(encoding="utf-8"))["entity"]["select"]["foxair_1463"]["state"]
        assert set(opts) <= set(states), lang
