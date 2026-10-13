"""Daily rows from Home Assistant long-term statistics, the whole-day COP model and period comparisons."""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta, tzinfo

from .efficiency_model import _eta, _ridge, carnot_cop, day_stats, verdict

DAY_MIN_HEAT_KWH = 5.0
DAY_MIN_ELEC_KWH = 0.5
DAY_MIN_HOURS = 20
DAY_MAX_COOL_KWH = 0.1
DAY_FIT_MIN = 5
DAILY_MIN_DAYS = 5
HISTORY_DAYS = 400
WINDOW_DAYS = 30
YEAR_DAYS = 365
PERIOD_MIN_DAYS = 5
MATCH_TOUT_K = 1.5
MATCH_MIN = 3
HEATING_DAY_KWH = 1.0
KD_FLOOR = 2.0
DEFAULT_T_IN = 20.0
SETTLE_S = 1800

SUM_SOURCES = ("elec", "heat", "dhw", "defrost", "cool")
MEAN_SOURCES = ("t_out", "t_in", "t_flow")
OWN_SUFFIXES = {"elec": "energy_electrical", "heat": "energy_heating", "dhw": "energy_dhw",
                "defrost": "energy_defrost", "cool": "energy_cooling"}
OPTION_KEYS = {"elec": "history_energy_entity", "t_out": "history_outdoor_entity", "t_in": "history_indoor_entity"}


def stat_ids(own: dict, opts: dict) -> dict:
    """Statistic id per source: the pump's own entities, overridden by the three history options."""
    ids = {k: own.get(k) for k in (*SUM_SOURCES, *MEAN_SOURCES)}
    for key, opt in OPTION_KEYS.items():
        if (opts or {}).get(opt):
            ids[key] = opts[opt]
    return ids


def build_days(hourly: dict, ids: dict, tz: tzinfo) -> list[dict]:
    """One row per local day from hourly statistics rows ({'start': epoch s, 'change' | 'mean': value})."""
    series = {}
    for key, sid in ids.items():
        field = "change" if key in SUM_SOURCES else "mean"
        series[key] = {r["start"]: r[field] for r in (hourly.get(sid) or []) if sid and r.get(field) is not None}
    heat_h: dict[float, float] = {}
    for key in ("heat", "dhw"):
        for t, v in series[key].items():
            heat_h[t] = heat_h.get(t, 0.0) + v
    days: dict[date, dict] = {}
    for key, ser in series.items():
        for t, v in ser.items():
            w = heat_h.get(t, 0.0) if key == "t_flow" else 1.0
            if w <= 0:
                continue
            acc = days.setdefault(datetime.fromtimestamp(t, tz).date(), {}).setdefault(key, [0.0, 0.0])
            acc[0] += v * w
            acc[1] += w
    out = []
    for day in sorted(days):
        d = days[day]
        row = {"day": day.isoformat(), "hours": int(d["elec"][1]) if "elec" in d else 0,
               "heat_hours": int(d["heat"][1]) if "heat" in d else 0}
        for key in SUM_SOURCES:
            row[key] = round(d[key][0], 3) if key in d else None
        for key in MEAN_SOURCES:
            row[key] = round(d[key][0] / d[key][1], 2) if key in d else None
        made = [row[k] for k in ("heat", "dhw") if row[k] is not None]
        row["heat_total"] = round(sum(made) - (row["defrost"] or 0.0), 3) if made else None
        out.append(row)
    return out


def merge_days(old: list[dict], new: list[dict]) -> list[dict]:
    """Replace the days present in `new`, keep the rest; sorted and capped to HISTORY_DAYS."""
    by_day = {r["day"]: r for r in old}
    by_day.update({r["day"]: r for r in new})
    return [by_day[d] for d in sorted(by_day)][-HISTORY_DAYS:]


def settled(changes: list[dict]) -> list[dict]:
    """Settings changes without edits that went back to the earlier settings within SETTLE_S."""
    out: list[dict] = []
    for c in changes:
        if c.get("kind") != "change" or not c.get("from") or not c.get("to"):
            continue
        if out and c["to"] == out[-1]["from"] and c["t"] - out[-1]["t"] <= SETTLE_S:
            out.pop()
            continue
        out.append(c)
    return out


def tag_settings(rows: list[dict], changes: list[dict], fp_now: str | None, known_since: float | None,
                 tz: tzinfo) -> list[dict]:
    """Copies of the rows with the settings group of each day; 'mixed' on a change, None before tracking."""
    ts = [c["t"] for c in changes]
    out = []
    for r in rows:
        start = datetime.combine(date.fromisoformat(r["day"]), datetime.min.time(), tz).timestamp()
        i, j = bisect_left(ts, start), bisect_left(ts, start + 86400)
        if known_since is None or start < known_since:
            fp = None
        elif j > i:
            fp = "mixed"
        elif i:
            fp = changes[i - 1]["to"]
        else:
            fp = changes[0]["from"] if changes else fp_now
        out.append({**r, "fp": fp})
    return out


