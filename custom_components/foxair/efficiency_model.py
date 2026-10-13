"""Weather-normalised COP model over steady 10-minute heating buckets."""
from __future__ import annotations

import hashlib
import json
import math
import statistics

DT_HX = 7.0
FIT_MIN_BUCKETS = 36
FIT_MIN_DAYS = 2
HOLDOUT_MAX_DAYS = 30
RIDGE = (0.0, 0.05, 0.05)
ETA_LIMITS = (0.15, 0.8)
COMPARE_MIN_DAYS = 3
DAY_S = 86400
QUALIFY_DAY_BUCKETS = 6
FLOW_MATCH_K = 2.0
FLOW_MIN_N = 6
FLOW_REF_DAYS = 14

F_T, F_HZ, F_TOUT, F_TFLOW, F_Q, F_P, F_SH, F_EEV, F_FP, F_FAN = range(10)


def carnot_cop(t_flow: float, t_out: float) -> float:
    """Ideal heating COP with a fixed heat-exchanger approach."""
    return (t_flow + 273.15) / max(t_flow - t_out + DT_HX, 5.0)


def features(hz: float, t_out: float) -> list[float]:
    """Steady efficiency-factor regressors (scaled)."""
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


def flow_shift(buckets: list[list], now: float) -> dict | None:
    """Last 24 h flow temperature and COP against earlier buckets at the same outdoor temperature."""
    recent = [b for b in buckets if now - b[F_T] <= DAY_S]
    ref = [b for b in buckets if DAY_S < now - b[F_T] <= FLOW_REF_DAYS * DAY_S]
    pairs = []
    for b in recent:
        m = [r for r in ref if abs(r[F_TOUT] - b[F_TOUT]) <= FLOW_MATCH_K]
        if len(m) >= 3:
            pairs.append((b[F_TFLOW] - statistics.median(r[F_TFLOW] for r in m),
                          bucket_cop(b) / statistics.median(bucket_cop(r) for r in m)))
    if len(pairs) < FLOW_MIN_N:
        return None
    return {"delta_k": round(statistics.median(p[0] for p in pairs), 1),
            "cop_pct": round(100 * (statistics.median(p[1] for p in pairs) - 1), 1), "buckets": len(pairs)}


def qualifying_days(buckets: list[list], fp: str) -> int:
    """Days with enough steady heating buckets for one settings group."""
    per: dict[int, int] = {}
    for b in buckets:
        if b[F_FP] == fp:
            per[day_of(b[F_T])] = per.get(day_of(b[F_T]), 0) + 1
    return sum(1 for n in per.values() if n >= QUALIFY_DAY_BUCKETS)
