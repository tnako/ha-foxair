#!/usr/bin/env python3
"""E02 autotest: schedule, block scoring, analysis, stages, runtime writes, undo and the E02-only guard."""
from __future__ import annotations

import asyncio
import importlib.util
import math
import pathlib
import random
import sys
import types
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"
PKG = "foxair_autotest_pkg"
sys.modules.setdefault(PKG, types.ModuleType(PKG)).__path__ = [str(CC)]
const = types.ModuleType(f"{PKG}.const")
const.get_slave_id = lambda e: 1
sys.modules[f"{PKG}.const"] = const


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


at = _load("efficiency_autotest")
eff = _load("efficiency")
rt = _load("efficiency_runtime")
TZ = ZoneInfo("Europe/Berlin")
E02 = rt.SETTING_ADDRS["E02"]


def _ts(d: date, hour: float) -> float:
    return datetime.combine(d, datetime.min.time(), TZ).timestamp() + hour * 3600


def test_every_value_runs_once_a_day_and_in_every_slot_once_per_cycle():
    arms = list(at.COARSE)
    for seed in (1, 2, 99):
        days = [at.day_order(arms, seed, d) for d in range(8)]
        assert all(sorted(d) == arms for d in days)
        for cycle in (days[:4], days[4:]):
            for slot in range(4):
                assert sorted(day[slot] for day in cycle) == arms
    assert at.day_order(arms, 1, 0) == at.day_order(arms, 1, 0)


def test_slots_follow_local_time_across_the_dst_change():
    start = date(2026, 10, 24)
    day, slot, t0, t1 = at.slot_at(_ts(date(2026, 10, 25), 2.5), TZ, start, 4)
    assert (day, slot) == (1, 0) and t1 - t0 == 7 * 3600
    assert at.slot_at(_ts(date(2026, 10, 25), 23.5), TZ, start, 4)[:2] == (1, 3)
    assert at.slot_at(_ts(date(2026, 10, 26), 0.1), TZ, start, 4)[:2] == (2, 0)
    assert at.slot_at(_ts(date(2026, 10, 26), 13), TZ, start, 3)[:2] == (2, 1)


def _block(day, slot, arm, ratio, run_h=5.0):
    elec = 1000.0 * run_h
    ideal = elec * 10.0
    return {"day": day, "slot": slot, "arm": arm, "heat_wh": ideal * ratio, "elec_wh": elec, "elec_run_wh": elec,
            "ideal_wh": ideal, "run_s": run_h * 3600, "heater_s": 0.0, "dhw_s": 0.0, "cooling": False}


def _sim(effects: dict, days: int, sd: float, seed: int, slot_eff=(0.0, -0.06, -0.24, -0.05)):
    """Blocks drawn with the live noise level: per-day weather, per-slot level, 7.3 % block noise."""
    rng = random.Random(seed)
    arms = sorted(effects)
    out = []
    for d in range(days):
        w = rng.gauss(0, 0.05)
        for s, arm in enumerate(at.day_order(arms, seed, d)):
            r = 0.4 * math.exp(w + slot_eff[s] + math.log(1 + effects[arm]) + rng.gauss(0, sd))
            out.append(_block(d, s, arm, r))
    return out


def test_analysis_removes_day_and_slot_effects_and_finds_a_real_difference():
    eff_true = {3.0: -0.10, 4.0: 0.0, 5.0: 0.0, 6.0: 0.08}
    res = at.analyse(_sim(eff_true, 10, 0.01, 3), list(eff_true), 5.0)
    assert res[5.0]["delta_pct"] == 0.0
    assert abs(res[3.0]["delta_pct"] + 10) < 1.5 and abs(res[6.0]["delta_pct"] - 8) < 1.5
    assert at.pick(res, 5.0) == 6.0


