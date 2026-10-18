"""E02 autotest: a few E02 values take turns every day, judged on whole-block COP within the same days."""
from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

from .efficiency_advisor import LADDER
from .efficiency_model import _solve, carnot_cop

PARAM = "E02"
FACTORY = 5.0
COARSE = (4.0, 5.0, 6.0, 7.0)
OLD_COARSE = ((3.0, 4.0, 5.0, 6.0),)
LIMITS = (LADDER[PARAM]["min"], LADDER[PARAM]["max"])
FINE_STEP = LADDER[PARAM]["step"]
SETTLE_S = 3600
MIN_RUN_S = 7200
MAX_HEATER_S = 600
STAGE_DAYS = 10
STAGE_MAX_DAYS = 14
MIN_BLOCKS = 5
MAX_GAP_S = 120
NOTE_S = 86400
RIDGE = 1e-6
RS_DHW = (3, 4)
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23,
       12: 2.18, 15: 2.13, 20: 2.09, 25: 2.06, 30: 2.04, 40: 2.02, 60: 2.00, 120: 1.98}
STOP_TEXT = {"user": "switched off", "write_failed": f"writing {PARAM} failed",
             "manual_change": f"{PARAM} was changed by hand", "short_cycling": "short cycling",
             "no_heating": "too little heating to judge", "undo": "undo pressed"}
PROBLEM_STOPS = ("write_failed", "short_cycling")


def t95(dof: int) -> float:
    """Two-sided 95 % Student t, rounded towards the next smaller tabulated dof (never too narrow)."""
    return T95[max(k for k in T95 if k <= dof)] if dof >= 1 else math.inf


def day_order(arms: list[float], seed: int, day: int) -> list[float]:
    """Values per slot for one local day; every n days form a Latin square, reshuffled each cycle."""
    n = len(arms)
    cycle, row = divmod(day, n)
    rng = random.Random(f"{seed}:{cycle}")
    symbols = list(arms)
    rng.shuffle(symbols)
    rows = list(range(n))
    rng.shuffle(rows)
    return [symbols[(slot + rows[row]) % n] for slot in range(n)]


def slot_at(now: float, tz, start_day: date, n: int) -> tuple[int, int, float, float]:
    """(day index, slot, block start, block end) of the local-time block holding `now`."""
    local = datetime.fromtimestamp(now, tz)
    hours = 24 // n
    slot = min(local.hour // hours, n - 1)
    midnight = datetime.combine(local.date(), datetime.min.time(), tz)
    start = midnight + timedelta(hours=slot * hours)
    end = midnight + timedelta(hours=(slot + 1) * hours) if slot < n - 1 else \
        datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), tz)
    return (local.date() - start_day).days, slot, start.timestamp(), end.timestamp()


def block_score(b: dict) -> float | None:
    """log(block COP / Carnot COP of its running time); None when the block can't be judged."""
    if b["cooling"] or b["run_s"] < MIN_RUN_S or b["heater_s"] > MAX_HEATER_S:
        return None
    if min(b["heat_wh"], b["elec_wh"], b["elec_run_wh"], b["ideal_wh"]) <= 0:
        return None
    return math.log(b["heat_wh"] / b["elec_wh"]) - math.log(b["ideal_wh"] / b["elec_run_wh"])


