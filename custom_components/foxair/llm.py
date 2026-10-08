"""Read-only LLM tool (Assist API / MCP) with the efficiency analyser report."""

from __future__ import annotations

from datetime import datetime, timezone

import probatio

from homeassistant.components.homeassistant import async_should_expose
from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, Tool, ToolAnnotations, ToolInput, ToolResult

from .const import DOMAIN, get_slave_id
from .efficiency import suggestion_policy
from .efficiency_runtime import SETTING_ADDRS

LIVE_KEYS = {"t30": "compressor_hz", "t04": "outdoor_c", "t02": "flow_c", "t01": "return_c", "t03": "evaporator_c",
             "heating_power": "heat_w", "electrical_power": "electrical_w", "cop": "cop"}


def _iso(ts):
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="minutes")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _prefix(entry) -> str:
    return str((entry.data or {}).get("name_prefix", "foxair") or "foxair")


def _units(hass: HomeAssistant) -> list:
    return [e for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if getattr(e.runtime_data, "efficiency", None) is not None]


def build_report(hass: HomeAssistant, entry) -> dict:
    from .sensor import _advice_message

    an = entry.runtime_data.efficiency.analyser
    prefix = _prefix(entry)
    live = {}
    for key, name in LIVE_KEYS.items():
        st = hass.states.get(f"sensor.{prefix}_{key}")
        live[name] = _num(st.state) if st else None
    adv = dict(an.advice)
    if "not_before" in adv:
        adv["not_before"] = _iso(adv["not_before"])
    day = an.last_day()
    if day:
        day = {**day, "day": str(_iso(day["day"] * 86400))[:10], "fp": an.describe(day["fp"])}
    return {
        "unit": {"name": entry.title, "prefix": prefix, "slave": get_slave_id(entry)},
        "live": live,
        "next_step": {**adv, "message": _advice_message(an.advice)},
        "findings": list(an.hint_list),
        "superheat_target": an.sh_target,
        "settings_group": an.describe(an.current_fp()) if an.current else None,
        "is_baseline": bool(an.current) and an.current_fp() == an.baseline_fp,
        "current_settings": dict(an.current),
        "index_pct_24h": (an.recent or {}).get("index_pct"),
        "buckets": len(an.buckets),
        "days_recorded": len(an.days),
        "last_day": day,
        "groups": {an.describe(fp): g for fp, g in an.groups.items()},
        "daily_groups": {an.describe(fp): g for fp, g in an.day_groups.items()},
        "model_fit_error_pct": (an.model or {}).get("mape_pct"),
        "recent_changes": [{**c, "t": _iso(c.get("t")),
                            "from": an.describe(c["from"]) if c.get("from") else None,
                            "to": an.describe(c["to"]) if c.get("to") else None}
                           for c in an.changes[-10:]],
        "suggestion_policy": suggestion_policy(SETTING_ADDRS),
    }


def _matches(entry, unit: str) -> bool:
    u = unit.strip().lower()
    return u in (_prefix(entry).lower(), (entry.title or "").lower(), str(get_slave_id(entry)), entry.entry_id.lower())


class GetEfficiencyReportTool(Tool):
    name = f"{DOMAIN}__GetEfficiencyReport"
    title = "Foxair efficiency report"
    description = ("Foxair heat pump efficiency analyser: live readings, next suggested settings step, findings, "
                   "COP per settings group, daily COP, recent setting changes and which settings the advisor may "
                   "suggest. Read-only. Without 'unit' all configured heat pumps are returned.")
    parameters = probatio.Schema({probatio.Optional("unit", description="Name prefix, title, Modbus slave id or "
                                                                        "config entry id of one heat pump"): str})
    annotations = ToolAnnotations(read_only=True, destructive=False, idempotent=True, open_world=False)
    integration = DOMAIN

    async def async_call(self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext) -> ToolResult:
        units = _units(hass)
        unit = tool_input.tool_args.get("unit")
        if unit:
            units = [e for e in units if _matches(e, unit)]
        if not units:
            known = [_prefix(e) for e in _units(hass)]
            return ToolResult(data={"error": "No matching Foxair unit with a running analyser", "units": known},
                              error=True)
        return ToolResult(data={"units": [build_report(hass, e) for e in units]})


@callback
def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
    if api_id != LLM_API_ASSIST or not llm_context.assistant:
        return None
    if not any(async_should_expose(hass, llm_context.assistant, f"climate.{_prefix(e)}_climate")
               for e in hass.config_entries.async_loaded_entries(DOMAIN)):
        return None
    return LLMTools(tools=[GetEfficiencyReportTool()])
