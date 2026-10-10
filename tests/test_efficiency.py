#!/usr/bin/env python3
"""Efficiency analyser: steady buckets, weather-normalised COP model, settings comparison.

Run: pytest tests/test_efficiency.py -v
"""
import importlib.util
import math
import pathlib
import random

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("foxair_efficiency_test", ROOT / "custom_components/foxair/efficiency.py")
eff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eff)

DAY = 86400


def synthetic_cop(hz, t_out, t_flow, factor=1.0):
    return factor * (0.5 - 0.002 * hz / 50 - 0.06 * t_out / 10) * eff.carnot_cop(t_flow, t_out)


def bucket(t, fp, factor=1.0, rng=None, sh=5.0):
    rng = rng or random.Random(int(t))
    hz = rng.uniform(30, 60)
    t_out = rng.uniform(-8, 14)
    t_flow = 45 - 0.6 * t_out + rng.uniform(-1, 1)
    p = 400 + 15 * hz
    cop = synthetic_cop(hz, t_out, t_flow, factor) * (1 + rng.gauss(0, 0.02))
    return [t, hz, t_out, t_flow, cop * p, p, sh, 150.0, fp]


def days_of(fp, start_day, n_days, factor=1.0, per_day=12, seed=1):
    rng = random.Random(seed)
    return [bucket((start_day + d) * DAY + 3600 * h, fp, factor, rng)
            for d in range(n_days) for h in range(per_day)]


def test_carnot_and_fingerprint_are_stable():
    assert math.isclose(eff.carnot_cop(35.0, 7.0), 308.15 / 35.0)
    assert eff.carnot_cop(10.0, 20.0) == 283.15 / 5.0
    assert eff.fingerprint({"E02": 3.5, "E01": 1}) == eff.fingerprint({"E01": 1, "E02": 3.5})
    assert eff.fingerprint({"E02": 3.5}) != eff.fingerprint({"E02": 3.0})
    assert eff.fingerprint({}) == "none"


def test_fit_needs_enough_buckets_and_days():
    one_day = [bucket(600 * i, "a") for i in range(60)]
    assert eff.fit(one_day) is None
    assert eff.fit(days_of("a", 0, 2, per_day=10)) is None
    model = eff.fit(days_of("a", 0, 4))
    assert model and model["mape_pct"] < 4


def test_model_removes_weather_so_a_change_is_measured_on_different_days():
    base = days_of("base", 0, 8, seed=1)
    worse = days_of("test", 8, 5, factor=0.93, seed=2)
    model, groups = eff.compare(base + worse, "base")
    assert model
    g = groups["test"]
    assert g["days"] == 5 and -9.5 < g["delta_pct"] < -4.5
    assert g["verdict"] == "worse"
    assert groups["base"]["verdict"] == "baseline"
    assert abs(groups["base"]["delta_pct"]) < 2


def test_same_settings_on_new_days_is_not_reported_as_a_change():
    base = days_of("base", 0, 8, seed=3)
    same = days_of("again", 8, 5, factor=1.0, seed=4)
    _, groups = eff.compare(base + same, "base")
    assert groups["again"]["verdict"] in ("inconclusive", "better", "worse")
    assert abs(groups["again"]["delta_pct"]) < 2
    assert groups["again"]["verdict"] == "inconclusive" or abs(groups["again"]["delta_pct"]) > groups["again"]["ci95_pct"]


def test_two_days_are_still_collecting():
    base = days_of("base", 0, 6)
    _, groups = eff.compare(base + days_of("new", 6, 2, factor=0.8), "base")
    assert groups["new"]["verdict"] == "collecting"


def poll(running=True, hz=40.0, q=3000.0, p=700.0, fp_ok=True, steady=True):
    return {"running": running, "steady_ok": steady, "hz": hz, "t_out": 5.0, "t_flow": 35.0, "q": q, "p": p,
            "sh": 5.0, "eev": 120.0, "fp": "x" if fp_ok else "y"}


def feed(builder, t0, seconds, **kw):
    out = []
    for t in range(t0, t0 + seconds, 30):
        b, _ = builder.add(t, poll(**kw))
        if b:
            out.append(b)
    return out


