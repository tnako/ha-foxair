"""Findings, the one next step and the status text shared by the sensor, the button and the LLM tool."""
from __future__ import annotations

import statistics

from .efficiency_history import DAILY_MIN_DAYS, qualifying_daily
from .efficiency_model import (COMPARE_MIN_DAYS, DAY_S, F_FAN, F_FP, F_SH, F_T, QUALIFY_DAY_BUCKETS, corr,
                               fingerprint, qualifying_days, ratios)

HINT_WINDOW_S = 7 * DAY_S
SH_OFF_TARGET_K = 1.5
SH_CORR_LIMIT = -0.3
SH_CORR_MIN_N = 100
SHORT_CYCLE_STARTS = 24
SHORT_CYCLE_AVG_RUN_S = 1200
COMPARE_MAX_DAYS = 10
MIN_HOLD_S = DAY_S
DEMAND_WINDOW_S = 2 * DAY_S
DIRECTION_MIN_N = 30
DIRECTION_CORR = 0.1
DAILY_MAX_DAYS = 14
DEFROST_MIN_EVENTS = 6
DEFROST_TIMER_SLACK_S = 600
DEFROST_SHORT_S = 240
DEFROST_TIMER_SHARE = 0.5
FAN_CAP_MARGIN = 5.0
FAN_CAP_SHARE = 0.2
FLOW_HIGHER_K = 3.0
FLOW_CLEAR_K = 2.5

LADDER = {
    "E02": {"step": 0.5, "min": 3.0, "max": 6.0, "metric": "steady", "dirs": (-1, 1)},
}
DAILY_PREFIXES = ("D", "P", "C", "A", "H")
STATES = ["learning", "waiting_for_heating", "suggestion", "testing", "no_change", "problem"]


def metric_for(param: str | None) -> str:
    if param in LADDER:
        return LADDER[param]["metric"]
    return "daily" if param and param.startswith(DAILY_PREFIXES) else "steady"


def fan_cap_share(buckets: list[list], fan_max: float | None, now: float) -> float | None:
    """Share of recent steady buckets whose fan target sits at the configured maximum."""
    if fan_max is None:
        return None
    win = [b for b in buckets if now - b[F_T] <= HINT_WINDOW_S and len(b) > F_FAN and b[F_FAN] is not None]
    if not win:
        return None
    return sum(1 for b in win if b[F_FAN] >= fan_max - FAN_CAP_MARGIN) / len(win)


def defrost_summary(events: list[dict], now: float, d03_min: float | None = None, fp: str | None = None) -> dict:
    """Last-24 h count plus 7-day medians; on_timer_share = defrosts right after the D03 minimum."""
    day = [e for e in events if now - e["t"] <= DAY_S]
    week = [e for e in events if now - e["t"] <= HINT_WINDOW_S and (fp is None or e.get("fp") == fp)]
    out = {"count_24h": len(day), "count_7d": len(week), "median_duration_min": None,
           "median_heating_before_min": None, "on_timer_share": None}
    if week:
        out["median_duration_min"] = round(statistics.median(e["dur_s"] for e in week) / 60, 1)
    runs = [e["run_s"] for e in week if e.get("run_s") is not None]
    if runs:
        out["median_heating_before_min"] = round(statistics.median(runs) / 60, 1)
        if d03_min is not None:
            limit = d03_min * 60 + DEFROST_TIMER_SLACK_S
            out["on_timer_share"] = round(sum(1 for r in runs if r <= limit) / len(runs), 2)
    return out


def defrost_on_timer(summary: dict) -> bool:
    return (summary["count_7d"] >= DEFROST_MIN_EVENTS and summary["on_timer_share"] is not None
            and summary["on_timer_share"] >= DEFROST_TIMER_SHARE and summary["median_duration_min"] is not None
            and summary["median_duration_min"] * 60 <= DEFROST_SHORT_S)


