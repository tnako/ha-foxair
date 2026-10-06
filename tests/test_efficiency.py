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
    assert len(got) == 2 and got[0][0] == t0 + 1200 and got[0][0] >= t0 + eff.WARMUP_S
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