def test_bucket_builder_skips_warmup_defrost_and_settings_changes():
    bb = eff.BucketBuilder()
    t0 = 6000 * 100
    got = feed(bb, t0, 2430)
    assert len(got) == 3 and got[0][0] == t0 + 600 and got[0][0] >= t0 + eff.WARMUP_S
    assert got[0][eff.F_HZ] == 40.0 and got[0][eff.F_FP] == "x"
    bb = eff.BucketBuilder()
    feed(bb, t0, 1500)
    feed(bb, t0 + 1500, 60, steady=False)
    assert feed(bb, t0 + 1560, 1200) == []
    bb = eff.BucketBuilder()
    feed(bb, t0, 1500)
    feed(bb, t0 + 1500, 60, fp_ok=False)
    assert feed(bb, t0 + 1560, 1200) == []


def test_bucket_builder_rejects_low_power_and_missing_values():
    bb = eff.BucketBuilder()
    assert feed(bb, 600000, 2400, p=100.0) == []
    bb = eff.BucketBuilder()
    assert feed(bb, 600000, 2400, hz=None) == []


def test_bucket_builder_keeps_window_when_compressor_stops_or_warms_up_inside():
    # 20-40 min runs (mild weather): the stop or the warm-up in the same window must not drop its steady part
    bb = eff.BucketBuilder()
    t0 = 6000 * 100
    got = feed(bb, t0 + 120, 1560)          # start at 2 min, steady from 12 min, stop at 28 min
    got += feed(bb, t0 + 1680, 1200, running=False)
    assert [b[0] for b in got] == [t0 + 600, t0 + 1200]
    bb = eff.BucketBuilder()
    feed(bb, t0, 900)
    feed(bb, t0 + 900, 60, steady=False)     # defrost inside a window still drops it
    assert all(b[0] != t0 + 600 for b in feed(bb, t0 + 960, 1200))


def test_analyser_tracks_baseline_and_persists():
    a = eff.EfficiencyAnalyser()
    a.update_settings({"E02": 3.5})
    assert a.baseline_fp == eff.fingerprint({"E02": 3.5}) and a.describe(a.current_fp()) == "baseline"
    t = 1_800_000_000
    for i in range(0, 4 * 3600, 30):
        a.observe(t + i, poll())
    base_fp = a.baseline_fp
    assert base_fp == eff.fingerprint({"E02": 3.5}) and a.buckets
    a.update_settings({"E02": 3.0})
    assert a.current_fp() != base_fp and a.describe(a.current_fp()) == "E02=3.0"
    b = eff.EfficiencyAnalyser(a.to_dict(t))
    assert b.baseline_fp == base_fp and b.buckets == a.buckets and b.current == {"E02": 3.0}
    b.set_baseline()
    assert b.baseline_fp == b.current_fp()


def test_analyser_waits_for_settings_before_bucketing():
    a = eff.EfficiencyAnalyser()
    for i in range(0, 4 * 3600, 30):
        a.observe(1_800_000_000 + i, poll())
    assert a.buckets == [] and a.baseline_fp is None


def test_short_cycling_hint_uses_starts_and_runtime():
    assert eff.hints(None, [], 30, 30 * 600, None, 0) == ["short_cycling"]
    assert eff.hints(None, [], 30, 30 * 3600, None, 0) == ["collecting"]


def test_superheat_hints():
    base = days_of("b", 0, 10)
    model = eff.fit(base)
    now = 10 * DAY
    for b in base:
        b[eff.F_SH] = 8.0
    assert "superheat_off_target" in eff.hints(model, base, 0, 0, 3.5, now)
    assert eff.hints(model, base, 0, 0, 8.0, now) == ["ok"]
    rng = random.Random(5)
    costly = []
    for b in days_of("b", 0, 10, per_day=20):
        sh = rng.uniform(3, 10)
        b[eff.F_SH] = sh
        b[eff.F_Q] *= 1 - 0.02 * (sh - 3)
        costly.append(b)
    assert "superheat_costs" in eff.hints(eff.fit(costly), costly, 0, 0, None, now)


def _adv(buckets, current, settings, baseline_fp, changes=(), now=None, hint_list=("ok",), sh_target=3.5):
    model, groups = eff.compare(buckets, baseline_fp)
    now = now if now is not None else max(b[eff.F_T] for b in buckets) + 600
    return eff.advise(buckets=buckets, groups=groups, settings=settings, current=current, baseline_fp=baseline_fp,
                      changes=list(changes), model=model, hint_list=list(hint_list), sh_target=sh_target, now=now)