def test_with_live_noise_no_difference_keeps_the_reference_most_of_the_time():
    flat = {a: 0.0 for a in at.COARSE}
    false_pick = sum(at.pick(at.analyse(_sim(flat, 10, 0.073, s), list(flat), 5.0), 5.0) != 5.0 for s in range(200))
    assert false_pick <= 0.15 * 200
    big = {3.0: 0.0, 4.0: 0.0, 5.0: 0.0, 6.0: 0.12}
    found = sum(at.pick(at.analyse(_sim(big, 10, 0.073, s), list(big), 5.0), 5.0) == 6.0 for s in range(200))
    assert found >= 0.7 * 200


def test_a_block_is_judged_only_with_enough_running_and_no_heater_or_cooling():
    good = _block(0, 0, 5.0, 0.4)
    assert at.block_score(good) == pytest.approx(math.log(0.4))
    assert at.block_score({**good, "run_s": 3600}) is None
    assert at.block_score({**good, "heater_s": 1200}) is None
    assert at.block_score({**good, "cooling": True}) is None


def _feed(t, start_day, e02, hours, step=60, p=1500.0, q=4500.0, running=True):
    """Polls for `hours`; returns new time. Pump holds the wanted E02 like a fast write would."""
    end = t + hours * 3600
    while t < end:
        want = t_.want(t, TZ)
        if want is not None and want != e02[0]:
            e02[0] = want
            t_.wrote(want, t)
        t_.observe(t, {"running": running, "p_day": p, "q_day": q, "t_flow": 35.0, "t_out": 5.0, "rs": 1,
                       "heater": False, "cooling": False}, TZ, e02[0])
        t += step
    return t


def test_stages_coarse_then_fine_then_finish_on_the_best_value():
    global t_
    t_ = at.Autotest()
    d0 = date(2026, 11, 2)
    t = _ts(d0, 9.5)
    t_.start(t, TZ, 5.5)
    assert t_.running and t_.arms == list(at.COARSE) and t_.ref == at.FACTORY and t_.start_value == 5.5
    e02 = [5.5]
    t = _feed(t, d0, e02, 24 * 11 + 1, step=120)
    assert t_.stage == "fine" and t_.coarse["ref"] == at.FACTORY
    assert t_.arms == [4.5, 5.0, 5.5] and t_.ref == 5.0
    t = _feed(t, d0, e02, 24 * 11, step=120)
    assert t_.stage == "done" and t_.result["value"] == 5.0
    assert e02[0] == 5.0 and t_.want(t, TZ) is None


def test_settling_hour_is_left_out_of_each_block():
    global t_
    t_ = at.Autotest()
    d0 = date(2026, 11, 2)
    t_.start(_ts(d0, 0), TZ, 5.0)
    e02 = [5.0]
    _feed(_ts(d0, 0), d0, e02, 6.5)
    first = t_.blocks[0]
    assert first["slot"] == 0 and first["run_s"] == pytest.approx(5 * 3600, abs=120)


def test_mixed_days_are_left_out():
    blocks = _sim({3.0: 0.0, 4.0: 0.0, 5.0: 0.0, 6.0: 0.0}, 4, 0.0, 1)
    blocks = [{**b, "heat_wh": b["heat_wh"] * (3 if b["day"] == 2 and b["arm"] == 6.0 else 1)} for b in blocks]
    assert at.analyse(blocks, list(at.COARSE), 5.0)[6.0]["delta_pct"] > 10
    assert at.analyse(blocks, list(at.COARSE), 5.0, skip_days=[2])[6.0]["delta_pct"] == pytest.approx(0, abs=0.1)


def test_stop_restores_the_start_value_and_survives_a_restart():
    a = at.Autotest()
    a.start(_ts(date(2026, 11, 2), 3), TZ, 5.5)
    a.stop("user", _ts(date(2026, 11, 2), 4))
    b = at.Autotest(a.to_dict())
    assert b.stage == "stopped" and b.want(0, TZ) == 5.5
    assert b.wrote(5.5, 1) is False and b.want(0, TZ) is None
    assert "set back to 5.5" in b.status(_ts(date(2026, 11, 2), 5), TZ)["message"]


