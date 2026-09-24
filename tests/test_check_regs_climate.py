"""Offline test for tools/check_regs.py climate_wiring_rows (live H25 wiring check).

Fake HA states only; no network. Guards the check that would have caught the
2026-09 bug (H25 = inlet while the climate still showed outlet).
"""
import importlib.util
import json
import pathlib

import pytest

R = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_regs_climate", R / "tools/check_regs.py")
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)
META = json.loads(cr.META_PATH.read_text(encoding="utf-8"))
MARKERS = json.loads(cr.CONFIG_PATH.read_text(encoding="utf-8"))["markers"]
CS = MARKERS["control_source"]
SP = MARKERS["setpoints"]["addr_single"]
CURVE = MARKERS["heat_curve"]["addr_single"]["live_target"]


def _state(eid, state, **attrs):
    return eid, {"entity_id": eid, "state": state, "attributes": attrs}


def _code(addr):
    return META[str(addr)].get("code") or str(addr)


def _states(h25_key, climate_attrs):
    regs = {e["current"]: 20.0 + i for i, e in enumerate(CS["by_value"].values())}
    regs.update({SP["heating_target"]: 40.0, CURVE: 33.3})
    for e in CS["by_value"].values():
        if e.get("target"):
            regs[e["target"]] = 21.5
    items = [_state(f"sensor.foxair_{a}", str(v), friendly_name=f"{_code(a)}: reg") for a, v in regs.items()]
    sel = CS["addr_single"]["selector"]
    items.append(_state(f"select.foxair_sel_{sel}", h25_key, friendly_name=f"{_code(sel)}: select"))
    items.append(_state("climate.foxair_climate", "heat", raw_mode=1, **climate_attrs))
    return dict(items), regs


def _verdicts(rows):
    return {r["code"]: r["verdict"] for r in rows}


@pytest.mark.parametrize("raw", sorted(CS["by_value"]))
def test_wired_climate_passes(raw):
    src = CS["by_value"][raw]
    target = src.get("target") or SP["heating_target"]
    states, regs = _states(src["key"], {})
    states["climate.foxair_climate"]["attributes"].update(
        control_source=src["key"], current_addr=src["current"], target_addr=target,
        current_temperature=regs[src["current"]], temperature=regs[target],
        control_mode="fixed", mode_code="heating")
    rows = cr.climate_wiring_rows(states, META)
    assert set(_verdicts(rows).values()) == {"OK"}, rows


def test_climate_stuck_on_outlet_while_h25_inlet_is_flagged():
    inlet = next(e for e in CS["by_value"].values() if e["key"] == "inlet_water_temp")
    outlet = next(e for e in CS["by_value"].values() if e["key"] == "outlet_water_temp")
    states, regs = _states(inlet["key"], {})
    states["climate.foxair_climate"]["attributes"].update(
        control_source=outlet["key"], current_addr=outlet["current"], target_addr=SP["heating_target"],
        current_temperature=regs[outlet["current"]], temperature=40.0, control_mode="fixed", mode_code="heating")
    v = _verdicts(cr.climate_wiring_rows(states, META))
    assert v["CLIMATE:source"] == v["CLIMATE:current_addr"] == "MISMATCH"


def test_pre_fix_build_without_control_source_is_flagged():
    states, _ = _states("inlet_water_temp", {"current_temperature": 35.0, "temperature": 40.0})
    v = _verdicts(cr.climate_wiring_rows(states, META))
    assert v == {"CLIMATE:source": "MISMATCH"}


def test_curve_target_compared_with_live_curve_register():
    src = next(e for e in CS["by_value"].values() if not e.get("target"))
    states, regs = _states(src["key"], {})
    states["climate.foxair_climate"]["attributes"].update(
        control_source=src["key"], current_addr=src["current"], target_addr=SP["heating_target"],
        current_temperature=regs[src["current"]], temperature=33.3, control_mode="weather_curve", mode_code="heating")
    assert _verdicts(cr.climate_wiring_rows(states, META))["CLIMATE:target"] == "OK"
    states["climate.foxair_climate"]["attributes"]["temperature"] = 40.0
    assert _verdicts(cr.climate_wiring_rows(states, META))["CLIMATE:target"] == "MISMATCH"
