#!/usr/bin/env python3
"""FoxNumber mode-dependent name (metadata name_by_dep_value).

1235 is the linear offset with H36 = 1 and the 0 degC point of the 7-point
curve with H36 = 2: the translation key follows H36 and HA's cached name is
dropped so the new name is written. Loads number.py with minimal HA stubs.

Run: pytest tests/test_number_name_variant.py -v
"""
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"
META = json.loads((CC / "data/foxair_metadata.json").read_text())
EN = json.loads((CC / "translations/en.json").read_text(encoding="utf-8"))


def _load_number():
    mods = {n: types.ModuleType(n) for n in (
        "homeassistant", "homeassistant.components", "homeassistant.components.number",
        "homeassistant.helpers", "homeassistant.helpers.entity", "homeassistant.helpers.update_coordinator",
        "foxair_number_pkg", "foxair_number_pkg.const")}

    class CoordinatorEntity:
        updates = 0

        def __init__(self, coord):
            self.coordinator = coord

        def _handle_coordinator_update(self):
            type(self).updates += 1

    mods["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntity
    mods["homeassistant.components.number"].NumberEntity = type("NumberEntity", (), {})
    mods["homeassistant.components.number"].NumberMode = types.SimpleNamespace(SLIDER="slider", BOX="box")
    mods["homeassistant.components.number"].NumberDeviceClass = type(
        "NumberDeviceClass", (), {"__getattr__": lambda self, k: k.lower()})()
    mods["homeassistant.helpers.entity"].EntityCategory = types.SimpleNamespace(CONFIG="config", DIAGNOSTIC="diagnostic")
    fconst = mods["foxair_number_pkg.const"]
    for name in ("device_for_addr", "entity_sort_key", "get_slave_id", "bind_device_info"):
        setattr(fconst, name, lambda *a, **k: None)
    fconst.get_device_prefix = lambda entry: "foxair"
    fconst.entity_suffix = lambda coord, addr: str(addr)
    fconst.dependency_met = lambda coord, meta, missing=False: True
    fconst.POPULAR_ADDRS = set()
    sys.modules.update(mods)
    src = (CC / "number.py").read_text().replace("from .", "from foxair_number_pkg.")
    mod = types.ModuleType("foxair_number_pkg.number")
    exec(compile(src, str(CC / "number.py"), "exec"), mod.__dict__)
    return mod


number = _load_number()


def _coord(h36):
    return types.SimpleNamespace(
        data={1236: {"raw": h36, "value": h36}} if h36 is not None else {},
        entry=types.SimpleNamespace(data={}, options={}),
        marker=lambda name: {},
    )


def test_1235_name_follows_h36():
    coord = _coord(1)
    ent = number.FoxNumber(coord, 1235, META["1235"])
    assert ent._attr_translation_key == "foxair_1235_linear"
    ent.__dict__["name"] = "cached by HA"
    coord.data[1236] = {"raw": 2, "value": 2}
    ent._handle_coordinator_update()
    assert ent._attr_translation_key == "foxair_1235_points"
    assert "name" not in ent.__dict__
    assert EN["entity"]["number"][ent._attr_translation_key]["name"] == "Point 0 °C"
    coord.data[1236] = {"raw": 0, "value": 0}
    ent._handle_coordinator_update()
    assert ent._attr_translation_key == "foxair_1235"


def test_unknown_mode_keeps_base_key_and_other_numbers_untouched():
    assert number.FoxNumber(_coord(None), 1235, META["1235"])._attr_translation_key == "foxair_1235"
    assert number.FoxNumber(_coord(2), 1250, META["1250"])._attr_translation_key == "foxair_1250"
