"""Weather-normalised efficiency analyser: steady buckets, daily totals, defrost log, settings comparison, advice."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import time

BUCKET_S = 600
MIN_SAMPLES = 12
WARMUP_S = 600
MIN_ELEC_W = 150.0
DT_HX = 7.0
FIT_MIN_BUCKETS = 36
FIT_MIN_DAYS = 2
MAX_BUCKETS = 5000
HOLDOUT_MAX_DAYS = 30
RIDGE = (0.0, 0.05, 0.05)
ETA_LIMITS = (0.15, 0.8)
COMPARE_MIN_DAYS = 3
DAY_S = 86400
HINT_WINDOW_S = 7 * DAY_S
SH_OFF_TARGET_K = 1.5
SH_CORR_LIMIT = -0.3
SH_CORR_MIN_N = 100
SHORT_CYCLE_STARTS = 24
SHORT_CYCLE_AVG_RUN_S = 1200
MAX_GAP_S = 120
QUALIFY_DAY_BUCKETS = 6
COMPARE_MAX_DAYS = 10
MIN_HOLD_S = DAY_S
DEMAND_WINDOW_S = 2 * DAY_S
DIRECTION_MIN_N = 30
DIRECTION_CORR = 0.1
MAX_CHANGES = 200

DAY_MIN_HEAT_KWH = 5.0
DAY_MIN_COVERAGE = 0.8
DAY_MIN_RUN_H = 1.0
DAY_FIT_MIN = 5
DAILY_MIN_DAYS = 5
DAILY_MAX_DAYS = 14
MAX_DAYS_KEPT = 400

MAX_DEFROSTS = 800
DEFROST_MIN_EVENTS = 6
DEFROST_TIMER_SLACK_S = 600
DEFROST_SHORT_S = 240
DEFROST_TIMER_SHARE = 0.5
RUN_STATUS_DEFROST = 2

FAN_CAP_MARGIN = 5.0
FAN_CAP_SHARE = 0.2

LADDER = {
    "E02": {"step": 0.5, "min": 2.0, "max": 6.0, "metric": "steady", "dirs": (-1, 1)},
    "F26": {"step": 30.0, "min": 600.0, "max": 660.0, "metric": "steady", "dirs": (1,)},
    "D03": {"step": 15.0, "min": 30.0, "max": 90.0, "metric": "daily", "dirs": (1,)},
}
DAILY_PREFIXES = ("D", "P", "C", "A", "H")
ACTIONS = ["collecting", "keep", "change", "revert", "accept", "wait_heating", "check_curve", "done", "none"]
FINDINGS = ["collecting", "ok", "short_cycling", "superheat_off_target", "superheat_costs", "fan_at_max",
            "defrost_on_timer"]

F_T, F_HZ, F_TOUT, F_TFLOW, F_Q, F_P, F_SH, F_EEV, F_FP, F_FAN = range(10)
SAMPLE_KEYS = ("hz", "t_out", "t_flow", "q", "p")
R_DAY, R_HEAT, R_ELEC, R_TOUT, R_TFLOW, R_RUN, R_STARTS, R_DEFROSTS, R_FP, R_COVER, R_COOL = range(11)


def carnot_cop(t_flow: float, t_out: float) -> float:
    """Ideal heating COP with a fixed heat-exchanger approach."""
    return (t_flow + 273.15) / max(t_flow - t_out + DT_HX, 5.0)


def features(hz: float, t_out: float) -> list[float]:
    """Steady efficiency-factor regressors (scaled)."""
    return [1.0, hz / 50.0, t_out / 10.0]


def day_features(row: list) -> list[float]:
    """Daily efficiency-factor regressors: outdoor temperature and load factor."""
    return [1.0, row[R_TOUT] / 10.0, row[R_RUN] / 24.0]


def fingerprint(settings: dict) -> str:
    """Stable short id of a settings snapshot."""
    if not settings:
        return "none"
    blob = json.dumps({str(k): settings[k] for k in settings}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:8]


def day_of(t: float) -> int:
    return int(t // DAY_S)


def metric_for(param: str | None) -> str:
    if param in LADDER:
        return LADDER[param]["metric"]
    return "daily" if param and param.startswith(DAILY_PREFIXES) else "steady"


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                k = m[r][c] / m[c][c]
                for j in range(c, n + 1):
                    m[r][j] -= k * m[c][j]
    return [m[i][n] / m[i][i] for i in range(n)]


def _ridge(xs: list[list[float]], ys: list[float]) -> list[float] | None:
    k = len(RIDGE)
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for x, y in zip(xs, ys):
        for i in range(k):
            xty[i] += x[i] * y
            for j in range(k):
                xtx[i][j] += x[i] * x[j]
    for i in range(k):
        xtx[i][i] += RIDGE[i] * len(ys)
    return _solve(xtx, xty)


def _eta(coef: list[float], x: list[float]) -> float:
    return min(max(sum(c * v for c, v in zip(coef, x)), ETA_LIMITS[0]), ETA_LIMITS[1])


def bucket_cop(b: list) -> float:
    return b[F_Q] / b[F_P]


def predict(model: dict, hz: float, t_out: float, t_flow: float) -> float:
    return _eta(model["coef"], features(hz, t_out)) * carnot_cop(t_flow, t_out)


def fit(buckets: list[list]) -> dict | None:
    """Ridge fit of eta = COP / Carnot on [1, Hz, T_out]; None when data is too thin."""
    days = {day_of(b[F_T]) for b in buckets}
    if len(buckets) < FIT_MIN_BUCKETS or len(days) < FIT_MIN_DAYS:
        return None
    coef = _ridge([features(b[F_HZ], b[F_TOUT]) for b in buckets],
                  [bucket_cop(b) / carnot_cop(b[F_TFLOW], b[F_TOUT]) for b in buckets])
    if coef is None:
        return None
    model = {"coef": coef, "n": len(buckets), "days": len(days)}
    errs = [abs(predict(model, b[F_HZ], b[F_TOUT], b[F_TFLOW]) / bucket_cop(b) - 1) for b in buckets]
    model["mape_pct"] = round(100 * sum(errs) / len(errs), 1)
    return model


def ratios(model: dict, buckets: list[list]) -> list[tuple[int, float]]:
    """(day, actual/expected COP) per bucket."""
    return [(day_of(b[F_T]), bucket_cop(b) / predict(model, b[F_HZ], b[F_TOUT], b[F_TFLOW])) for b in buckets]


def day_stats(pairs: list[tuple[int, float]], min_per_day: int = QUALIFY_DAY_BUCKETS) -> dict:
    """Mean ratio as a % delta with a 95 % interval over day means; thin days don't count."""
    by_day: dict[int, list[float]] = {}
    for d, r in pairs:
        by_day.setdefault(d, []).append(r)
    kept = [v for v in by_day.values() if len(v) >= min_per_day]
    means = [sum(v) / len(v) for v in kept]
    n_days = len(means)
    flat = [r for v in kept for r in v] or [r for _, r in pairs]
    mean = sum(flat) / len(flat) if flat else 1.0
    ci = None
    if n_days >= 2:
        mu = sum(means) / n_days
        sd = math.sqrt(sum((m - mu) ** 2 for m in means) / (n_days - 1))
        ci = 1.96 * sd / math.sqrt(n_days)
    return {"buckets": len(pairs), "days": n_days, "delta_pct": round(100 * (mean - 1), 1),
            "ci95_pct": None if ci is None else round(100 * ci, 1)}