BASE = {"E02": 3.5}
BFP = eff.fingerprint(BASE)


def test_advise_collects_baseline_first():
    b = days_of(BFP, 0, 2)
    a = _adv(b, BASE, {BFP: BASE}, BFP)
    assert a["action"] == "collecting" and a["days_left"] == 1


def test_advise_suggests_one_step_from_the_data():
    b = days_of(BFP, 0, 6)
    for x in b:
        x[eff.F_SH] = 6.0
    a = _adv(b, BASE, {BFP: BASE}, BFP)
    assert (a["action"], a["param"], a["from"], a["to"]) == ("change", "E02", 3.5, 3.0)
    assert a["reason"] == "superheat_above_target"


def test_advise_waits_a_day_after_any_change():
    b = days_of(BFP, 0, 6)
    now = max(x[eff.F_T] for x in b) + 600
    a = _adv(b, BASE, {BFP: BASE}, BFP, changes=[{"t": now - 3600, "kind": "change"}], now=now)
    assert a["action"] == "keep" and a["reason"] == "settling_after_change"
    assert a["not_before"] == now - 3600 + eff.MIN_HOLD_S


def test_advise_counts_test_days_then_reverts_or_accepts():
    new = {"E02": 3.0}
    nfp = eff.fingerprint(new)
    st = {BFP: BASE, nfp: new}
    base = days_of(BFP, 0, 8, seed=1)
    a = _adv(base + days_of(nfp, 8, 1, seed=2), new, st, BFP)
    assert a["action"] == "keep" and a["days_left"] == 2 and a["reason"] == "need_more_days"
    a = _adv(base + days_of(nfp, 8, 5, factor=0.92, seed=2), new, st, BFP)
    assert (a["action"], a["param"], a["from"], a["to"]) == ("revert", "E02", 3.0, 3.5)
    a = _adv(base + days_of(nfp, 8, 5, factor=1.08, seed=2), new, st, BFP)
    assert (a["action"], a["param"], a["to"]) == ("accept", "E02", 3.0)


def test_advise_tries_the_other_direction_after_a_worse_step():
    lower = {"E02": 3.0}
    lfp = eff.fingerprint(lower)
    b = days_of(BFP, 0, 8, seed=1) + days_of(lfp, 8, 5, factor=0.9, seed=2)
    for x in b:
        x[eff.F_SH] = 6.0
    a = _adv(b, BASE, {BFP: BASE, lfp: lower}, BFP)
    assert (a["action"], a["to"], a["reason"]) == ("change", 4.0, "other_direction_tried")


def test_advise_waits_for_heating_and_flags_short_cycling():
    b = days_of(BFP, 0, 6)
    later = max(x[eff.F_T] for x in b) + 5 * DAY
    assert _adv(b, BASE, {BFP: BASE}, BFP, now=later)["action"] == "wait_heating"
    assert _adv(b, BASE, {BFP: BASE}, BFP, hint_list=["short_cycling"])["action"] == "check_curve"


def test_settings_change_is_logged_once():
    a = eff.EfficiencyAnalyser()
    assert a.update_settings({"E02": 3.5}, 100) is None
    rec = a.update_settings({"E02": 3.0}, 200)
    assert rec["diff"] == {"E02": [3.5, 3.0]} and rec["t"] == 200
    assert a.update_settings({"E02": 3.0}, 300) is None
    a.set_baseline(400)
    assert [c["kind"] for c in a.changes] == ["change", "baseline"] and a.last_change()["t"] == 200
    assert eff.EfficiencyAnalyser(a.to_dict(500)).changes == a.changes


def day_row(day, fp, factor=1.0, rng=None):
    rng = rng or random.Random(day)
    t_out = rng.uniform(-8, 10)
    t_flow = 42 - 0.5 * t_out
    run = 6 + (10 - t_out) * 0.8
    cop = factor * (0.42 - 0.03 * t_out / 10 - 0.05 * run / 24) * eff.carnot_cop(t_flow, t_out) * (1 + rng.gauss(0, 0.015))
    elec = 1.2 * run
    return [day, round(cop * elec, 3), round(elec, 3), t_out, t_flow, run, 20, 5, fp, 1.0, False]