class Coord:
    def __init__(self, e02=5.5, ok=True, expert=True):
        self.data = {a: {"value": 0.0} for a in rt.SETTING_ADDRS.values()}
        self.data[E02] = {"value": e02}
        self.entry = types.SimpleNamespace(data={}, options={"enable_expert": expert})
        self.writes, self._ok = [], ok
        self.async_update_listeners = lambda: None

    async def async_write_register(self, addr, value):
        self.writes.append((addr, value))
        if self._ok:
            self.data[addr] = {"value": value}
        return self._ok


class Store:
    async def async_save(self, data):
        self.saved = data

    def async_delay_save(self, fn, delay):
        pass


class Hass:
    def __init__(self):
        self.tasks = []

    async def async_add_executor_job(self, fn, *a):
        return fn(*a)

    def async_create_task(self, coro):
        if coro.__name__ == "_refresh":
            coro.close()
        else:
            self.tasks.append(coro)
        return types.SimpleNamespace(done=lambda: True)


def _runtime(coord):
    r = rt.EfficiencyRuntime(Hass(), coord, Store())
    r.tz = lambda: TZ
    r.analyser.update_settings(rt.settings_snapshot(coord), 0)
    r.analyser.set_baseline(0)
    r._fetched_once = True
    return r


def _drain(r):
    while r.hass.tasks:
        asyncio.run(r.hass.tasks.pop(0))


def test_the_only_writable_setting_is_e02_in_its_range():
    r = _runtime(Coord())
    for code in rt.SETTING_ADDRS:
        if code != "E02":
            with pytest.raises(ValueError, match="watch-only"):
                asyncio.run(r.async_write_setting(code, 1.0, "autotest"))
    for bad in (2.5, 6.5):
        with pytest.raises(ValueError, match="outside"):
            asyncio.run(r.async_write_setting("E02", bad, "autotest"))
    assert r.coord.writes == []
    src = (CC / "efficiency_runtime.py").read_text()
    assert src.count("async_write_register(") == 1


def test_autotest_needs_expert_mode():
    r = _runtime(Coord(expert=False))
    with pytest.raises(ValueError, match="expert mode"):
        asyncio.run(r.async_set_autotest(True))
    assert not r.analyser.autotest.running and r.coord.writes == []


def test_autotest_writes_e02_on_schedule_and_tags_the_change():
    c = Coord(e02=5.5)
    r = _runtime(c)
    asyncio.run(r.async_set_autotest(True))
    _drain(r)
    want = r.analyser.autotest.want(__import__("time").time(), TZ)
    assert c.writes == [(E02, want)]
    last = r.analyser.changes[-1]
    assert last["by"] == "autotest" and last["diff"] == {"E02": [5.5, want]}
    assert r.analyser.origin == {"E02": 5.5}
    assert {a for a, _ in c.writes} == {E02}


def test_hand_change_of_e02_stops_the_autotest_without_writing_back():
    c = Coord(e02=5.5)
    r = _runtime(c)
    asyncio.run(r.async_set_autotest(True))
    _drain(r)
    n = len(c.writes)
    c.data[E02] = {"value": 4.2}
    r._publish_settings()
    a = r.analyser.autotest
    assert a.stage == "stopped" and a.result["stopped"] == "manual_change" and a.want(0, TZ) is None
    assert len(c.writes) == n and "by" not in r.analyser.changes[-1]


def test_another_setting_changed_by_hand_marks_the_day_mixed_but_keeps_testing():
    c = Coord(e02=5.0)
    r = _runtime(c)
    asyncio.run(r.async_set_autotest(True))
    _drain(r)
    c.data[rt.SETTING_ADDRS["P11"]] = {"value": 4.0}
    r._publish_settings()
    assert r.analyser.autotest.running and r.analyser.autotest.mixed == [0]