def day_data_problems(row: dict) -> list[str]:
    """Why a day has no trustworthy whole-day COP, whatever the settings were (empty = measured)."""
    out = []
    if min(row["hours"], row.get("heat_hours", 0)) < DAY_MIN_HOURS:
        out.append("coverage")
    if row.get("heat_total") is None or row["heat_total"] < DAY_MIN_HEAT_KWH:
        out.append("little_heat")
    if row.get("elec") is None or row["elec"] < DAY_MIN_ELEC_KWH:
        out.append("no_power")
    if (row.get("cool") or 0.0) > DAY_MAX_COOL_KWH:
        out.append("cooling")
    if row.get("t_flow") is None or row.get("t_out") is None:
        out.append("no_temperatures")
    return out


def day_problems(row: dict) -> list[str]:
    """Why a day is not usable for the settings comparison (empty = usable)."""
    out = day_data_problems(row)
    if row.get("fp") in ("mixed", None):
        out.append("settings_changed" if row.get("fp") == "mixed" else "settings_unknown")
    return out


def day_ok(row: dict) -> bool:
    return not day_problems(row)


def day_cop(row: dict) -> float:
    return row["heat_total"] / row["elec"]


def day_features(row: dict) -> list[float]:
    """Daily efficiency-factor regressors: outdoor temperature and mean heat output (load)."""
    return [1.0, row["t_out"] / 10.0, row["heat_total"] / 120.0]


def fit_daily(rows: list[dict]) -> dict | None:
    rows = [r for r in rows if day_ok(r)]
    if len(rows) < DAY_FIT_MIN:
        return None
    coef = _ridge([day_features(r) for r in rows], [day_cop(r) / carnot_cop(r["t_flow"], r["t_out"]) for r in rows])
    if coef is None:
        return None
    model = {"coef": coef, "n": len(rows)}
    errs = [abs(predict_daily(model, r) / day_cop(r) - 1) for r in rows]
    model["mape_pct"] = round(100 * sum(errs) / len(errs), 1)
    return model


def predict_daily(model: dict, row: dict) -> float:
    return _eta(model["coef"], day_features(row)) * carnot_cop(row["t_flow"], row["t_out"])


def daily_ratio(model: dict, row: dict) -> float:
    return day_cop(row) / predict_daily(model, row)


def compare_daily(rows: list[dict], baseline_fp: str) -> tuple[dict | None, dict]:
    """Whole-day COP (defrost, cycling, standby included) vs a baseline day model."""
    good = [r for r in rows if day_ok(r)]
    base = [r for r in good if r["fp"] == baseline_fp]
    model = fit_daily(base)
    groups: dict[str, dict] = {}
    if not model:
        return None, groups
    hold = []
    for r in base:
        m = fit_daily([x for x in base if x is not r])
        if m:
            hold.append((r["day"], daily_ratio(m, r)))
    if hold:
        groups[baseline_fp] = {**day_stats(hold, 1), "verdict": "baseline"}
    for fp in sorted({r["fp"] for r in good} - {baseline_fp}):
        st = day_stats([(r["day"], daily_ratio(model, r)) for r in good if r["fp"] == fp], 1)
        st["verdict"] = verdict(st, DAILY_MIN_DAYS)
        groups[fp] = st
    return model, groups


def qualifying_daily(rows: list[dict], fp: str) -> int:
    return sum(1 for r in rows if r.get("fp") == fp and day_ok(r))


def full_days(rows: list[dict], today: date) -> list[dict]:
    return [r for r in rows if r["day"] < today.isoformat()]


def _full(r: dict) -> bool:
    return r["hours"] >= DAY_MIN_HOURS and r.get("elec") is not None and r.get("t_out") is not None


def _heating(r: dict) -> bool:
    return _full(r) and r["elec"] >= HEATING_DAY_KWH


def _heat_full(r: dict) -> bool:
    return r.get("heat_hours", 0) >= DAY_MIN_HOURS and r.get("heat_total") is not None


def _kd(r: dict) -> float:
    return max(KD_FLOOR, (r["t_in"] if r.get("t_in") is not None else DEFAULT_T_IN) - r["t_out"])