def baseline_holdout(buckets: list[list]) -> list[tuple[int, float]]:
    """Leave-one-day-out ratios on the baseline: its honest noise floor."""
    out = []
    days = sorted({day_of(b[F_T]) for b in buckets})[-HOLDOUT_MAX_DAYS:]
    for d in days:
        model = fit([b for b in buckets if day_of(b[F_T]) != d])
        if model:
            out.extend(ratios(model, [b for b in buckets if day_of(b[F_T]) == d]))
    return out


def verdict(stats: dict, min_days: int = COMPARE_MIN_DAYS) -> str:
    if stats["days"] < min_days or stats["ci95_pct"] is None:
        return "collecting"
    if abs(stats["delta_pct"]) <= stats["ci95_pct"]:
        return "inconclusive"
    return "better" if stats["delta_pct"] > 0 else "worse"


def compare(buckets: list[list], baseline_fp: str) -> tuple[dict | None, dict]:
    """Fit on the baseline settings, score every other settings group against it."""
    base = [b for b in buckets if b[F_FP] == baseline_fp]
    model = fit(base)
    groups: dict[str, dict] = {}
    if not model:
        return None, groups
    hold = baseline_holdout(base)
    if hold:
        groups[baseline_fp] = {**day_stats(hold), "verdict": "baseline"}
    for fp in sorted({b[F_FP] for b in buckets} - {baseline_fp}):
        st = day_stats(ratios(model, [b for b in buckets if b[F_FP] == fp]))
        st["verdict"] = verdict(st)
        groups[fp] = st
    return model, groups


