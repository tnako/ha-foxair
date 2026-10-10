#!/usr/bin/env python3
"""Apply button path: write the suggested value with read-back, or keep settings as the reference."""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pkg = types.ModuleType("foxair_apply_pkg")
pkg.__path__ = [str(CC)]
sys.modules["foxair_apply_pkg"] = pkg
const = types.ModuleType("foxair_apply_pkg.const")
const.get_slave_id = lambda e: 1
sys.modules["foxair_apply_pkg.const"] = const
eff = _load("foxair_apply_pkg.efficiency", CC / "efficiency.py")
rt = _load("foxair_apply_pkg.efficiency_runtime", CC / "efficiency_runtime.py")
E02 = rt.SETTING_ADDRS["E02"]


class Coord:
    def __init__(self, e02=5.0, readback=None, ok=True):
        self.data = {a: {"value": 0.0} for a in rt.SETTING_ADDRS.values()}
        self.data[E02] = {"value": e02}
        self.writes, self._readback, self._ok = [], readback, ok

    async def async_write_register(self, addr, value):
        self.writes.append((addr, value))
        self.data[addr] = {"value": value if self._readback is None else self._readback}
        return self._ok


class Store:
    async def async_save(self, data):
        self.saved = data

    def async_delay_save(self, fn, delay):
        pass


class Hass:
    async def async_add_executor_job(self, fn, *a):
        return fn(*a)

    def async_create_task(self, coro):
        coro.close()


def _runtime(coord, advice):
    r = rt.EfficiencyRuntime(Hass(), coord, Store())
    coord.async_update_listeners = lambda: None
    r.analyser.update_settings(rt.settings_snapshot(coord), 0)
    r.analyser.set_baseline(0)
    r.analyser.advice = advice
    r._fetched_once = True
    return r


CHANGE = {"action": "change", "param": "E02", "from": 5.0, "to": 5.5, "days_left": 3, "reason": "x"}


def test_apply_writes_the_suggested_value_and_logs_the_change():
    c = Coord()
    r = _runtime(c, dict(CHANGE))
    assert asyncio.run(r.async_apply()) == "written"
    assert c.writes == [(E02, 5.5)]
    assert r.analyser.current["E02"] == 5.5 and r.analyser.last_change()["diff"] == {"E02": [5.0, 5.5]}


def test_apply_refuses_when_the_pump_value_moved_meanwhile():
    c = Coord(e02=4.0)
    r = _runtime(c, dict(CHANGE))
    with pytest.raises(ValueError, match="expected 5.0"):
        asyncio.run(r.async_apply())
    assert c.writes == []


def test_apply_reports_a_failed_read_back():
    r = _runtime(Coord(readback=5.0), dict(CHANGE))
    with pytest.raises(ValueError, match="read back"):
        asyncio.run(r.async_apply())
    with pytest.raises(ValueError, match="failed or was blocked"):
        asyncio.run(_runtime(Coord(ok=False), dict(CHANGE)).async_apply())


def test_apply_without_a_suggestion_explains_why():
    c = Coord()
    r = _runtime(c, {"action": "collecting", "days_left": 2, "reason": "baseline_needs_days"})
    with pytest.raises(ValueError, match="Learning"):
        asyncio.run(r.async_apply())
    assert c.writes == []


def test_apply_accept_makes_the_current_settings_the_reference():
    c = Coord()
    r = _runtime(c, {"action": "accept", "param": "E02", "from": 5.0, "to": 5.0, "delta_pct": 2.0})
    c.data[E02] = {"value": 5.5}
    r._publish_settings()
    r.analyser.advice = {"action": "accept", "param": "E02", "from": 5.0, "to": 5.5, "delta_pct": 2.0}
    assert asyncio.run(r.async_apply()) == "baseline"
    assert r.analyser.baseline_fp == r.analyser.current_fp() and c.writes == []
