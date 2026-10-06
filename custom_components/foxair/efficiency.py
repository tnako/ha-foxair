"""Weather-normalised efficiency analyser: steady buckets, Carnot COP model, settings comparison."""
from __future__ import annotations

import hashlib
import json
import math
import time

BUCKET_S = 600
MIN_SAMPLES = 12
WARMUP_S = 900
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
LADDER = {"E02": {"step": 0.5, "min": 2.0, "max": 6.0}}
ACTIONS = ["collecting", "keep", "change", "revert", "accept", "wait_heating", "check_curve", "done", "none"]

F_T, F_HZ, F_TOUT, F_TFLOW, F_Q, F_P, F_SH, F_EEV, F_FP = range(9)
SAMPLE_KEYS = ("hz", "t_out", "t_flow", "q", "p")


def carnot_cop(t_flow: float, t_out: float) -> float:
    """Ideal heating COP with a fixed heat-exchanger approach."""
    return (t_flow + 273.15) / max(t_flow - t_out + DT_HX, 5.0)


def features(hz: float, t_out: float) -> list[float]:
    """Efficiency-factor regressors (scaled)."""
    return [1.0, hz / 50.0, t_out / 10.0]


def fingerprint(settings: dict) -> str:
    """Stable short id of a settings snapshot."""
    if not settings:
        return "none"
    blob = json.dumps({str(k): settings[k] for k in settings}, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:8]