def day_ok(row: list) -> bool:
    return (row[R_COVER] >= DAY_MIN_COVERAGE and row[R_HEAT] >= DAY_MIN_HEAT_KWH and row[R_ELEC] > 0
            and row[R_RUN] >= DAY_MIN_RUN_H and not row[R_COOL] and row[R_FP] not in ("mixed", "none")
            and row[R_TFLOW] is not None and row[R_TOUT] is not None)


def day_cop(row: list) -> float:
    return row[R_HEAT] / row[R_ELEC]


def fit_daily(rows: list[list]) -> dict | None:
    rows = [r for r in rows if day_ok(r)]
    if len(rows) < DAY_FIT_MIN:
        return None
    coef = _ridge([day_features(r) for r in rows], [day_cop(r) / carnot_cop(r[R_TFLOW], r[R_TOUT]) for r in rows])
    if coef is None:
        return None
    model = {"coef": coef, "n": len(rows)}
    errs = [abs(predict_daily(model, r) / day_cop(r) - 1) for r in rows]
    model["mape_pct"] = round(100 * sum(errs) / len(errs), 1)
    return model


def predict_daily(model: dict, row: list) -> float:
    return _eta(model["coef"], day_features(row)) * carnot_cop(row[R_TFLOW], row[R_TOUT])


def daily_ratio(model: dict, row: list) -> float:
    return day_cop(row) / predict_daily(model, row)


def compare_daily(rows: list[list], baseline_fp: str) -> tuple[dict | None, dict]:
    """Whole-day COP (defrost, cycling, standby included) vs a baseline day model."""
    good = [r for r in rows if day_ok(r)]
    base = [r for r in good if r[R_FP] == baseline_fp]
    model = fit_daily(base)
    groups: dict[str, dict] = {}
    if not model:
        return None, groups
    hold = []
    for r in base:
        m = fit_daily([x for x in base if x is not r])
        if m:
            hold.append((r[R_DAY], daily_ratio(m, r)))
    if hold:
        groups[baseline_fp] = {**day_stats(hold, 1), "verdict": "baseline"}
    for fp in sorted({r[R_FP] for r in good} - {baseline_fp}):
        st = day_stats([(r[R_DAY], daily_ratio(model, r)) for r in good if r[R_FP] == fp], 1)
        st["verdict"] = verdict(st, DAILY_MIN_DAYS)
        groups[fp] = st
    return model, groups


def corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


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
          defrosts: list[dict] | None = None) -> list[str]:
    """Ordered findings for the recent window; the first one is the headline."""
    current = current or {}
    out = []
    if starts_24h >= SHORT_CYCLE_STARTS and run_s_24h / starts_24h < SHORT_CYCLE_AVG_RUN_S:
        out.append("short_cycling")
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


def qualifying_days(buckets: list[list], fp: str) -> int:
    """Days with enough steady heating buckets for one settings group."""
    per: dict[int, int] = {}
    for b in buckets:
        if b[F_FP] == fp:
            per[day_of(b[F_T])] = per.get(day_of(b[F_T]), 0) + 1
    return sum(1 for n in per.values() if n >= QUALIFY_DAY_BUCKETS)


def qualifying_daily(rows: list[list], fp: str) -> int:
    return sum(1 for r in rows if r[R_FP] == fp and day_ok(r))


def _only_diff(a: dict, b: dict) -> dict:
    return {k: v for k, v in a.items() if b.get(k) != v}


def _step(param: str, value: float, direction: int) -> float | None:
    lad = LADDER[param]
    if not lad["min"] <= value <= lad["max"]:
        return None
    new = round(min(max(value + direction * lad["step"], lad["min"]), lad["max"]), 1)
    return None if new == round(value, 1) else new


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