def test_switching_off_writes_the_start_value_back():
    c = Coord(e02=5.5)
    r = _runtime(c)
    asyncio.run(r.async_set_autotest(True))
    _drain(r)
    asyncio.run(r.async_set_autotest(False))
    _drain(r)
    assert c.writes[-1] == (E02, 5.5) and c.data[E02]["value"] == 5.5
    assert r.analyser.autotest.want(0, TZ) is None


def test_a_failed_write_stops_and_reports_a_problem():
    c = Coord(e02=5.5, ok=False)
    r = _runtime(c)
    asyncio.run(r.async_set_autotest(True))
    _drain(r)
    st = r.analyser.status(__import__("time").time(), TZ)
    assert r.analyser.autotest.stage == "stopped" and st["state"] == "problem" and "failed" in st["message"]


def test_undo_writes_back_only_what_eef_changed_and_forgets_every_test():
    c = Coord(e02=5.5)
    r = _runtime(c)
    r.analyser.advice = {"action": "change", "param": "E02", "from": 5.5, "to": 6.0, "days_left": 3}
    assert asyncio.run(r.async_apply()) == "written"
    c.data[rt.SETTING_ADDRS["P11"]] = {"value": 4.0}
    r._publish_settings()
    r.analyser.buckets.append([0, 30, 5, 35, 3000, 700, 5, 100, r.analyser.current_fp(), None])
    assert r.analyser.undo_targets() == {"E02": (6.0, 5.5)}
    assert asyncio.run(r.async_undo()) == {"E02": (6.0, 5.5)}
    assert c.writes == [(E02, 6.0), (E02, 5.5)]
    a = r.analyser
    assert a.buckets == [] and a.origin == {} and a.autotest.stage is None and a.groups == {}
    assert [ch["kind"] for ch in a.changes] == ["reset"] and a.baseline_fp == a.current_fp()
    assert a.current["P11"] == 4.0


def test_undo_refuses_when_e02_moved_by_hand_after_eef():
    c = Coord(e02=5.5)
    r = _runtime(c)
    r.analyser.advice = {"action": "change", "param": "E02", "from": 5.5, "to": 6.0, "days_left": 3}
    asyncio.run(r.async_apply())
    c.data[E02] = {"value": 4.0}
    r._publish_settings()
    assert r.analyser.undo_targets() == {"E02": (4.0, 5.5)}
    assert asyncio.run(r.async_undo()) == {"E02": (4.0, 5.5)}
    assert c.writes[-1] == (E02, 5.5)


def test_origin_from_a_log_before_tracking_is_the_first_apply_shaped_e02_step():
    log = [{"t": 1, "kind": "change", "diff": {"P01": [0.0, 1.0]}},
           {"t": 2, "kind": "change", "diff": {"P11": [4.1, 3.6]}},
           {"t": 3, "kind": "baseline", "diff": None},
           {"t": 4, "kind": "change", "diff": {"E02": [5.5, 6.0]}}]
    assert at.legacy_origin(log) == {"E02": 5.5}
    assert at.legacy_origin([{"t": 1, "kind": "change", "diff": {"E02": [3.0, 5.0]}}]) == {}
    a = eff.EfficiencyAnalyser({"changes": log})
    assert a.origin == {"E02": 5.5}
    assert eff.EfficiencyAnalyser({"changes": log, "origin": {}}).origin == {}


def test_status_while_testing_names_the_value_and_the_block_end():
    a = eff.EfficiencyAnalyser()
    a.update_settings({"E02": 5.0}, 0)
    now = _ts(date(2026, 11, 2), 13)
    a.autotest.start(now, TZ, 5.0)
    a.refresh(now)
    st = a.status(now, TZ)
    v = a.autotest.want(now, TZ)
    assert st["state"] == "testing" and st["apply"] is None
    assert f"now E02={v:g} until 18:00" in st["message"] and st["next_check"] == _ts(date(2026, 11, 2), 18)
