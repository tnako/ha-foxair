"""Efficiency analyser state: live buckets and defrosts, settings log, persistence, refresh."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .efficiency_advisor import LADDER, MIN_HOLD_S, STATES, advise, defrost_summary, hints, summary
from .efficiency_autotest import Autotest, legacy_origin
from .efficiency_history import (comparisons, compare_daily, daily_ratio, day_cop, day_problems, full_days,
                                 last_measured, predict_daily, settled, tag_settings)
from .efficiency_model import DAY_S, F_FP, F_T, compare, fingerprint, flow_shift, predict, ratios

__all__ = ["LADDER", "STATES", "EfficiencyAnalyser", "defrost_summary"]

BUCKET_S = 600
MIN_SAMPLES = 12
WARMUP_S = 600
MIN_ELEC_W = 150.0
MAX_BUCKETS = 5000
MAX_GAP_S = 120
MAX_CHANGES = 200
MAX_DEFROSTS = 800
RUN_STATUS_DEFROST = 2
SAMPLE_KEYS = ("hz", "t_out", "t_flow", "q", "p")


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
        self.tracked_since: float | None = data.get("tracked_since")
        if self.tracked_since is None and self.current:
            self.tracked_since = min([c["t"] for c in self.changes if c.get("t") is not None]
                                     + [b[F_T] for b in self.buckets] + [data.get("saved_at") or time.time()])
        self.days: list[dict] = []
        self.history_tz = timezone.utc
        self.history_sources: dict = {}
        self.defrosts: list[dict] = list(data.get("defrosts", []))
        self.defrost_tracker = DefrostTracker(data.get("defrost_state"))
        self.builder = BucketBuilder()
        self.model: dict | None = None
        self.groups: dict = {}
        self.day_model: dict | None = None
        self.day_groups: dict = {}
        self.comparison: dict = {}
        self.hint_list: list[str] = ["collecting"]
        self.recent: dict | None = None
        self.advice: dict = dict(data.get("advice") or {"action": "none", "reason": "settings_unknown"})
        self.sh_target: float | None = None
        self.flow: dict | None = None
        self._last_t: float | None = None
        self.origin: dict = dict(data["origin"]) if "origin" in data else legacy_origin(self.changes)
        self.autotest = Autotest(data.get("autotest"))

    def to_dict(self, now: float) -> dict:
        return {"buckets": self.buckets, "settings": self.settings, "current": self.current,
                "baseline_fp": self.baseline_fp, "starts": self.starts, "run_hours": self.run_hours,
                "changes": self.changes, "defrosts": self.defrosts, "tracked_since": self.tracked_since,
                "defrost_state": self.defrost_tracker.state(), "saved_at": now, "advice": self.advice,
                "origin": self.origin, "autotest": self.autotest.to_dict()}

    def set_days(self, rows: list[dict], tz) -> None:
        """Daily rows rebuilt from recorder statistics (local days); called by the runtime."""
        self.days, self.history_tz = rows, tz

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
        for e in self.defrosts:
            if e.get("fp") == old:
                e["fp"] = new
        for c in self.changes:
            for k in ("from", "to"):
                if c.get(k) == old:
                    c[k] = new
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

    def update_settings(self, settings: dict, now: float | None = None, by: str | None = None) -> dict | None:
        """Merge a settings snapshot; returns the change record when a known value moved."""
        new = {k: v for k, v in settings.items() if v is not None}
        diff = {k: [self.current[k], v] for k, v in new.items() if k in self.current and self.current[k] != v}
        added = {k: v for k, v in new.items() if k not in self.current}
        if added and self.current:
            self._extend(added)
            self.current.update(added)
        old_fp = self.current_fp() if self.current else None
        self.current.update(new)
        stamp = time.time() if now is None else now
        if self.current and self.tracked_since is None:
            self.tracked_since = stamp
        if self.baseline_fp is None and self.current:
            self.baseline_fp = self.current_fp()
        if not diff:
            return None
        rec = {"t": stamp, "kind": "change", "diff": diff, "from": old_fp, "to": self.current_fp()}
        if by:
            rec["by"] = by
            for k, (old, _) in diff.items():
                self.origin.setdefault(k, old)
        self.changes.append(rec)
        del self.changes[:-MAX_CHANGES]
        return rec

    def undo_targets(self) -> dict:
        """Settings EEF wrote that differ from their value before EEF's first write: {code: (now, before)}."""
        return {k: (self.current.get(k), v) for k, v in self.origin.items()
                if self.current.get(k) is not None and self.current.get(k) != v}

    def reset_tests(self, now: float) -> None:
        """Forget every test: steady buckets, settings groups, change log, autotest and the EEF origin; the current
        settings become the reference. Defrost and start history stay (findings, not tests); recorder days before
        now lose their settings tag, so the daily comparison restarts too."""
        self.buckets, self.settings = [], {}
        self.baseline_fp = self.current_fp() if self.current else None
        self.changes = [{"t": now, "kind": "reset", "from": None, "to": self.baseline_fp}]
        self.tracked_since = now
        self.origin, self.autotest, self.builder = {}, Autotest(), BucketBuilder()
        self.model, self.groups, self.day_model, self.day_groups, self.recent = None, {}, None, {}, None
        self.advice = {"action": "none", "reason": "settings_unknown"}

    def observe(self, now: float, sample: dict) -> bool:
        """Feed one poll; True when a bucket or defrost closed (time to refresh and save)."""
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
        event, _ = self.defrost_tracker.add(now, sample)
        self.starts = [t for t in self.starts if now - t <= DAY_S]
        floor = int(now // 3600) - 24
        self.run_hours = {h: s for h, s in self.run_hours.items() if int(h) > floor}
        if event:
            self.defrosts.append(event)
            del self.defrosts[:-MAX_DEFROSTS]
        if closed is not None:
            self.buckets.append(closed)
            del self.buckets[:-MAX_BUCKETS]
        return closed is not None or bool(event)

    def set_baseline(self, now: float | None = None) -> None:
        old = self.baseline_fp
        self.baseline_fp = self.current_fp()
        if old != self.baseline_fp:
            self.changes.append({"t": time.time() if now is None else now, "kind": "baseline",
                                 "from": old, "to": self.baseline_fp})
            del self.changes[:-MAX_CHANGES]

    def last_change(self) -> dict | None:
        """Latest settings change that stuck; one undone within 30 minutes is no change."""
        log = settled(self.changes)
        return log[-1] if log else None

    def tagged_days(self) -> list[dict]:
        return tag_settings(self.days, settled(self.changes), self.current_fp() if self.current else None,
                            self.tracked_since, self.history_tz)

    def refresh(self, now: float) -> None:
        """Recompute models, comparisons, hints and advice (CPU-bound: run in an executor)."""
        buckets, defrosts = list(self.buckets), list(self.defrosts)
        days = self.tagged_days()
        today = datetime.fromtimestamp(now, self.history_tz).date()
        settings, current = dict(self.settings), dict(self.current)
        model, groups, day_model, day_groups = None, {}, None, {}
        if self.baseline_fp is not None:
            model, groups = compare(buckets, self.baseline_fp)
            day_model, day_groups = compare_daily(full_days(days, today), self.baseline_fp)
        recent = None
        if model:
            r = [x for _, x in ratios(model, [b for b in buckets if now - b[F_T] <= DAY_S])]
            if r:
                recent = {"index_pct": round(100 * sum(r) / len(r), 1), "buckets": len(r)}
        flow = flow_shift(buckets, now)
        hint_list = hints(model, buckets, len(self.starts), sum(self.run_hours.values()), self.sh_target, now,
                          current, defrosts, flow, "flow_higher" in self.hint_list)
        last = self.last_change()
        at = self.autotest
        if at.running:
            advice = {"action": "autotest", "reason": "autotest"}
        else:
            advice = advise(buckets=buckets, groups=groups, settings=settings, current=current,
                            baseline_fp=self.baseline_fp, changes=[last] if last else [], model=model,
                            hint_list=hint_list, sh_target=self.sh_target, now=now,
                            day_rows=full_days(days, today), day_groups=day_groups, day_model=day_model,
                            defrosts=defrosts, skip=("E02",) if at.stage == "done" else ())
        prev = self.advice
        if (advice.get("action") == "change" and prev.get("since")
                and all(prev.get(k) == advice.get(k) for k in ("action", "param", "from", "to"))):
            advice["since"] = prev["since"]
        fp = fingerprint(current) if current else None
        if model and fp and fp not in groups:
            settling = last is not None and last.get("to") == fp and now - last["t"] < MIN_HOLD_S
            groups[fp] = {"buckets": 0, "days": 0, "delta_pct": None, "ci95_pct": None,
                          "verdict": "settling" if settling else "collecting"}
        self.model, self.groups, self.recent, self.hint_list, self.advice = model, groups, recent, hint_list, advice
        self.day_model, self.day_groups, self.flow = day_model, day_groups, flow
        self.comparison = comparisons(days, today)

    def status(self, now: float, tz=timezone.utc) -> dict:
        group = self.describe(self.current_fp()) if self.current and self.baseline_fp else None
        at = self.autotest.status(now, tz)
        st = summary(self.advice, self.hint_list, self.flow, group, now,
                     at["message"] if at and self.autotest.running else None)
        if at and self.autotest.running:
            st.update(next_check=at["until"], estimated=False)
        elif at and at["message"]:
            if at["problem"]:
                st.update(state="problem", message=f"{at['message']} Also: {st['message']}")
            else:
                st["message"] = f"{at['message']} {st['message']}"
        st["autotest"] = at
        return st

    def expected_cop(self, hz, t_out, t_flow) -> float | None:
        if self.model is None or hz is None or t_out is None or t_flow is None or hz <= 0:
            return None
        return predict(self.model, hz, t_out, t_flow)

    def last_day(self, now: float | None = None) -> dict:
        """Latest full local day with a trustworthy COP; `comparable` is False when settings changed or were unknown."""
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now, self.history_tz).date()
        row, skipped = last_measured(self.tagged_days(), today)
        out: dict = {"days_recorded": len(full_days(self.days, today))}
        if skipped:
            out["last_day_skipped"] = skipped
        if row is None:
            return out
        why = day_problems(row)
        out.update({"day": row["day"], "cop": round(day_cop(row), 2), "heat_kwh": row["heat_total"],
                    "elec_kwh": row["elec"], "t_out": row["t_out"], "t_in": row.get("t_in"),
                    "t_flow": row["t_flow"], "fp": row["fp"], "comparable": not why})
        if why:
            out["not_comparable_why"] = why
        elif self.day_model:
            out["expected_cop"] = round(predict_daily(self.day_model, row), 2)
            out["index_pct"] = round(100 * daily_ratio(self.day_model, row), 1)
        return out

    def describe(self, fp: str) -> str:
        """Settings that differ from the baseline, e.g. 'E02=3.0'."""
        if fp == self.baseline_fp:
            return "baseline"
        cur, base = self.settings.get(fp, {}), self.settings.get(self.baseline_fp or "", {})
        diff = [f"{k}={v}" for k, v in sorted(cur.items()) if base.get(k) != v]
        return " ".join(diff) or fp