def analyse(blocks: list[dict], arms: list[float], ref: float, skip_days=()) -> dict:
    """Per value: judged blocks and COP % against `ref` with a 95 % interval, fitted with day and slot effects."""
    rows = [(b["day"], b["slot"], b["arm"], s) for b in blocks
            if b["arm"] in arms and b["day"] not in skip_days and (s := block_score(b)) is not None]
    per_day: dict[int, set] = {}
    for d, _, a, _ in rows:
        per_day.setdefault(d, set()).add(a)
    rows = [r for r in rows if len(per_day[r[0]]) >= 2]
    out = {a: {"value": a, "blocks": sum(1 for r in rows if r[2] == a), "delta_pct": None, "ci95_pct": None}
           for a in arms}
    if not out[ref]["blocks"]:
        return out
    out[ref]["delta_pct"] = 0.0
    others = [a for a in arms if a != ref and out[a]["blocks"]]
    days, slots = sorted({r[0] for r in rows}), sorted({r[1] for r in rows})
    cols = [(0, d) for d in days[1:]] + [(1, s) for s in slots[1:]] + [(2, a) for a in others]
    x = [[1.0] + [1.0 if r[k] == v else 0.0 for k, v in cols] for r in rows]
    y = [r[3] for r in rows]
    p = len(cols) + 1
    xtx = [[sum(row[j] * row[k] for row in x) + (RIDGE if j == k and j else 0.0) for k in range(p)]
           for j in range(p)]
    beta = _solve(xtx, [sum(row[j] * yi for row, yi in zip(x, y)) for j in range(p)])
    if beta is None:
        return out
    dof = len(rows) - p
    sd = None
    if dof >= 1:
        res = [yi - sum(b * v for b, v in zip(beta, row)) for row, yi in zip(x, y)]
        sd = math.sqrt(sum(r * r for r in res) / dof)
    for j, (k, a) in enumerate(cols, start=1):
        if k != 2:
            continue
        out[a]["delta_pct"] = round(100 * (math.exp(beta[j]) - 1), 1)
        inv = _solve(xtx, [1.0 if i == j else 0.0 for i in range(p)]) if sd is not None else None
        if sd is not None and inv and inv[j] > 0:
            out[a]["ci95_pct"] = round(100 * t95(dof) * sd * math.sqrt(inv[j]), 1)
    return out


def pick(res: dict, ref: float) -> float:
    """The value clearly better than `ref` (whole interval above zero), else `ref`."""
    clear = [r for a, r in res.items() if a != ref and r["delta_pct"] is not None and r["ci95_pct"] is not None
             and r["delta_pct"] - r["ci95_pct"] > 0]
    return max(clear, key=lambda r: r["delta_pct"])["value"] if clear else ref


def legacy_origin(changes: list[dict]) -> dict:
    """E02 before the first Apply-shaped change (only E02, one ladder step) in a log from before origin tracking."""
    for c in changes:
        d = c.get("diff") or {}
        if c.get("kind") == "change" and set(d) == {PARAM} and None not in d[PARAM] \
                and abs(abs(d[PARAM][1] - d[PARAM][0]) - FINE_STEP) < 1e-6:
            return {PARAM: d[PARAM][0]}
    return {}


def _fmt(v) -> str:
    return "?" if v is None else f"{v:g}"


