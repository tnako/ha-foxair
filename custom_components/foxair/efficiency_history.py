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
WEEK_DAYS = 7
PERIOD_MIN_DAYS = 3
MATCH_TOUT_K = 1.0
MATCH_TIN_K = 0.7
MATCH_MIN = 3
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


def _heat_full(r: dict) -> bool:
    return r.get("heat_hours", 0) >= DAY_MIN_HOURS and r.get("heat_total") is not None


def _kd(r: dict) -> float:
    return max(0.0, (r["t_in"] if r.get("t_in") is not None else DEFAULT_T_IN) - r["t_out"])


def _pct(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b else round(100 * (a / b - 1), 1)


def _period(rows: list[dict]) -> dict:
    full = [r for r in rows if _full(r)]
    out = {"days": len(full), "elec_kwh": None, "heat_kwh": None, "cop": None, "t_out": None, "t_in": None,
           "elec_kwh_per_kelvin_day": None}
    if not full:
        return out
    elec = sum(r["elec"] for r in full)
    out["elec_kwh"] = round(elec, 1)
    out["t_out"] = round(sum(r["t_out"] for r in full) / len(full), 1)
    tin = [r["t_in"] for r in full if r.get("t_in") is not None]
    out["t_in"] = round(sum(tin) / len(tin), 1) if tin else None
    if all(_heat_full(r) for r in full) and elec > 0:
        heat = sum(r["heat_total"] for r in full)
        out["heat_kwh"] = round(heat, 1)
        out["cop"] = round(heat / elec, 2)
    kd = sum(_kd(r) for r in full)
    out["elec_kwh_per_kelvin_day"] = round(elec / kd, 3) if kd > 0 else None
    return out


def _median(v: list[float]) -> float:
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _same_weather(row: dict, pool: list[dict]) -> float | None:
    """Median electricity of reference days with the same outdoor (and indoor, when known) temperature."""
    m = [p["elec"] for p in pool
         if abs(p["t_out"] - row["t_out"]) <= MATCH_TOUT_K
         and (row.get("t_in") is None or p.get("t_in") is None or abs(p["t_in"] - row["t_in"]) <= MATCH_TIN_K)]
    return _median(m) if len(m) >= MATCH_MIN else None


def compare_periods(cur: list[dict], ref: list[dict], label: str, ref_label: str) -> dict:
    """Two periods side by side; electricity also against same-weather days of the reference period."""
    a, b = _period(cur), _period(ref)
    pool = [r for r in ref if _full(r)]
    pairs = [(r["elec"], m) for r in cur if _full(r) and (m := _same_weather(r, pool)) is not None]
    out = {"period": label, "reference_period": ref_label, "current": a, "reference": b,
           "elec_pct": _pct(a["elec_kwh"], b["elec_kwh"]),
           "elec_per_kelvin_day_pct": _pct(a["elec_kwh_per_kelvin_day"], b["elec_kwh_per_kelvin_day"]),
           "cop_pct": _pct(a["cop"], b["cop"]), "same_weather_days": len(pairs),
           "elec_vs_same_weather_pct": _pct(sum(p[0] for p in pairs), sum(p[1] for p in pairs)) if pairs else None,
           "comparable": a["days"] >= PERIOD_MIN_DAYS and b["days"] >= PERIOD_MIN_DAYS}
    if not out["comparable"]:
        out["not_comparable_why"] = ["too_few_full_days"]
    return out


def comparisons(rows: list[dict], today: date) -> list[dict]:
    """Last 7 full days vs the 7 before, and this month so far vs the same dates last year."""
    by_day = {r["day"]: r for r in rows}

    def span(first: date, last: date) -> list[dict]:
        n = (last - first).days + 1
        return [by_day[d] for d in ((first + timedelta(days=i)).isoformat() for i in range(max(n, 0))) if d in by_day]

    yday = today - timedelta(days=1)
    week = timedelta(days=WEEK_DAYS)
    out = [compare_periods(span(yday - week + timedelta(days=1), yday), span(yday - 2 * week + timedelta(days=1),
                                                                            yday - week),
                           "last_7_days", "previous_7_days")]
    first = yday.replace(day=1)
    last_ly = yday.replace(year=yday.year - 1, day=min(yday.day, 28)) if (yday.month, yday.day) == (2, 29) \
        else yday.replace(year=yday.year - 1)
    out.append(compare_periods(span(first, yday), span(first.replace(year=first.year - 1), last_ly),
                               "month_to_date", "same_dates_last_year"))
    return out


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