def _candidate_dirs(param: str, *, model, buckets, base_buckets, current, sh_target, defrosts, now,
                    day_model) -> tuple[list[int], str] | None:
    """Directions worth testing for one ladder parameter now, or None when its precondition fails."""
    if param == "E02":
        if model is None:
            return None
        d, why = _direction_from_data(model, base_buckets, sh_target)
        return [d, -d], why
    if param == "F26":
        share = fan_cap_share(buckets, current.get("F26"), now)
        if model is None or share is None or share < FAN_CAP_SHARE:
            return None
        return [1], "fan_at_max"
    if param == "D03":
        if day_model is None or not defrost_on_timer(defrost_summary(defrosts, now, current.get("D03"))):
            return None
        return [1], "defrost_on_timer"
    return None


def advise(*, buckets: list[list], groups: dict, settings: dict, current: dict, baseline_fp: str | None,
           changes: list[dict], model: dict | None, hint_list: list[str], sh_target: float | None,
           now: float, day_rows: list[list] | None = None, day_groups: dict | None = None,
           day_model: dict | None = None, defrosts: list[dict] | None = None) -> dict:
    """Next step for the user: what to change, to which value, and not before when."""
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
        need = max(min_days - days, 1)
        return {**out, **res, "action": "keep" if heating else "wait_heating", "days_left": need,
                "reason": "need_more_days" if heating else "no_heating"}

    base_buckets = [b for b in buckets if b[F_FP] == baseline_fp]
    if model is None or qualifying_days(buckets, baseline_fp) < COMPARE_MIN_DAYS:
        return {**out, "action": "collecting" if heating else "wait_heating",
                "days_left": max(COMPARE_MIN_DAYS - qualifying_days(buckets, baseline_fp), 1),
                "reason": "baseline_needs_days" if heating else "no_heating"}
    for param, lad in LADDER.items():
        if param not in current:
            continue
        cand = _candidate_dirs(param, model=model, buckets=buckets, base_buckets=base_buckets, current=current,
                               sh_target=sh_target, defrosts=defrosts, now=now, day_model=day_model)
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
                    "not_before": now, "days_left": days, "metric": lad["metric"],
                    "reason": why if dirn == dirs[0] else "other_direction_tried"}
    return {**out, "action": "done", "reason": "no_candidate"}