class Autotest:
    """Schedule, block energy totals and stage decisions; the runtime does the writes."""

    def __init__(self, data: dict | None = None):
        d = data or {}
        self.stage: str | None = d.get("stage")
        self.arms: list[float] = [float(a) for a in d.get("arms", [])]
        if d.get("stage") == "coarse" and tuple(self.arms) in OLD_COARSE:
            self.arms = list(COARSE)
        self.ref: float = float(d.get("ref") or FACTORY)
        self.seed: int = int(d.get("seed") or 0)
        self.start_day: str = d.get("start_day") or "1970-01-01"
        self.start_value: float | None = d.get("start_value")
        self.blocks: list[dict] = list(d.get("blocks", []))
        self.mixed: list[int] = list(d.get("mixed", []))
        self.checked_day: int = int(d.get("checked_day") or 0)
        self.acc: dict | None = d.get("acc")
        self.coarse: dict | None = d.get("coarse")
        self.result: dict = dict(d.get("result") or {})
        self.pending: float | None = d.get("pending")
        self.expected: float | None = d.get("expected")
        self.since: float | None = d.get("since")
        self._last_t: float | None = None
        self._cache: tuple | None = None

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("stage", "arms", "ref", "seed", "start_day", "start_value", "blocks",
                                               "mixed", "checked_day", "acc", "coarse", "result", "pending",
                                               "expected", "since")}

    @property
    def running(self) -> bool:
        return self.stage in ("coarse", "fine")

    def start(self, now: float, tz, value: float) -> None:
        self.__init__({"stage": "coarse", "arms": list(COARSE), "ref": FACTORY, "seed": int(now),
                       "start_day": datetime.fromtimestamp(now, tz).date().isoformat(), "start_value": value})

    def stop(self, reason: str, now: float, restore: bool = True) -> None:
        self.result = {"stopped": reason, "t": now, "stage": self.stage, "restore": restore}
        self.pending = self.start_value if restore else None
        self.stage, self.acc = "stopped", None

    def _slot(self, now: float, tz) -> tuple[int, int, float, float, float]:
        day, slot, t0, t1 = slot_at(now, tz, date.fromisoformat(self.start_day), len(self.arms))
        return day, slot, t0, t1, day_order(self.arms, self.seed, day)[slot]

    def want(self, now: float, tz) -> float | None:
        """The E02 value the pump should hold now, or None when the autotest has nothing to write."""
        return self._slot(now, tz)[4] if self.running else self.pending

    def wrote(self, value: float, now: float, written: bool = True) -> bool:
        """Record that the pump holds `value`; True when that finished the autotest (time to set the baseline)."""
        if self.running:
            self.expected = value
            if written:
                self.since = now
            return False
        self.pending = None
        return self.stage == "done"

    def restore_failed(self) -> None:
        self.result["restore_failed"] = True
        self.pending = None

    def mark_mixed(self, now: float, tz) -> None:
        """Other settings changed: the day's blocks no longer compare like with like."""
        if self.running:
            day = self._slot(now, tz)[0]
            if day not in self.mixed:
                self.mixed.append(day)

    def results(self) -> list[dict]:
        if not self.running:
            return []
        key = (len(self.blocks), tuple(self.arms), self.ref, len(self.mixed))
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, list(analyse(self.blocks, self.arms, self.ref, self.mixed).values()))
        return self._cache[1]

    def observe(self, now: float, sample: dict, tz, e02_now: float | None) -> bool:
        """Feed one poll; True when a block closed or the stage changed."""
        if not self.running:
            return False
        dt = now - self._last_t if self._last_t is not None and 0 < now - self._last_t <= MAX_GAP_S else 0.0
        self._last_t = now
        day, slot, t0, _, arm = self._slot(now, tz)
        changed = False
        if self.acc and (self.acc["day"], self.acc["slot"]) != (day, slot):
            self.blocks.append(self.acc)
            self.acc, changed = None, True
        if day >= STAGE_DAYS and day > self.checked_day:
            self.checked_day = day
            if self._finish(day, now, tz):
                return True
        if e02_now is None or round(e02_now, 1) != arm or now < max(t0, self.since or t0) + SETTLE_S:
            return changed
        if self.acc is None:
            self.acc = {"day": day, "slot": slot, "arm": arm, "heat_wh": 0.0, "elec_wh": 0.0, "elec_run_wh": 0.0,
                        "ideal_wh": 0.0, "run_s": 0.0, "heater_s": 0.0, "dhw_s": 0.0, "cooling": False}
        a = self.acc
        if sample.get("rs") in RS_DHW:
            a["dhw_s"] += dt
            return changed
        a["cooling"] = a["cooling"] or bool(sample.get("cooling"))
        if sample.get("heater"):
            a["heater_s"] += dt
        p, q, tf, to = (sample.get(k) for k in ("p_day", "q_day", "t_flow", "t_out"))
        if p is not None:
            a["elec_wh"] += p * dt / 3600
        if q is not None:
            a["heat_wh"] += q * dt / 3600
        if sample.get("running") and p and tf is not None and to is not None:
            a["run_s"] += dt
            a["elec_run_wh"] += p * dt / 3600
            a["ideal_wh"] += p * carnot_cop(tf, to) * dt / 3600
        return changed

    def _finish(self, day: int, now: float, tz) -> bool:
        """At a day change from STAGE_DAYS on: move to the fine stage, finish, or keep collecting."""
        res = analyse(self.blocks, self.arms, self.ref, self.mixed)
        full = all(r["blocks"] >= MIN_BLOCKS and r["delta_pct"] is not None for r in res.values())
        if not full and day < STAGE_MAX_DAYS:
            return False
        if res[self.ref]["delta_pct"] is None or not any(r["delta_pct"] is not None for a, r in res.items()
                                                         if a != self.ref):
            self.stop("no_heating", now)
            return True
        best = pick(res, self.ref)
        done = {"arms": self.arms, "ref": self.ref, "best": best, "days": day, "results": list(res.values())}
        if self.stage == "coarse":
            lo, hi = LIMITS
            self.coarse, self.stage, self.ref = done, "fine", best
            self.arms = sorted({round(min(max(best + d * FINE_STEP, lo), hi), 1) for d in (-1, 0, 1)})
            self.seed += 1
            self.start_day = datetime.fromtimestamp(now, tz).date().isoformat()
            self.blocks, self.mixed, self.checked_day, self.acc = [], [], 0, None
        else:
            self.result = {"value": best, "fine": done, "t": now}
            self.stage, self.pending, self.acc = "done", best, None
        return True

    def status(self, now: float, tz) -> dict | None:
        """What the status sensor and the dashboard show; `message` is None once a stop note is old."""
        if self.stage is None:
            return None
        out = {"stage": self.stage, "arms": self.arms, "ref": self.ref, "start_value": self.start_value,
               "coarse": self.coarse, "result": self.result or None, "message": None, "until": None,
               "problem": self.stage == "stopped" and (self.result.get("stopped") in PROBLEM_STOPS
                                                       or bool(self.result.get("restore_failed")))}
        if self.running:
            day, _, _, t1, arm = self._slot(now, tz)
            hours = 24 // len(self.arms)
            n = "1" if self.stage == "coarse" else "2"
            days = STAGE_DAYS if day < STAGE_DAYS else STAGE_MAX_DAYS
            out.update(value_now=arm, until=t1, day=day + 1, days=days, block_h=hours, results=self.results())
            out["message"] = (f"Autotest {PARAM}, stage {n} of 2, day {day + 1} of {days}: now {PARAM}="
                              f"{_fmt(arm)} until {datetime.fromtimestamp(t1, tz).strftime('%H:%M')}. "
                              f"{' / '.join(_fmt(a) for a in self.arms)} take turns, {hours} h each per day.")
        elif self.stage == "done":
            r = self.result["fine"]
            others = ", ".join(f"{_fmt(x['value'])}: {_fmt(x['delta_pct'])} % ± {_fmt(x['ci95_pct'])} %"
                               for x in r["results"] if x["value"] != r["ref"])
            why = "clearly better" if self.result["value"] != r["ref"] else "no value was clearly better"
            out["message"] = (f"Autotest finished: {PARAM}={_fmt(self.result['value'])} kept ({why}). "
                              f"Against {_fmt(r['ref'])}: {others}.")
        elif self.stage == "stopped" and now - self.result["t"] < NOTE_S:
            why = self.result["stopped"]
            if self.result.get("restore_failed"):
                back = f"Setting {PARAM} back to {_fmt(self.start_value)} failed, set it by hand."
            elif self.result.get("restore"):
                back = f"{PARAM} set back to {_fmt(self.start_value)}."
            else:
                back = f"{PARAM} left as it is."
            out["message"] = f"Autotest stopped ({STOP_TEXT.get(why, why)}). {back}"
        return out