def test_daily_comparison_judges_whole_day_settings():
    base = [day_row(d, "b", rng=random.Random(d)) for d in range(10)]
    test = [day_row(d, "t", 0.92, random.Random(100 + d)) for d in range(10, 16)]
    model, groups = eff.compare_daily(base + test, "b")
    assert model and model["mape_pct"] < 4
    assert groups["t"]["verdict"] == "worse" and -10 < groups["t"]["delta_pct"] < -5
    short = [day_row(d, "s", 1.0, random.Random(200 + d)) for d in range(10, 13)]
    assert eff.compare_daily(base + short, "b")[1]["s"]["verdict"] == "collecting"


def test_daily_rows_skip_thin_mixed_and_cooling_days():
    good = day_row(1, "b")
    assert eff.day_ok(good)
    for idx, val in ((eff.R_COVER, 0.5), (eff.R_HEAT, 2.0), (eff.R_FP, "mixed"), (eff.R_COOL, True), (eff.R_RUN, 0.5)):
        bad = list(good)
        bad[idx] = val
        assert not eff.day_ok(bad)


def test_daily_accumulator_integrates_energy_and_rolls_over():
    acc = eff.DailyAccumulator()
    t0 = 10 * DAY
    for i in range(0, DAY, 30):
        on = (i // 3600) % 2 == 0
        assert acc.add(t0 + i, {"fp": "b", "running": on, "p_day": 1000.0 if on else 10.0,
                                "q_day": 3000.0 if on else None, "t_out": 2.0, "t_flow": 35.0}, False, False) is None
    row = acc.add(t0 + DAY, {"fp": "b", "running": False, "p_day": 10.0}, False, False)
    assert row[eff.R_DAY] == 10 and row[eff.R_FP] == "b"
    assert abs(row[eff.R_ELEC] - 12.12) < 0.05 and abs(row[eff.R_HEAT] - 36.0) < 0.1
    assert abs(row[eff.R_RUN] - 12.0) < 0.05 and row[eff.R_TOUT] == 2.0 and row[eff.R_COVER] > 0.99


def test_defrost_tracker_records_duration_interval_and_heating_before():
    tr = eff.DefrostTracker()
    t = 0.0
    events = []

    def run(seconds, rs, running=True):
        nonlocal t
        for _ in range(int(seconds // 30)):
            t += 30
            ev, _ = tr.add(t, {"rs": rs, "running": running, "p_day": 800.0, "t_out": -3.0, "coil": -9.0, "fp": "b"})
            if ev:
                events.append(ev)

    run(3000, 1)
    run(180, 2, running=False)
    run(2700, 1)
    run(240, 2, running=False)
    run(60, 1)
    assert len(events) == 2
    a, b = events
    assert a["dur_s"] == 180 and a["interval_s"] is None and a["coil"] == -9.0 and a["t_out"] == -3.0
    assert b["dur_s"] == 240 and b["interval_s"] == 2880 and abs(b["run_s"] - 2700) <= 30
    assert abs(b["elec_wh"] - 800 * 240 / 3600) < 5
    restored = eff.DefrostTracker(tr.state())
    assert restored.last_start == tr.last_start


def _defrosts(n, now, run_min=46, dur_s=200):
    return [{"t": now - i * 3600, "dur_s": dur_s, "run_s": run_min * 60, "interval_s": 3600, "elec_wh": 40,
             "t_out": -2, "coil": -8, "fp": "b"} for i in range(n)]


def test_defrost_on_timer_finding():
    now = 30 * DAY
    assert eff.defrost_on_timer(eff.defrost_summary(_defrosts(10, now), now, 45))
    assert not eff.defrost_on_timer(eff.defrost_summary(_defrosts(10, now, run_min=90), now, 45))
    assert not eff.defrost_on_timer(eff.defrost_summary(_defrosts(10, now, dur_s=600), now, 45))
    assert not eff.defrost_on_timer(eff.defrost_summary(_defrosts(3, now), now, 45))
    assert "defrost_on_timer" in eff.hints(None, [], 0, 0, None, now, {"D03": 45}, _defrosts(10, now))


def _with_fan(buckets, rpm):
    for b in buckets:
        b.append(rpm)
    return buckets


FULL = {"E02": 3.5, "F26": 600.0, "D03": 45.0}
FFP = eff.fingerprint(FULL)


def test_fan_max_is_never_raised():
    b = _with_fan(days_of(FFP, 0, 6), 600.0)
    for x in b:
        x[eff.F_SH] = 3.5
    tried_e02 = {}
    settings = {FFP: FULL}
    for v in (3.0, 4.0):
        s = {**FULL, "E02": v}
        settings[eff.fingerprint(s)] = s
        b += _with_fan(days_of(eff.fingerprint(s), 6 + len(tried_e02) * 5, 5, factor=1.0, seed=int(v * 10)), 600.0)
        tried_e02[v] = True
    a = _adv(b, FULL, settings, FFP)
    assert a["param"] != "F26" and "F26" not in eff.LADDER
    assert "fan_at_max" in eff.hints(eff.fit(b), b, 0, 0, 3.5, max(x[0] for x in b), FULL)
    low = _with_fan(days_of(FFP, 0, 6), 400.0)
    assert eff.fan_cap_share(low, 600.0, max(x[0] for x in low)) == 0.0


def test_fan_curve_tested_both_ways_slower_first_only_in_mild_weather():
    full = {**FULL, "F05": -4.0}
    ffp = eff.fingerprint(full)
    b = _with_fan(days_of(ffp, 0, 6), 350.0)
    settings = {ffp: full}
    model, groups = eff.compare(b, ffp)
    for v in (3.0, 4.0):
        s = {**full, "E02": v}
        settings[eff.fingerprint(s)] = s
        groups[eff.fingerprint(s)] = {"days": 5, "verdict": "inconclusive"}
    now = max(x[0] for x in b) + 600
    kw = dict(buckets=b, settings=settings, current=full, baseline_fp=ffp, changes=[], model=model,
              hint_list=["ok"], sh_target=3.5, now=now)
    a = eff.advise(groups=groups, **kw)
    assert (a["action"], a["param"], a["from"], a["to"], a["reason"]) == ("change", "F05", -4.0, -6.0,
                                                                         "fan_slower_first")
    slower = {**full, "F05": -6.0}
    settings[eff.fingerprint(slower)] = slower
    a = eff.advise(groups={**groups, eff.fingerprint(slower): {"days": 5, "verdict": "worse"}}, **kw)
    assert (a["param"], a["to"], a["reason"]) == ("F05", -2.0, "other_direction_tried")
    cold = [x[:eff.F_TOUT] + [0.0] + x[eff.F_TOUT + 1:] for x in b]
    a = eff.advise(groups=groups, **{**kw, "buckets": cold})
    assert a["param"] != "F05"
    assert eff._step("F05", -10.0, -1) is None and eff._step("F05", 2.0, 1) is None


def test_defrost_step_uses_daily_metric_and_waits_five_days():
    b = days_of(FFP, 0, 8)
    now = max(x[0] for x in b) + 600
    rows = [day_row(d, FFP, rng=random.Random(d)) for d in range(8)]
    dm, dg = eff.compare_daily(rows, FFP)
    model, groups = eff.compare(b, FFP)
    e02 = {}
    settings = {FFP: FULL}
    for v in (3.0, 4.0):
        s = {**FULL, "E02": v}
        fp = eff.fingerprint(s)
        settings[fp] = s
        groups[fp] = {"days": 5, "verdict": "inconclusive", "delta_pct": 0.1, "ci95_pct": 2.0}
    a = eff.advise(buckets=b, groups=groups, settings=settings, current=FULL, baseline_fp=FFP, changes=[],
                   model=model, hint_list=["ok"], sh_target=3.5, now=now, day_rows=rows, day_groups=dg,
                   day_model=dm, defrosts=_defrosts(10, now))
    assert (a["action"], a["param"], a["to"], a["metric"], a["days_left"]) == ("change", "D03", 60.0, "daily", 5)
    longer = {**FULL, "D03": 60.0}
    lfp = eff.fingerprint(longer)
    settings[lfp] = longer
    rows2 = rows + [day_row(d, lfp, rng=random.Random(50 + d)) for d in range(8, 10)]
    dm2, dg2 = eff.compare_daily(rows2, FFP)
    a = eff.advise(buckets=b, groups=groups, settings=settings, current=longer, baseline_fp=FFP, changes=[],
                   model=model, hint_list=["ok"], sh_target=3.5, now=now, day_rows=rows2, day_groups=dg2,
                   day_model=dm2, defrosts=_defrosts(10, now))
    assert a["action"] == "keep" and a["metric"] == "daily" and a["days_left"] == 3


def test_new_tracked_parameters_keep_existing_history():
    a = eff.EfficiencyAnalyser()
    a.update_settings({"E02": 3.5}, 1)
    old = a.current_fp()
    a.buckets.append([0, 30, 5, 35, 3000, 700, 5, 100, old, None])
    a.changes.append({"t": 2, "kind": "change", "diff": {}, "from": old, "to": old})
    assert a.update_settings({"E02": 3.5, "F26": 600.0, "D03": 45.0}, 3) is None
    new = a.current_fp()
    assert new != old and a.baseline_fp == new and a.buckets[0][eff.F_FP] == new
    assert a.settings[new] == {"E02": 3.5, "F26": 600.0, "D03": 45.0} and old not in a.settings
    assert a.changes[-1]["to"] == new
    assert a.describe(new) == "baseline"


def test_analyser_end_to_end_day_and_defrost_bookkeeping():
    a = eff.EfficiencyAnalyser()
    a.update_settings(FULL, 0)
    t0 = 20 * DAY
    for i in range(0, DAY + 600, 30):
        t = t0 + i
        rs = 2 if (i % 3600) < 180 else 1
        a.observe(t, {"running": rs == 1, "steady_ok": rs != 2, "hz": 40.0, "t_out": 0.0, "t_flow": 35.0,
                      "q": 3000.0 if rs == 1 else None, "p": 900.0 if rs == 1 else None, "sh": 4.0, "eev": 150.0,
                      "fan": 450.0, "coil": -6.0, "rs": rs, "p_day": 900.0, "q_day": 3000.0 if rs == 1 else -2000.0,
                      "cooling": False})
    assert len(a.days) == 1 and eff.day_ok(a.days[0])
    assert 23 <= len(a.defrosts) <= 25 and a.days[0][eff.R_DEFROSTS] == 24
    a.refresh(t0 + DAY + 600)
    d = a.last_day()
    assert d and 2.5 < d["cop"] < 3.3
    restored = eff.EfficiencyAnalyser(a.to_dict(0))
    assert restored.days == a.days and len(restored.defrosts) == len(a.defrosts)


def test_due_change_keeps_its_first_since(monkeypatch):
    step = {"action": "change", "param": "E02", "from": 5.0, "to": 5.5, "days_left": 3, "reason": "x"}
    monkeypatch.setattr(eff, "advise", lambda **kw: {**step, "since": kw["now"]})
    a = eff.EfficiencyAnalyser()
    a.update_settings(FULL, 0)
    a.refresh(1000)
    a.refresh(5000)
    assert a.advice["since"] == 1000
    b = eff.EfficiencyAnalyser(a.to_dict(5000))
    b.refresh(9000)
    assert b.advice["since"] == 1000
    monkeypatch.setattr(eff, "advise", lambda **kw: {**step, "to": 4.5, "since": kw["now"]})
    b.refresh(9500)
    assert b.advice["since"] == 9500


def test_next_decision_is_never_in_the_past():
    now = 100 * DAY + 3600
    for action in ("change", "revert", "accept"):
        assert eff.due_at({"action": action, "since": now - 10 * DAY, "days_left": 3}, now) == (None, False)
    assert eff.due_at({"action": "keep", "not_before": now + 60, "days_left": 3}, now) == (now + 60, False)
    t, est = eff.due_at({"action": "keep", "not_before": now - 60, "days_left": 2}, now)
    assert est and t > now
    t, est = eff.due_at({"action": "collecting", "days_left": 1}, now)
    assert est and t > now
    for action in ("done", "none", "check_curve"):
        assert eff.due_at({"action": action}, now) == (None, False)


def test_headline_never_says_ok_while_a_step_is_pending():
    assert eff.headline(["ok"], {"action": "change"}) == "action_suggested"
    assert eff.headline(["collecting"], {"action": "revert"}) == "action_suggested"
    assert eff.headline(["short_cycling", "ok"], {"action": "change"}) == "short_cycling"
    assert eff.headline(["ok"], {"action": "keep"}) == "ok"
    assert eff.headline([], {"action": "collecting"}) == "collecting"
