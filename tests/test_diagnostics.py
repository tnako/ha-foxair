#!/usr/bin/env python3
"""Offline diagnostics tests (no HA installed).

Regression: diagnostics must include key addrs (H31 pump type 1041,
power/COP/flow sources, firmware, curve) even when the normal poll cycle
missed them, and must never cap the register dump.
"""
import asyncio
import json
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _stub_modules():
    ha = types.ModuleType("homeassistant")
    ha.core = types.ModuleType("homeassistant.core")
    ha.core.HomeAssistant = object
    ha.config_entries = types.ModuleType("homeassistant.config_entries")
    ha.config_entries.ConfigEntry = object
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha.core
    sys.modules["homeassistant.config_entries"] = ha.config_entries


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_stub_modules()
diag = _load("foxair_diag_test", CC / "diagnostics.py")


MARKERS = json.loads((CC / "data/foxair_config.json").read_text(encoding="utf-8"))["markers"]


class FakeEntry:
    def __init__(self, coord):
        self.entry_id = "e1"
        self.options = {}
        self.data = {"host": "h", "port": 502, "slave": 1}
        self.runtime_data = coord


class FakeHass:
    def __init__(self, coord):
        self._coord = coord
        self.states = types.SimpleNamespace(get=lambda _eid: None)


class FakeCoord:
    def __init__(self, data):
        self.data = data
        self.stats = {}
        self.fetched = None

    def marker(self, name):
        return MARKERS.get(name, {})

    async def _fetch_addrs(self, addrs):
        self.fetched = set(addrs)
        # Simulate the device answering H31 + power regs live.
        return {a: {"raw": 2, "value": 2.0, "info": {"code": "X", "type": "RAW"}}
                for a in addrs}


def test_key_addrs_fetched_when_missing():
    coord = FakeCoord({1011: {"raw": 1, "value": 1.0, "info": {}}})
    out = asyncio.run(diag.async_get_config_entry_diagnostics(
        FakeHass(coord), FakeEntry(coord)))
    assert 1041 in coord.fetched  # H31 pump type requested live
    assert "1041" in out["registers"]
    assert out["key_fetch"]["still_missing"] == []
    cs = MARKERS["control_source"]
    assert cs["addr_single"]["selector"] in coord.fetched
    assert all(src["current"] in coord.fetched for src in cs["by_value"].values())
    # Written back so computed sensors / entities see them too.
    assert 1041 in coord.data


def test_no_fetch_when_all_present():
    probe = FakeCoord({})
    asyncio.run(diag.async_get_config_entry_diagnostics(FakeHass(probe), FakeEntry(probe)))
    data = {a: {"raw": 1, "value": 1.0, "info": {}} for a in probe.fetched}
    coord = FakeCoord(data)
    out = asyncio.run(diag.async_get_config_entry_diagnostics(
        FakeHass(coord), FakeEntry(coord)))
    assert coord.fetched is None
    assert out["key_fetch"] == {"requested": [], "still_missing": []}


def test_no_register_cap():
    data = {a: {"raw": 1, "value": 1.0, "info": {}} for a in range(1, 400)}
    coord = FakeCoord(data)
    out = asyncio.run(diag.async_get_config_entry_diagnostics(
        FakeHass(coord), FakeEntry(coord)))
    assert len(out["registers"]) >= 399