def _pct(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b else round(100 * (a / b - 1), 1)


def _means(rows: list[dict]) -> dict:
    tin = [r["t_in"] for r in rows if r.get("t_in") is not None]
    return {"t_out": round(sum(r["t_out"] for r in rows) / len(rows), 1) if rows else None,
            "t_in": round(sum(tin) / len(tin), 1) if tin else None}


def _cop(rows: list[dict]) -> tuple[float | None, int]:
    measured = [r for r in rows if _heat_full(r) and r["elec"] > 0]
    used = sum(r["elec"] for r in measured)
    return (round(sum(r["heat_total"] for r in measured) / used, 2), len(measured)) if used > 0 else (None, 0)


def _median(v: list[float]) -> float:
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _matches(row: dict, pool: list[dict]) -> list[dict]:
    return [p for p in pool if abs(p["t_out"] - row["t_out"]) <= MATCH_TOUT_K]


def expected_elec(row: dict, pool: list[dict]) -> float | None:
    """Electricity a pool of past heating days needed at this outdoor temperature, scaled to this indoor temperature."""
    m = [p["elec"] * _kd(row) / _kd(p) for p in _matches(row, pool)]
    return _median(m) if len(m) >= MATCH_MIN else None


def _per_day(groups: list[list[dict]], key: str) -> float | None:
    means = [sum(v) / len(v) for g in groups if (v := [r[key] for r in g if r.get(key) is not None])]
    return round(sum(means) / len(means), 1) if means else None


def _matched_cop(groups: list[list[dict]]) -> tuple[float | None, int]:
    heat = elec = 0.0
    n = 0
    for g in groups:
        m = [r for r in g if _heat_full(r) and r["elec"] > 0]
        if m:
            heat += sum(r["heat_total"] for r in m) / len(m)
            elec += sum(r["elec"] for r in m) / len(m)
            n += 1
    return (round(heat / elec, 2), n) if elec > 0 else (None, 0)


def vs_past_year(cur: list[dict], pool: list[dict]) -> dict:
    """Matched heating days of the last 30 against heating days of the past year at the same outdoor temperature."""
    pool = [r for r in pool if _heating(r)]
    days = [r for r in cur if _heating(r)]
    pairs = [(r, e) for r in days if (e := expected_elec(r, pool)) is not None]
    matched = [r for r, _ in pairs]
    groups = [_matches(r, pool) for r in matched]
    refs = {p["day"] for g in groups for p in g}
    now_cop, now_cop_days = _cop(matched)
    past_cop, past_cop_days = _matched_cop(groups)
    elec = sum(r["elec"] for r in matched)
    expected = sum(e for _, e in pairs)
    out = {"heating_days": len(days), "matched_days": len(pairs), "reference_days": len(refs),
           "now": {"elec_kwh": round(elec, 1) if pairs else None, **_means(matched),
                   "cop": now_cop, "cop_days": now_cop_days},
           "past_year": {"elec_kwh": round(expected, 1) if pairs else None,
                         "t_out": _per_day(groups, "t_out"), "t_in": _per_day(groups, "t_in"),
                         "cop": past_cop, "cop_days": past_cop_days},
           "elec_pct": _pct(elec, expected) if pairs else None, "cop_pct": _pct(now_cop, past_cop),
           "comparable": len(pairs) >= PERIOD_MIN_DAYS}
    if not out["comparable"]:
        out["not_comparable_why"] = ["too_few_same_weather_days"]
    return out


def comparisons(rows: list[dict], today: date) -> dict:
    """Matched heating days of the last 30 full days against same-weather heating days of the past year."""
    by_day = {r["day"]: r for r in rows}

    def span(first: date, last: date) -> list[dict]:
        n = (last - first).days + 1
        return [by_day[d] for d in ((first + timedelta(days=i)).isoformat() for i in range(max(n, 0))) if d in by_day]

    yday = today - timedelta(days=1)
    first = yday - timedelta(days=WINDOW_DAYS - 1)
    cur = [r for r in span(first, yday) if _full(r)]
    pool = [r for r in span(yday - timedelta(days=YEAR_DAYS - 1), first - timedelta(days=1)) if _full(r)]
    return {"period": f"{first.isoformat()}..{yday.isoformat()}", **vs_past_year(cur, pool)}


def last_measured(rows: list[dict], today: date) -> tuple[dict | None, dict | None]:
    """(latest full day with a trustworthy COP, the latest full day when it was skipped for data reasons)."""
    days = full_days(rows, today)
    skipped = None
    if days and day_data_problems(days[-1]):
        skipped = {"day": days[-1]["day"], "why": day_data_problems(days[-1]), "hours": days[-1]["hours"]}
    for r in reversed(days):
        if not day_data_problems(r):
            return r, skipped
    return None, skipped