def hints(model: dict | None, buckets: list[list], starts_24h: int, run_s_24h: float,
          sh_target: float | None, now: float, current: dict | None = None,
          defrosts: list[dict] | None = None, flow: dict | None = None, flow_was_higher: bool = False) -> list[str]:
    """Ordered findings for the recent window; the first one is the headline."""
    current = current or {}
    out = []
    if starts_24h >= SHORT_CYCLE_STARTS and run_s_24h / starts_24h < SHORT_CYCLE_AVG_RUN_S:
        out.append("short_cycling")
    if flow and flow["delta_k"] >= (FLOW_CLEAR_K if flow_was_higher else FLOW_HIGHER_K):
        out.append("flow_higher")
    if defrosts and defrost_on_timer(defrost_summary(defrosts, now, current.get("D03"))):
        out.append("defrost_on_timer")
    share = fan_cap_share(buckets, current.get("F26"), now)
    if share is not None and share >= FAN_CAP_SHARE:
        out.append("fan_at_max")
    if not model:
        return out or ["collecting"]
    win = [b for b in buckets if now - b[F_T] <= HINT_WINDOW_S and b[F_SH] is not None]
    if win and sh_target is not None:
        mean_sh = sum(b[F_SH] for b in win) / len(win)
        if abs(mean_sh - sh_target) > SH_OFF_TARGET_K:
            out.append("superheat_off_target")
    if len(win) >= SH_CORR_MIN_N:
        c = corr([b[F_SH] for b in win], [r for _, r in ratios(model, win)])
        if c is not None and c < SH_CORR_LIMIT:
            out.append("superheat_costs")
    return out or ["ok"]


def _only_diff(a: dict, b: dict) -> dict:
    return {k: v for k, v in a.items() if b.get(k) != v}