def day_of(t: float) -> int:
    return int(t // DAY_S)


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


def bucket_cop(b: list) -> float:
    return b[F_Q] / b[F_P]


def predict(model: dict, hz: float, t_out: float, t_flow: float) -> float:
    eta = sum(c * x for c, x in zip(model["coef"], features(hz, t_out)))
    eta = min(max(eta, ETA_LIMITS[0]), ETA_LIMITS[1])
    return eta * carnot_cop(t_flow, t_out)


def fit(buckets: list[list]) -> dict | None:
    """Ridge fit of eta = COP / Carnot on [1, Hz, T_out]; None when data is too thin."""
    days = {day_of(b[F_T]) for b in buckets}
    if len(buckets) < FIT_MIN_BUCKETS or len(days) < FIT_MIN_DAYS:
        return None
    k = len(RIDGE)
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for b in buckets:
        x = features(b[F_HZ], b[F_TOUT])
        y = bucket_cop(b) / carnot_cop(b[F_TFLOW], b[F_TOUT])
        for i in range(k):
            xty[i] += x[i] * y
            for j in range(k):
                xtx[i][j] += x[i] * x[j]
    n = len(buckets)
    for i in range(k):
        xtx[i][i] += RIDGE[i] * n
    coef = _solve(xtx, xty)
    if coef is None:
        return None
    model = {"coef": coef, "n": n, "days": len(days)}
    errs = [abs(predict(model, b[F_HZ], b[F_TOUT], b[F_TFLOW]) / bucket_cop(b) - 1) for b in buckets]
    model["mape_pct"] = round(100 * sum(errs) / n, 1)
    return model


def ratios(model: dict, buckets: list[list]) -> list[tuple[int, float]]:
    """(day, actual/expected COP) per bucket."""
    return [(day_of(b[F_T]), bucket_cop(b) / predict(model, b[F_HZ], b[F_TOUT], b[F_TFLOW])) for b in buckets]


def day_stats(pairs: list[tuple[int, float]]) -> dict:
    """Mean ratio as a % delta with a 95 % interval over day means; thin days don't count."""
    by_day: dict[int, list[float]] = {}
    for d, r in pairs:
        by_day.setdefault(d, []).append(r)
    kept = [v for v in by_day.values() if len(v) >= QUALIFY_DAY_BUCKETS]
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


def verdict(stats: dict) -> str:
    if stats["days"] < COMPARE_MIN_DAYS or stats["ci95_pct"] is None:
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


def hints(model: dict | None, buckets: list[list], starts_24h: int, run_s_24h: float,
          sh_target: float | None, now: float) -> list[str]:
    """Ordered findings for the recent window; the first one is the headline."""
    out = []
    if starts_24h >= SHORT_CYCLE_STARTS and run_s_24h / starts_24h < SHORT_CYCLE_AVG_RUN_S:
        out.append("short_cycling")
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


def _only_diff(a: dict, b: dict) -> dict:
    return {k: v for k, v in a.items() if b.get(k) != v}


def _step(param: str, value: float, direction: int) -> float | None:
    lad = LADDER[param]
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


def advise(*, buckets: list[list], groups: dict, settings: dict, current: dict, baseline_fp: str | None,
           changes: list[dict], model: dict | None, hint_list: list[str], sh_target: float | None,
           now: float) -> dict:
    """Next step for the user: what to change, to which value, and not before when."""
    out = {"action": "none", "param": None, "from": None, "to": None, "not_before": None,
           "days_left": None, "reason": None}
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
        st = groups.get(fp) or {"days": 0, "verdict": "collecting"}
        days = qualifying_days(buckets, fp)
        info = {"param": param, "from": current.get(param) if param else None,
                "to": base.get(param) if param else None}
        if st["verdict"] == "better":
            return {**out, "action": "accept", "param": param, "from": base.get(param) if param else None,
                    "to": current.get(param) if param else None, "reason": "better",
                    "delta_pct": st.get("delta_pct"), "ci95_pct": st.get("ci95_pct")}
        if st["verdict"] == "worse":
            return {**out, **info, "action": "revert", "reason": "worse",
                    "delta_pct": st.get("delta_pct"), "ci95_pct": st.get("ci95_pct")}
        if days >= COMPARE_MAX_DAYS:
            return {**out, **info, "action": "revert", "reason": "no_clear_gain",
                    "delta_pct": st.get("delta_pct"), "ci95_pct": st.get("ci95_pct")}
        need = max(COMPARE_MIN_DAYS - days, 1)
        reason = "need_more_days" if heating else "no_heating"
        return {**out, "action": "keep" if heating else "wait_heating", "days_left": need, "reason": reason,
                "delta_pct": st.get("delta_pct"), "ci95_pct": st.get("ci95_pct")}

    base_days = qualifying_days(buckets, baseline_fp)
    if model is None or base_days < COMPARE_MIN_DAYS:
        return {**out, "action": "collecting" if heating else "wait_heating",
                "days_left": max(COMPARE_MIN_DAYS - base_days, 1),
                "reason": "baseline_needs_days" if heating else "no_heating"}
    for param in LADDER:
        if param not in current:
            continue
        tried = {}
        for gfp, st in groups.items():
            d = _only_diff(settings.get(gfp, {}), base)
            if set(d) == {param} and st.get("verdict") in ("worse", "inconclusive", "better"):
                tried[1 if d[param] > current[param] else -1] = st["verdict"]
        direction, why = _direction_from_data(model, [b for b in buckets if b[F_FP] == baseline_fp], sh_target)
        for dirn in (direction, -direction):
            if dirn in tried:
                continue
            new = _step(param, current[param], dirn)
            if new is None:
                continue
            if not heating:
                return {**out, "action": "wait_heating", "param": param, "from": current[param], "to": new,
                        "reason": "no_heating"}
            return {**out, "action": "change", "param": param, "from": current[param], "to": new,
                    "not_before": now, "days_left": COMPARE_MIN_DAYS,
                    "reason": why if dirn == direction else "other_direction_tried"}
    return {**out, "action": "done", "reason": "all_steps_tried"}


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
        ok = (running and steady and self.run_start is not None
              and now - self.run_start >= WARMUP_S
              and all(s.get(k) is not None for k in SAMPLE_KEYS)
              and s["q"] > 0 and s["p"] >= MIN_ELEC_W)
        if ok:
            self.acc.append(s)
        else:
            self.tainted = True
        return closed, started

    def _close(self) -> list | None:
        if self.tainted or len(self.acc) < MIN_SAMPLES or self.key is None:
            return None
        n = len(self.acc)

        def avg(k):
            return sum(x[k] for x in self.acc) / n

        sh = [x["sh"] for x in self.acc if x.get("sh") is not None]
        eev = [x["eev"] for x in self.acc if x.get("eev") is not None]
        return [self.key * BUCKET_S, round(avg("hz"), 2), round(avg("t_out"), 2), round(avg("t_flow"), 2),
                round(avg("q"), 1), round(avg("p"), 1),
                round(sum(sh) / len(sh), 2) if sh else None,
                round(sum(eev) / len(eev), 1) if eev else None, self.acc[0]["fp"]]


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
        self.advice: dict = {"action": "none", "reason": "settings_unknown"}
        self.builder = BucketBuilder()
        self.model: dict | None = None
        self.groups: dict = {}
        self.hint_list: list[str] = ["collecting"]
        self.recent: dict | None = None
        self.sh_target: float | None = None
        self._last_t: float | None = None

    def to_dict(self, now: float) -> dict:
        return {"buckets": self.buckets, "settings": self.settings, "current": self.current,
                "baseline_fp": self.baseline_fp, "starts": self.starts, "run_hours": self.run_hours,
                "changes": self.changes, "saved_at": now}

    def current_fp(self) -> str:
        fp = fingerprint(self.current)
        if self.current and fp not in self.settings:
            self.settings[fp] = dict(self.current)
        return fp

    def update_settings(self, settings: dict, now: float | None = None) -> dict | None:
        """Merge a settings snapshot; returns the change record when a known value moved."""
        new = {k: v for k, v in settings.items() if v is not None}
        diff = {k: [self.current[k], v] for k, v in new.items() if k in self.current and self.current[k] != v}
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
        """Feed one poll; True when a bucket closed (time to refresh and save)."""
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
        self.starts = [t for t in self.starts if now - t <= DAY_S]
        floor = int(now // 3600) - 24
        self.run_hours = {h: s for h, s in self.run_hours.items() if int(h) > floor}
        if closed is None:
            return False
        self.buckets.append(closed)
        del self.buckets[:-MAX_BUCKETS]
        return True

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
        """Recompute model, comparison and hints (CPU-bound: run in an executor)."""
        buckets = list(self.buckets)
        settings, current = dict(self.settings), dict(self.current)
        model, groups = (None, {}) if self.baseline_fp is None else compare(buckets, self.baseline_fp)
        recent = None
        if model:
            r = [x for _, x in ratios(model, [b for b in buckets if now - b[F_T] <= DAY_S])]
            if r:
                recent = {"index_pct": round(100 * sum(r) / len(r), 1), "buckets": len(r)}
        hint_list = hints(model, buckets, len(self.starts), sum(self.run_hours.values()), self.sh_target, now)
        last = self.last_change()
        advice = advise(buckets=buckets, groups=groups, settings=settings, current=current,
                        baseline_fp=self.baseline_fp, changes=[last] if last else [], model=model,
                        hint_list=hint_list, sh_target=self.sh_target, now=now)
        self.model, self.groups, self.recent, self.hint_list, self.advice = model, groups, recent, hint_list, advice

    def expected_cop(self, hz, t_out, t_flow) -> float | None:
        if self.model is None or hz is None or t_out is None or t_flow is None or hz <= 0:
            return None
        return predict(self.model, hz, t_out, t_flow)

    def describe(self, fp: str) -> str:
        """Settings that differ from the baseline, e.g. 'E02=3.0'."""
        if fp == self.baseline_fp:
            return "baseline"
        cur, base = self.settings.get(fp, {}), self.settings.get(self.baseline_fp or "", {})
        diff = [f"{k}={v}" for k, v in sorted(cur.items()) if base.get(k) != v]
        return " ".join(diff) or fp
