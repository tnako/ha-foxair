#!/usr/bin/env python3
"""Daily history from recorder statistics: full load, hourly top-up, failure stays visible, options pick entities."""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
import zoneinfo
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"
PKG = "foxair_history_pkg"
BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")
CALLS: list = []
FAIL = {"on": False}


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _hourly_rows(start, end, ids):
    out = {sid: [] for sid in ids}
    t = int(start.timestamp())
    while t < end.timestamp():
        for sid in ids:
            key = "change" if "energy" in sid or "meter" in sid else "mean"
            out[sid].append({"start": float(t), key: 0.5 if key == "change" else 10.0})
        t += 3600
    return out


def statistics_during_period(hass, start, end, ids, period, units, types_):
    CALLS.append((start, end, set(ids), period, units, set(types_)))
    if FAIL["on"]:
        raise RuntimeError("database is locked")
    return _hourly_rows(start, end, ids)


class Recorder:
    async def async_add_executor_job(self, fn, *a):
        return fn(*a)


_mod("homeassistant")
_mod("homeassistant.components")
_mod("homeassistant.components.recorder", get_instance=lambda hass: Recorder())
_mod("homeassistant.components.recorder.statistics", statistics_during_period=statistics_during_period)
_mod("homeassistant.util")
_mod("homeassistant.util.dt", get_default_time_zone=lambda: BERLIN,
     start_of_local_day=lambda d: datetime.combine(d.astimezone(BERLIN).date(), datetime.min.time(), BERLIN))
sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]
_mod(PKG).__path__ = [str(CC)]
_mod(f"{PKG}.const", get_slave_id=lambda e: 1)
for _n in ("efficiency_model", "efficiency_history", "efficiency_advisor", "efficiency"):
    _load(_n)
rt = _load("efficiency_runtime")


class Store:
    async def async_load(self):
        return None

    async def async_save(self, data):
        pass

    def async_delay_save(self, fn, delay):
        pass


class Hass:
    async def async_add_executor_job(self, fn, *a):
        return fn(*a)

    def async_create_task(self, coro):
        coro.close()


def _runtime(opts=None):
    coord = types.SimpleNamespace(data={}, entry=types.SimpleNamespace(data={"name_prefix": "fox"}, options=opts or {}),
                                  async_update_listeners=lambda: None)
    return rt.EfficiencyRuntime(Hass(), coord, Store())


def test_first_load_reads_400_local_days_then_tops_up_two():
    CALLS.clear()
    r = _runtime()
    asyncio.run(r.async_load_history())
    start, end, ids, period, units, types_ = CALLS[-1]
    assert period == "hour" and types_ == {"change", "mean"} and units == {"energy": "kWh", "temperature": "°C"}
    assert ids == {"sensor.fox_energy_electrical", "sensor.fox_energy_heating", "sensor.fox_energy_dhw",
                   "sensor.fox_energy_defrost", "sensor.fox_energy_cooling", "sensor.fox_t04", "sensor.fox_t02"}
    assert 399 <= (end - start).days <= 401 and start.astimezone(BERLIN).hour == 0
    n = len(r.analyser.days)
    assert n == 400 and r.history_error is None and r.analyser.history_tz is BERLIN
    asyncio.run(r.async_load_history())
    start, end = CALLS[-1][:2]
    assert 2 <= (end - start).total_seconds() / 86400 <= 3 and start.astimezone(BERLIN).hour == 0
    assert len(r.analyser.days) == n


def test_options_choose_the_meter_and_room_sensors():
    CALLS.clear()
    r = _runtime({"history_energy_entity": "sensor.meter10_energy", "history_outdoor_entity": "sensor.outside",
                  "history_indoor_entity": "sensor.room"})
    asyncio.run(r.async_load_history())
    ids = CALLS[-1][2]
    assert {"sensor.meter10_energy", "sensor.outside", "sensor.room"} <= ids
    assert not ids & {"sensor.fox_energy_electrical", "sensor.fox_t04"}
    assert r.analyser.history_sources["t_in"] == "sensor.room"


def test_a_recorder_failure_keeps_the_old_days_and_reports_why():
    r = _runtime()
    asyncio.run(r.async_load_history())
    before = list(r.analyser.days)
    FAIL["on"] = True
    try:
        asyncio.run(r.async_load_history())
    finally:
        FAIL["on"] = False
    assert r.analyser.days == before and r.history_error == "RuntimeError: database is locked"
    asyncio.run(r.async_load_history())
    assert r.history_error is None


def test_days_survive_a_restart_because_they_come_from_the_recorder():
    a = _runtime()
    asyncio.run(a.async_load_history())
    b = _runtime()
    b.analyser = rt.EfficiencyAnalyser(a.analyser.to_dict(datetime.now(timezone.utc).timestamp()))
    assert b.analyser.days == []
    asyncio.run(b.async_load_history())
    assert b.analyser.days == a.analyser.days
