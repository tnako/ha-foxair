"""Read-only LLM tool (Assist API / MCP) with the efficiency analyser report. Needs HA 2026.10+."""

from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

try:
    from homeassistant.components.homeassistant import async_should_expose
    from homeassistant.components.llm import LLMTools
    from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, Tool, ToolAnnotations, ToolInput, ToolResult
    HAS_LLM = True
except ImportError:
    HAS_LLM = False

LIVE_KEYS = {"t30": "compressor_hz", "t04": "outdoor_c", "t02": "flow_c", "t01": "return_c", "t03": "evaporator_c",
             "heating_power": "heat_w", "electrical_power": "electrical_w", "cop": "cop"}
RULES = "Suggestions only; the analyser never writes to the pump. F26 stays at 600 rpm. P11 and A40 are never suggested."


def _iso(ts):
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="minutes")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _prefix(entry) -> str:
    return str((entry.data or {}).get("name_prefix", "foxair") or "foxair")


def build_report(hass: HomeAssistant, coord) -> dict:
    from .sensor import _advice_message

    an = coord.efficiency.analyser
    prefix = _prefix(coord.entry)
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
        "rules": RULES,
    }


def _reports(hass: HomeAssistant) -> list[dict]:
    return [build_report(hass, e.runtime_data) for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if getattr(e.runtime_data, "efficiency", None) is not None]


if HAS_LLM:

    class GetEfficiencyReportTool(Tool):
        name = f"{DOMAIN}__GetEfficiencyReport"
        title = "Foxair efficiency report"
        description = ("Foxair heat pump efficiency analyser: live readings, next suggested settings step, findings, "
                       "COP comparison per settings group, daily COP and recent setting changes. Read-only.")
        annotations = ToolAnnotations(read_only=True, destructive=False, idempotent=True, open_world=False)
        integration = DOMAIN

        async def async_call(self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext) -> ToolResult:
            reports = _reports(hass)
            if not reports:
                return ToolResult(data={"error": "Foxair efficiency analyser is not running"}, error=True)
            return ToolResult(data=reports[0] if len(reports) == 1 else {"units": reports})

    @callback
    def async_get_tools(hass: HomeAssistant, llm_context: LLMContext, api_id: str) -> LLMTools | None:
        if api_id != LLM_API_ASSIST or not llm_context.assistant:
            return None
        if not any(async_should_expose(hass, llm_context.assistant, f"climate.{_prefix(e)}_climate")
                   for e in hass.config_entries.async_loaded_entries(DOMAIN)):
            return None
        return LLMTools(tools=[GetEfficiencyReportTool()])