class BucketBuilder:
    """Turns 30 s polls into 10 min steady-state heating buckets."""

    def __init__(self):
        self.run_start: float | None = None
        self.was_running = False
        self.last_fp: str | None = None
        self.key: int | None = None
        self.acc: list[dict] = []
        self.tainted = False

    def add(self, now: float, s: dict) -> tuple[list | None, bool]:
        """Feed one poll; returns (closed bucket or None, compressor-start flag)."""
        running = bool(s.get("running"))
        steady = bool(s.get("steady_ok", True))
        started = running and not self.was_running
        if not running:
            self.run_start = None
        elif started or not steady or s.get("fp") != self.last_fp:
            self.run_start = now
        self.was_running = running
        self.last_fp = s.get("fp")
        key = int(now // BUCKET_S)
        closed = None
        if self.key is not None and key != self.key:
            closed = self._close()
        if self.key != key:
            self.key, self.acc, self.tainted = key, [], False
        if running and (not steady or (self.acc and s.get("fp") != self.acc[0]["fp"])):
            self.tainted = True  # defrost, heater or settings change inside the window: drop it
        elif running and self.run_start is not None and now - self.run_start >= WARMUP_S:
            if all(s.get(k) is not None for k in SAMPLE_KEYS) and s["q"] > 0 and s["p"] >= MIN_ELEC_W:
                self.acc.append(s)
            else:
                self.tainted = True
        # stopped or still warming up: skip the poll, the window keeps its steady samples
        return closed, started

    def _close(self) -> list | None:
        if self.tainted or len(self.acc) < MIN_SAMPLES or self.key is None:
            return None
        n = len(self.acc)

        def avg(k):
            return sum(x[k] for x in self.acc) / n

        def opt(k):
            v = [x[k] for x in self.acc if x.get(k) is not None]
            return round(sum(v) / len(v), 2) if v else None

        return [self.key * BUCKET_S, round(avg("hz"), 2), round(avg("t_out"), 2), round(avg("t_flow"), 2),
                round(avg("q"), 1), round(avg("p"), 1), opt("sh"), opt("eev"), self.acc[0]["fp"], opt("fan")]


class DefrostTracker:
    """Detects defrost cycles from the run status and records one event per cycle."""

    def __init__(self, state: dict | None = None):
        s = state or {}
        self.active = bool(s.get("active"))
        self.start = s.get("start")
        self.elec_wh = s.get("elec_wh", 0.0)
        self.t_out = s.get("t_out")
        self.coil = s.get("coil")
        self.last_start = s.get("last_start")
        self.run_s = s.get("run_s")
        self.last_coil = s.get("last_coil")
        self.last_t = s.get("last_t")

    def state(self) -> dict:
        return {k: getattr(self, k) for k in ("active", "start", "elec_wh", "t_out", "coil", "last_start",
                                               "run_s", "last_coil", "last_t")}

    def add(self, now: float, s: dict) -> tuple[dict | None, bool]:
        """Feed one poll; returns (finished event or None, defrost-started flag)."""
        dt = now - self.last_t if self.last_t is not None and 0 < now - self.last_t <= MAX_GAP_S else 0.0
        self.last_t = now
        rs = s.get("rs")
        if rs is None:
            return None, False
        if self.active and self.start is not None:
            if s.get("p_day") is not None:
                self.elec_wh += s["p_day"] * dt / 3600
            if rs == RUN_STATUS_DEFROST:
                return None, False
            start = float(self.start)
            ev = {"t": start, "dur_s": round(now - start), "elec_wh": round(self.elec_wh, 1),
                  "interval_s": None if self.last_start is None else round(start - self.last_start),
                  "run_s": None if self.run_s is None else round(self.run_s),
                  "t_out": self.t_out, "coil": self.coil, "fp": s.get("fp")}
            self.active, self.last_start, self.run_s, self.elec_wh = False, start, 0.0, 0.0
            return ev, False
        if rs == RUN_STATUS_DEFROST:
            self.active, self.start, self.elec_wh = True, now, 0.0
            self.t_out, self.coil = s.get("t_out"), self.last_coil
            return None, True
        if s.get("running") and self.run_s is not None:
            self.run_s += dt
        if s.get("coil") is not None:
            self.last_coil = s["coil"]
        return None, False


class DailyAccumulator:
    """Whole-day energy totals: heat (heating + DHW), electricity (everything), outdoor, run time."""

    FIELDS = ("day", "heat_wh", "elec_wh", "elec_s", "tout_sum", "tout_s", "tflow_sum", "tflow_s", "run_s",
              "starts", "defrosts", "fp", "cooling", "last_t")

    def __init__(self, state: dict | None = None):
        self.s = dict(state) if state else {}

    def _reset(self, day: int) -> None:
        self.s = {"day": day, "heat_wh": 0.0, "elec_wh": 0.0, "elec_s": 0.0, "tout_sum": 0.0, "tout_s": 0.0,
                  "tflow_sum": 0.0, "tflow_s": 0.0, "run_s": 0.0, "starts": 0, "defrosts": 0, "fp": None,
                  "cooling": False, "last_t": None}

    def _row(self) -> list:
        s = self.s
        return [s["day"], round(s["heat_wh"] / 1000, 3), round(s["elec_wh"] / 1000, 3),
                round(s["tout_sum"] / s["tout_s"], 2) if s["tout_s"] else None,
                round(s["tflow_sum"] / s["tflow_s"], 2) if s["tflow_s"] else None,
                round(s["run_s"] / 3600, 2), s["starts"], s["defrosts"], s["fp"] or "none",
                round(min(s["elec_s"] / DAY_S, 1.0), 3), s["cooling"]]

    def add(self, now: float, smp: dict, started: bool, defrost_started: bool) -> list | None:
        """Feed one poll; returns the finished day row when the day rolled over."""
        day = day_of(now)
        closed = None
        if not self.s:
            self._reset(day)
        elif self.s["day"] != day:
            closed = self._row()
            self._reset(day)
        s = self.s
        dt = now - s["last_t"] if s["last_t"] is not None and 0 < now - s["last_t"] <= MAX_GAP_S else 0.0
        s["last_t"] = now
        if s["fp"] is None:
            s["fp"] = smp.get("fp")
        elif s["fp"] != smp.get("fp"):
            s["fp"] = "mixed"
        s["starts"] += int(started)
        s["defrosts"] += int(defrost_started)
        s["cooling"] = s["cooling"] or bool(smp.get("cooling"))
        if dt:
            if smp.get("p_day") is not None:
                s["elec_wh"] += smp["p_day"] * dt / 3600
                s["elec_s"] += dt
            if smp.get("q_day"):
                s["heat_wh"] += smp["q_day"] * dt / 3600
            if smp.get("t_out") is not None:
                s["tout_sum"] += smp["t_out"] * dt
                s["tout_s"] += dt
            if smp.get("running"):
                s["run_s"] += dt
                if smp.get("t_flow") is not None:
                    s["tflow_sum"] += smp["t_flow"] * dt
                    s["tflow_s"] += dt
        return closed


class EfficiencyAnalyser:
    """Analyser state; the caller persists to_dict() and runs refresh() off the event loop."""

    def __init__(self, data: dict | None = None):
        data = data or {}
        self.buckets: list[list] = [list(b) for b in data.get("buckets", [])]
        self.settings: dict[str, dict] = dict(data.get("settings", {}))
        self.current: dict = dict(data.get("current", {}))
        self.baseline_fp: str | None = data.get("baseline_fp")
        self.starts: list[float] = list(data.get("starts", []))
        self.run_hours: dict[str, float] = dict(data.get("run_hours", {}))
        self.changes: list[dict] = list(data.get("changes", []))
        self.days: list[list] = [list(r) for r in data.get("days", [])]
        self.defrosts: list[dict] = list(data.get("defrosts", []))
        self.defrost_tracker = DefrostTracker(data.get("defrost_state"))
        self.daily = DailyAccumulator(data.get("day_acc"))
        self.builder = BucketBuilder()
        self.model: dict | None = None
        self.groups: dict = {}
        self.day_model: dict | None = None
        self.day_groups: dict = {}
        self.hint_list: list[str] = ["collecting"]
        self.recent: dict | None = None
        self.advice: dict = {"action": "none", "reason": "settings_unknown"}
        self.sh_target: float | None = None
        self._last_t: float | None = None

    def to_dict(self, now: float) -> dict:
        return {"buckets": self.buckets, "settings": self.settings, "current": self.current,
                "baseline_fp": self.baseline_fp, "starts": self.starts, "run_hours": self.run_hours,
                "changes": self.changes, "days": self.days, "defrosts": self.defrosts,
                "defrost_state": self.defrost_tracker.state(), "day_acc": self.daily.s, "saved_at": now}

    def current_fp(self) -> str:
        fp = fingerprint(self.current)
        if self.current and fp not in self.settings:
            self.settings[fp] = dict(self.current)
        return fp

    def _rename(self, old: str, new: str) -> None:
        if old == new:
            return
        for b in self.buckets:
            if b[F_FP] == old:
                b[F_FP] = new
        for r in self.days:
            if r[R_FP] == old:
                r[R_FP] = new
        for e in self.defrosts:
            if e.get("fp") == old:
                e["fp"] = new
        for c in self.changes:
            for k in ("from", "to"):
                if c.get(k) == old:
                    c[k] = new
        if self.daily.s.get("fp") == old:
            self.daily.s["fp"] = new
        if self.baseline_fp == old:
            self.baseline_fp = new

    def _extend(self, added: dict) -> None:
        """Newly tracked parameters: add their current value to every stored group and re-key it."""
        for old, snap in list(self.settings.items()):
            ext = {**added, **snap}
            new = fingerprint(ext)
            del self.settings[old]
            self.settings[new] = ext
            self._rename(old, new)

    def update_settings(self, settings: dict, now: float | None = None) -> dict | None:
        """Merge a settings snapshot; returns the change record when a known value moved."""
        new = {k: v for k, v in settings.items() if v is not None}
        diff = {k: [self.current[k], v] for k, v in new.items() if k in self.current and self.current[k] != v}
        added = {k: v for k, v in new.items() if k not in self.current}
        if added and self.current:
            self._extend(added)
            self.current.update(added)
        old_fp = self.current_fp() if self.current else None
        self.current.update(new)
        if self.baseline_fp is None and self.current:
            self.baseline_fp = self.current_fp()
        if not diff:
            return None
        rec = {"t": time.time() if now is None else now, "kind": "change", "diff": diff,
               "from": old_fp, "to": self.current_fp()}
        self.changes.append(rec)
        del self.changes[:-MAX_CHANGES]
        return rec

    def observe(self, now: float, sample: dict) -> bool:
        """Feed one poll; True when a bucket, day or defrost closed (time to refresh and save)."""
        fp = self.current_fp()
        sample = dict(sample, fp=fp)
        if fp == "none":
            sample["steady_ok"] = False
        running = bool(sample.get("running"))
        if running and self._last_t is not None and 0 < now - self._last_t <= MAX_GAP_S:
            hour = str(int(now // 3600))
            self.run_hours[hour] = self.run_hours.get(hour, 0.0) + now - self._last_t
        self._last_t = now
        closed, started = self.builder.add(now, sample)
        if started:
            self.starts.append(now)
        event, defrost_started = self.defrost_tracker.add(now, sample)
        day_row = self.daily.add(now, sample, started, defrost_started)
        self.starts = [t for t in self.starts if now - t <= DAY_S]
        floor = int(now // 3600) - 24
        self.run_hours = {h: s for h, s in self.run_hours.items() if int(h) > floor}
        if event:
            self.defrosts.append(event)
            del self.defrosts[:-MAX_DEFROSTS]
        if day_row:
            self.days.append(day_row)
            del self.days[:-MAX_DAYS_KEPT]
        if closed is not None:
            self.buckets.append(closed)
            del self.buckets[:-MAX_BUCKETS]
        return closed is not None or bool(event) or bool(day_row)

    def set_baseline(self, now: float | None = None) -> None:
        old = self.baseline_fp
        self.baseline_fp = self.current_fp()
        if old != self.baseline_fp:
            self.changes.append({"t": time.time() if now is None else now, "kind": "baseline",
                                 "from": old, "to": self.baseline_fp})
            del self.changes[:-MAX_CHANGES]

    def last_change(self) -> dict | None:
        return next((c for c in reversed(self.changes) if c.get("kind") == "change"), None)

    def refresh(self, now: float) -> None:
        """Recompute models, comparisons, hints and advice (CPU-bound: run in an executor)."""
        buckets, days, defrosts = list(self.buckets), list(self.days), list(self.defrosts)
        settings, current = dict(self.settings), dict(self.current)
        model, groups, day_model, day_groups = None, {}, None, {}
        if self.baseline_fp is not None:
            model, groups = compare(buckets, self.baseline_fp)
            day_model, day_groups = compare_daily(days, self.baseline_fp)
        recent = None
        if model:
            r = [x for _, x in ratios(model, [b for b in buckets if now - b[F_T] <= DAY_S])]
            if r:
                recent = {"index_pct": round(100 * sum(r) / len(r), 1), "buckets": len(r)}
        hint_list = hints(model, buckets, len(self.starts), sum(self.run_hours.values()), self.sh_target, now,
                          current, defrosts)
        last = self.last_change()
        advice = advise(buckets=buckets, groups=groups, settings=settings, current=current,
                        baseline_fp=self.baseline_fp, changes=[last] if last else [], model=model,
                        hint_list=hint_list, sh_target=self.sh_target, now=now, day_rows=days,
                        day_groups=day_groups, day_model=day_model, defrosts=defrosts)
        self.model, self.groups, self.recent, self.hint_list, self.advice = model, groups, recent, hint_list, advice
        self.day_model, self.day_groups = day_model, day_groups

    def expected_cop(self, hz, t_out, t_flow) -> float | None:
        if self.model is None or hz is None or t_out is None or t_flow is None or hz <= 0:
            return None
        return predict(self.model, hz, t_out, t_flow)

    def last_day(self) -> dict | None:
        """Most recent complete qualifying day with its ratio to the baseline day model."""
        for r in reversed(self.days):
            if day_ok(r):
                out = {"day": r[R_DAY], "cop": round(day_cop(r), 2), "heat_kwh": r[R_HEAT], "elec_kwh": r[R_ELEC],
                       "t_out": r[R_TOUT], "run_h": r[R_RUN], "defrosts": r[R_DEFROSTS], "fp": r[R_FP]}
                if self.day_model:
                    out["expected_cop"] = round(predict_daily(self.day_model, r), 2)
                    out["index_pct"] = round(100 * daily_ratio(self.day_model, r), 1)
                return out
        return None

    def describe(self, fp: str) -> str:
        """Settings that differ from the baseline, e.g. 'E02=3.0'."""
        if fp == self.baseline_fp:
            return "baseline"
        cur, base = self.settings.get(fp, {}), self.settings.get(self.baseline_fp or "", {})
        diff = [f"{k}={v}" for k, v in sorted(cur.items()) if base.get(k) != v]
        return " ".join(diff) or fp