def due_at(advice: dict, now: float) -> tuple[float | None, bool]:
    """(timestamp, estimated) of the next automatic check; always in the future or None."""
    a = advice.get("action")
    if a in ("change", "revert", "accept"):
        return None, False
    t = advice.get("not_before")
    if t and t > now:
        return t, False
    days = 1 if advice.get("reason") == "inconclusive" else advice.get("days_left")
    if days and a in ("collecting", "keep", "wait_heating"):
        return (int(now // DAY_S) + int(days)) * DAY_S, True
    return None, False


def _fmt(v) -> str:
    return "?" if v is None else f"{v:g}" if isinstance(v, (int, float)) else str(v)


def summary(advice: dict, hint_list: list[str], flow: dict | None, group: str | None, now: float,
            autotest_msg: str | None = None) -> dict:
    """One state, one message and the one thing the Apply button does; shared by sensor, button and LLM."""
    a, p, f, t = advice.get("action"), advice.get("param"), advice.get("from"), advice.get("to")
    days, reason = advice.get("days_left"), advice.get("reason")
    testing = group not in (None, "baseline")
    own_test = p in LADDER
    apply = None
    if a == "change" or (a == "revert" and own_test):
        apply = {"kind": "write", "param": p, "from": f, "to": t}
    elif a in ("accept", "revert"):
        apply = {"kind": "baseline"}
    if a == "change":
        state, msg = "suggestion", (f"Press Apply to set {p} from {_fmt(f)} to {_fmt(t)}. Keep it {days} heating "
                                    f"days, the result is judged automatically.")
    elif a == "revert" and own_test:
        state, msg = "suggestion", (f"{p}={_fmt(f)} showed no gain ({reason}). "
                                    f"Press Apply to set it back to {_fmt(t)}.")
    elif a == "revert":
        word = "worse" if reason == "worse" else "no clear difference"
        state, msg = "suggestion", (f"Result for {group}: COP {_fmt(advice.get('delta_pct'))} % against the "
                                    f"reference ({word}). Press Apply to make the current settings the new "
                                    f"reference; nothing is written to the pump.")
    elif a == "accept":
        what = f"{p}={_fmt(t)}" if p else f"Settings {group}"
        state, msg = "suggestion", (f"{what} is better ({_fmt(advice.get('delta_pct'))} %). Press Apply to keep "
                                    f"it as the new reference.")
    elif a == "check_curve":
        state, msg = "problem", "Short cycling: fix the heating curve or hysteresis first."
    elif a == "autotest":
        state, msg = "testing", autotest_msg or "Autotest running."
    elif a == "wait_heating" and testing:
        state, msg = "waiting_for_heating", f"Testing {group}: waiting for heating, {days} more heating day(s) needed."
    elif a == "wait_heating":
        nxt = f" Then {p} {_fmt(f)} -> {_fmt(t)} is tested." if p and t is not None else ""
        state, msg = "waiting_for_heating", f"Waiting for heating (about 1 h of steady heating a day).{nxt}"
    elif a == "keep" and reason == "settling_after_change":
        state = "testing" if testing else "learning"
        what = f"Testing {group}" if testing else "Settings changed"
        msg = f"{what}: measuring starts after a 24 h settling time."
    elif a == "keep" and reason == "inconclusive":
        state = "testing"
        msg = (f"Testing {group}: COP {_fmt(advice.get('delta_pct'))} % ± {_fmt(advice.get('ci95_pct'))} % against "
               f"the reference, not clear yet. Checked after every heating day, decided within {days} heating "
               f"day(s) at the latest.")
    elif a == "keep" and own_test:
        state, msg = "testing", f"Testing {group}: {days} more heating day(s) needed."
    elif a == "keep":
        state, msg = "testing", f"Measuring {group} against the reference: {days} more heating day(s) needed."
    elif a == "collecting":
        state, msg = "learning", f"Learning how the pump performs: {days} more heating day(s) needed."
    elif a == "done":
        state, msg = "no_change", "No setting change to suggest. Checks continue automatically."
    else:
        state, msg = "learning", "Reading the settings from the pump."
    if "flow_higher" in hint_list and flow:
        prob = (f"Flow is {flow['delta_k']:g} K warmer than on earlier days at the same outdoor temperature "
                f"(COP {flow['cop_pct']:+g} %). Check the heating curve and setpoint.")
        msg = f"{prob} Also: {msg}"
        state = "problem"
    when, est = due_at(advice, now)
    return {"state": state, "message": msg, "apply": apply, "next_check": when, "estimated": est,
            "days_left": days, "reason": reason, "findings": list(hint_list)}


def _step(param: str, value: float, direction: int) -> float | None:
    lad = LADDER[param]
    if not lad["min"] <= value <= lad["max"]:
        return None
    new = round(min(max(value + direction * lad["step"], lad["min"]), lad["max"]), 1)
    return None if new == round(value, 1) else new


def suggestion_policy(tracked) -> dict:
    """What the advisor may propose (from LADDER) and which tracked settings it only watches."""
    return {"may_suggest": {p: {"step": l["step"], "min": l["min"], "max": l["max"], "metric": l["metric"],
                                "directions": ["down" if d < 0 else "up" for d in l["dirs"]]}
                            for p, l in LADDER.items()},
            "watch_only": sorted(p for p in tracked if p not in LADDER),
            "writes_to_device": "only_when_apply_is_pressed_or_autotest_is_on",
            "autotest_writes": ["E02"]}


def _direction_from_data(model: dict | None, buckets: list[list], sh_target: float | None) -> tuple[int, str]:
    """-1 = lower the superheat target, +1 = raise it; with the evidence used."""
    win = [b for b in buckets if b[F_SH] is not None]
    if model and len(win) >= DIRECTION_MIN_N:
        c = corr([b[F_SH] for b in win], [r for _, r in ratios(model, win)])
        if c is not None and abs(c) >= DIRECTION_CORR:
            return (-1, "cop_falls_with_superheat") if c < 0 else (1, "cop_rises_with_superheat")
    if win and sh_target is not None:
        mean_sh = sum(b[F_SH] for b in win) / len(win)
        return (-1, "superheat_above_target") if mean_sh >= sh_target else (1, "superheat_below_target")
    return -1, "default"


def _candidate_dirs(param: str, *, model, base_buckets, sh_target) -> tuple[list[int], str] | None:
    """Directions worth testing for one ladder parameter now, or None when its precondition fails."""
    if param != "E02" or model is None:
        return None
    d, why = _direction_from_data(model, base_buckets, sh_target)
    return [d, -d], why


def advise(*, buckets: list[list], groups: dict, settings: dict, current: dict, baseline_fp: str | None,
           changes: list[dict], model: dict | None, hint_list: list[str], sh_target: float | None,
           now: float, day_rows: list[dict] | None = None, day_groups: dict | None = None,
           day_model: dict | None = None, defrosts: list[dict] | None = None, skip=()) -> dict:
    """Next step for the user: what to change, to which value, and not before when; `skip` = params owned elsewhere."""
    day_rows, day_groups, defrosts = day_rows or [], day_groups or {}, defrosts or []
    out = {"action": "none", "param": None, "from": None, "to": None, "not_before": None,
           "days_left": None, "reason": None, "metric": None}
    if not current or baseline_fp is None:
        return {**out, "reason": "settings_unknown"}
    fp = fingerprint(current)
    base = settings.get(baseline_fp, {})
    recent = sum(1 for b in buckets if now - b[F_T] <= DEMAND_WINDOW_S)
    heating = recent >= QUALIFY_DAY_BUCKETS
    if "short_cycling" in hint_list:
        return {**out, "action": "check_curve", "reason": "short_cycling"}
    last = changes[-1] if changes else None
    if last and now - last["t"] < MIN_HOLD_S:
        return {**out, "action": "keep", "not_before": last["t"] + MIN_HOLD_S, "reason": "settling_after_change"}

    if fp != baseline_fp:
        diff = _only_diff(current, base)
        param = next(iter(diff)) if len(diff) == 1 else None
        metric = metric_for(param)
        if metric == "daily":
            st = day_groups.get(fp) or {"days": 0, "verdict": "collecting"}
            days, min_days, max_days = qualifying_daily(day_rows, fp), DAILY_MIN_DAYS, DAILY_MAX_DAYS
        else:
            st = groups.get(fp) or {"days": 0, "verdict": "collecting"}
            days, min_days, max_days = qualifying_days(buckets, fp), COMPARE_MIN_DAYS, COMPARE_MAX_DAYS
        res = {"delta_pct": st.get("delta_pct"), "ci95_pct": st.get("ci95_pct"), "metric": metric}
        info = {"param": param, "from": current.get(param) if param else None,
                "to": base.get(param) if param else None}
        if st["verdict"] == "better":
            return {**out, **res, "action": "accept", "param": param, "from": base.get(param) if param else None,
                    "to": current.get(param) if param else None, "reason": "better"}
        if st["verdict"] == "worse":
            return {**out, **res, **info, "action": "revert", "reason": "worse"}
        if days >= max_days:
            return {**out, **res, **info, "action": "revert", "reason": "no_clear_gain"}
        if days >= min_days:
            return {**out, **res, **info, "action": "keep" if heating else "wait_heating",
                    "days_left": max_days - days, "reason": "inconclusive" if heating else "no_heating"}
        return {**out, **res, **info, "action": "keep" if heating else "wait_heating", "days_left": min_days - days,
                "reason": "need_more_days" if heating else "no_heating"}

    base_buckets = [b for b in buckets if b[F_FP] == baseline_fp]
    if model is None or qualifying_days(buckets, baseline_fp) < COMPARE_MIN_DAYS:
        return {**out, "action": "collecting" if heating else "wait_heating",
                "days_left": max(COMPARE_MIN_DAYS - qualifying_days(buckets, baseline_fp), 1),
                "reason": "baseline_needs_days" if heating else "no_heating"}
    for param, lad in LADDER.items():
        if param not in current or param in skip:
            continue
        cand = _candidate_dirs(param, model=model, base_buckets=base_buckets, sh_target=sh_target)
        if cand is None:
            continue
        dirs, why = cand
        pool = day_groups if lad["metric"] == "daily" else groups
        tried = {}
        for gfp, st in pool.items():
            d = _only_diff(settings.get(gfp, {}), base)
            if set(d) == {param} and st.get("verdict") in ("worse", "inconclusive", "better"):
                tried[1 if d[param] > current[param] else -1] = st["verdict"]
        for dirn in dirs:
            if dirn in tried or dirn not in lad["dirs"]:
                continue
            new = _step(param, current[param], dirn)
            if new is None:
                continue
            days = COMPARE_MIN_DAYS if lad["metric"] == "steady" else DAILY_MIN_DAYS
            if not heating:
                return {**out, "action": "wait_heating", "param": param, "from": current[param], "to": new,
                        "reason": "no_heating", "metric": lad["metric"]}
            return {**out, "action": "change", "param": param, "from": current[param], "to": new,
                    "since": now, "days_left": days, "metric": lad["metric"],
                    "reason": why if dirn == dirs[0] else "other_direction_tried"}
    return {**out, "action": "done", "reason": "no_candidate"}
