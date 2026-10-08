#!/usr/bin/env python3
"""Offline tests for the read-only LLM tool (llm.py) with stubbed HA modules."""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


@dataclass
class LLMTools:
    tools: list
    prompt: str | None = None


@dataclass
class ToolResult:
    data: dict
    error: bool = False


@dataclass(frozen=True)
class ToolAnnotations:
    read_only: bool = False
    destructive: bool = True
    idempotent: bool = False
    open_world: bool = True


@dataclass
class ToolInput:
    tool_name: str
    tool_args: dict = field(default_factory=dict)


EXPOSED = {"climate.foxair_climate"}


def _stub():
    _mod("homeassistant")
    _mod("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    _mod("homeassistant.components")
    _mod("homeassistant.components.homeassistant", async_should_expose=lambda hass, a, eid: eid in EXPOSED)
    _mod("homeassistant.components.llm", LLMTools=LLMTools)
    _mod("homeassistant.helpers")
    _mod("homeassistant.helpers.llm", LLM_API_ASSIST="assist", LLMContext=object, Tool=object,
         ToolAnnotations=ToolAnnotations, ToolInput=ToolInput, ToolResult=ToolResult)
    pkg = _mod("foxair_llm_pkg")
    pkg.__path__ = [str(CC)]
    _mod("foxair_llm_pkg.const", DOMAIN="foxair")

    def _advice_message(adv):
        return f"msg:{adv.get('action')}"
    _mod("foxair_llm_pkg.sensor", _advice_message=_advice_message)


_stub()
spec = importlib.util.spec_from_file_location("foxair_llm_pkg.llm", CC / "llm.py")
llm = importlib.util.module_from_spec(spec)
sys.modules["foxair_llm_pkg.llm"] = llm
spec.loader.exec_module(llm)


class FakeAnalyser:
    advice = {"action": "keep", "reason": "settling_after_change", "not_before": 86400.0, "days_left": 3}
    hint_list = ["ok"]
    sh_target = 5.0
    current = {"E02": 5.0, "F05": -4.0}
    baseline_fp = "fp1"
    recent = {"index_pct": 101.2}
    buckets = [1, 2, 3]
    days = [1]
    groups = {"fp1": {"days": 4, "verdict": "baseline"}}
    day_groups = {}
    model = {"mape_pct": 3.1}
    changes = [{"t": 0.0, "kind": "change", "from": "fp0", "to": "fp1", "diff": {"E02": [4.5, 5.0]}}]

    def current_fp(self):
        return "fp1"

    def describe(self, fp):
        return "baseline" if fp == "fp1" else f"G{fp}"

    def last_day(self):
        return {"day": 20370, "cop": 4.6, "fp": "fp1"}


def _hass(entries, states=None):
    states = states or {}
    return types.SimpleNamespace(
        states=types.SimpleNamespace(get=lambda eid: types.SimpleNamespace(state=states[eid]) if eid in states else None),
        config_entries=types.SimpleNamespace(async_loaded_entries=lambda d: entries if d == "foxair" else []))


def _entry(prefix="foxair", efficiency=True):
    coord = types.SimpleNamespace(efficiency=types.SimpleNamespace(analyser=FakeAnalyser()) if efficiency else None)
    e = types.SimpleNamespace(data={"name_prefix": prefix}, runtime_data=coord)
    coord.entry = e
    return e


CTX = types.SimpleNamespace(assistant="conversation")


def test_tool_offered_only_for_assist_with_exposed_climate():
    hass = _hass([_entry()])
    tools = llm.async_get_tools(hass, CTX, "assist")
    assert [t.name for t in tools.tools] == ["foxair__GetEfficiencyReport"]
    t = tools.tools[0]
    assert t.annotations.read_only and not t.annotations.destructive and not t.annotations.open_world
    assert llm.async_get_tools(hass, CTX, "other_api") is None
    assert llm.async_get_tools(hass, types.SimpleNamespace(assistant=None), "assist") is None
    assert llm.async_get_tools(_hass([_entry("other")]), CTX, "assist") is None


def test_report_content_is_readable():
    hass = _hass([_entry()], {"sensor.foxair_t30": "32.0", "sensor.foxair_cop": "unknown"})
    tool = llm.async_get_tools(hass, CTX, "assist").tools[0]
    res = asyncio.run(tool.async_call(hass, ToolInput(tool.name), CTX))
    r = res.data
    assert not res.error
    assert r["live"]["compressor_hz"] == 32.0 and r["live"]["cop"] is None and r["live"]["outdoor_c"] is None
    assert r["next_step"]["message"] == "msg:keep" and r["next_step"]["not_before"] == "1970-01-02T00:00+00:00"
    assert r["is_baseline"] and r["settings_group"] == "baseline" and r["current_settings"]["F05"] == -4.0
    assert r["last_day"]["day"] == "2025-10-09" and r["last_day"]["fp"] == "baseline"
    assert r["recent_changes"][0]["from"] == "Gfp0" and r["recent_changes"][0]["t"].startswith("1970-01-01")
    assert r["groups"] == {"baseline": {"days": 4, "verdict": "baseline"}}
    assert "F26 stays at 600" in r["rules"]


def test_report_error_when_analyser_missing_and_multi_unit():
    tool = llm.GetEfficiencyReportTool()
    res = asyncio.run(tool.async_call(_hass([_entry(efficiency=False)]), ToolInput(tool.name), CTX))
    assert res.error
    res = asyncio.run(tool.async_call(_hass([_entry(), _entry("pump2")]), ToolInput(tool.name), CTX))
    assert len(res.data["units"]) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
