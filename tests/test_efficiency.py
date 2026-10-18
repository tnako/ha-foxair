#!/usr/bin/env python3
"""Efficiency analyser: steady buckets, weather-normalised COP model, settings comparison.

Run: pytest tests/test_efficiency.py -v
"""
import datetime
import importlib.util
import math
import pathlib
import random
import sys
import types
import zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"
PKG = "foxair_efficiency_test"
sys.modules.setdefault(PKG, types.ModuleType(PKG)).__path__ = [str(CC)]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", CC / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


model, hist, adv, an = (_load(n) for n in ("efficiency_model", "efficiency_history", "efficiency_advisor", "efficiency"))
eff = types.SimpleNamespace(**{k: v for m in (model, hist, adv, an) for k, v in vars(m).items() if not k.startswith("__")})

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


BASE = {"E02": 4.5}
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
    assert (a["action"], a["param"], a["from"], a["to"]) == ("change", "E02", 4.5, 4.0)
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
    assert (a["action"], a["param"], a["from"], a["to"]) == ("revert", "E02", 3.0, 4.5)
    a = _adv(base + days_of(nfp, 8, 5, factor=1.08, seed=2), new, st, BFP)
    assert (a["action"], a["param"], a["to"]) == ("accept", "E02", 3.0)


def test_inconclusive_test_says_so_and_rechecks_daily():
    new = {"E02": 3.0}
    nfp = eff.fingerprint(new)
    b = days_of(BFP, 0, 8, seed=1) + days_of(nfp, 8, 4, seed=2)
    a = _adv(b, new, {BFP: BASE, nfp: new}, BFP)
    assert (a["action"], a["reason"], a["days_left"]) == ("keep", "inconclusive", eff.COMPARE_MAX_DAYS - 4)
    st = eff.summary(a, ["ok"], None, "E02=3", NOW)
    assert "not clear yet" in st["message"] and "more heating day" not in st["message"]
    assert st["next_check"] == (NOW // DAY + 1) * DAY

def test_advise_tries_the_other_direction_after_a_worse_step():
    lower = {"E02": 4.0}
    lfp = eff.fingerprint(lower)
    b = days_of(BFP, 0, 8, seed=1) + days_of(lfp, 8, 5, factor=0.9, seed=2)
    for x in b:
        x[eff.F_SH] = 6.0
    a = _adv(b, BASE, {BFP: BASE, lfp: lower}, BFP)
    assert (a["action"], a["to"], a["reason"]) == ("change", 5.0, "other_direction_tried")


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
    heat = 30 + (10 - t_out) * 3
    cop = factor * (0.42 - 0.03 * t_out / 10 - 0.05 * heat / 120) * eff.carnot_cop(t_flow, t_out) * (1 + rng.gauss(0, 0.015))
    return {"day": f"2026-01-{day + 1:02d}", "hours": 24, "heat_hours": 24, "elec": round(heat / cop, 3), "heat": heat,
            "dhw": None,
            "defrost": 0.0, "cool": 0.0, "heat_total": heat, "t_out": t_out, "t_in": 20.0, "t_flow": t_flow,
            "fp": fp}


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
    for key, val in (("hours", 12), ("heat_hours", 12), ("heat_total", 2.0), ("fp", "mixed"), ("fp", None), ("cool", 1.5),
                     ("elec", 0.1), ("t_flow", None)):
        assert not eff.day_ok({**good, key: val})


UTC = datetime.timezone.utc
BERLIN = zoneinfo.ZoneInfo("Europe/Berlin")
IDS = {"elec": "sensor.meter", "heat": "sensor.heat", "dhw": "sensor.dhw", "defrost": "sensor.defrost",
       "cool": None, "t_out": "sensor.out", "t_in": "sensor.in", "t_flow": "sensor.flow"}


def hourly(start, hours, elec=0.5, heat=2.0, t_out=5.0, t_flow=35.0, defrost=0.0):
    rows = {k: [] for k in IDS.values() if k}
    for h in range(hours):
        t = start + 3600 * h
        on = h % 2 == 0
        rows["sensor.meter"].append({"start": t, "change": elec})
        rows["sensor.heat"].append({"start": t, "change": heat if on else 0.0})
        rows["sensor.dhw"].append({"start": t, "change": 0.0})
        rows["sensor.defrost"].append({"start": t, "change": defrost})
        rows["sensor.out"].append({"start": t, "mean": t_out})
        rows["sensor.in"].append({"start": t, "mean": 20.0})
        rows["sensor.flow"].append({"start": t, "mean": t_flow if on else 22.0})
    return rows


def test_days_are_local_days_from_hourly_statistics():
    midnight_berlin = 1791237600
    rows = eff.build_days(hourly(midnight_berlin, 48), IDS, BERLIN)
    assert [r["day"] for r in rows] == ["2026-10-06", "2026-10-07"]
    r = rows[0]
    assert r["hours"] == 24 and r["elec"] == 12.0 and r["heat_total"] == 24.0 and r["t_flow"] == 35.0
    utc_days = [x["day"] for x in eff.build_days(hourly(midnight_berlin, 48), IDS, UTC)]
    assert utc_days == ["2026-10-05", "2026-10-06", "2026-10-07"]
    taken = eff.build_days(hourly(midnight_berlin, 24, defrost=0.1), IDS, BERLIN)[0]
    assert abs(taken["heat_total"] - 21.6) < 1e-9 and taken["defrost"] == 2.4


def test_own_entities_are_the_default_and_options_override_them():
    own = {"elec": "sensor.p_energy_electrical", "t_out": "sensor.p_t04", "heat": "sensor.p_energy_heating"}
    ids = eff.stat_ids(own, {})
    assert ids["elec"] == "sensor.p_energy_electrical" and ids["t_in"] is None
    ids = eff.stat_ids(own, {"history_energy_entity": "sensor.meter10_energy", "history_indoor_entity": "sensor.room"})
    assert ids["elec"] == "sensor.meter10_energy" and ids["t_in"] == "sensor.room" and ids["t_out"] == "sensor.p_t04"


def test_merge_days_replaces_recent_days_and_keeps_older_ones():
    a = [{"day": "2026-10-01", "x": 1}, {"day": "2026-10-02", "x": 1}]
    b = [{"day": "2026-10-02", "x": 2}, {"day": "2026-10-03", "x": 2}]
    merged = [(r["day"], r["x"]) for r in eff.merge_days(a, b)]
    assert merged == [("2026-10-01", 1), ("2026-10-02", 2), ("2026-10-03", 2)]


def test_a_change_undone_within_30_minutes_is_no_change():
    log = [{"t": 0, "kind": "change", "from": "a", "to": "b"}, {"t": 660, "kind": "change", "from": "b", "to": "a"},
           {"t": 5000, "kind": "change", "from": "a", "to": "c"},
           {"t": 5000 + 3600, "kind": "change", "from": "c", "to": "a"}]
    assert [(c["from"], c["to"]) for c in eff.settled(log)] == [("a", "c"), ("c", "a")]
    a = eff.EfficiencyAnalyser()
    a.update_settings({"E07": 60.0, "P11": 3.0}, 100)
    a.update_settings({"E07": 40.0, "P11": 3.0}, 200)
    a.update_settings({"E07": 60.0, "P11": 3.0}, 860)
    assert a.last_change() is None and len(a.changes) == 2
    a.update_settings({"E07": 60.0, "P11": 3.5}, 5000)
    assert a.last_change()["diff"] == {"P11": [3.0, 3.5]}


def test_days_get_their_settings_group_and_quick_reverts_dont_mix_them():
    start = 1791237600
    rows = eff.build_days(hourly(start - 2 * DAY, 4 * 24), IDS, BERLIN)
    log = [{"t": start + 20 * 3600, "kind": "change", "from": "a", "to": "b"},
           {"t": start + 20 * 3600 + 600, "kind": "change", "from": "b", "to": "a"},
           {"t": start + DAY + 3600, "kind": "change", "from": "a", "to": "c"}]
    tagged = eff.tag_settings(rows, eff.settled(log), "c", start - DAY, BERLIN)
    assert [(r["day"], r["fp"]) for r in tagged] == [("2026-10-04", None), ("2026-10-05", "a"),
                                                       ("2026-10-06", "a"), ("2026-10-07", "mixed")]
    assert "fp" not in rows[0]


def _hist_row(day, elec, t_out, t_in=20.0, heat=None):
    return {"day": day.isoformat(), "hours": 24, "heat_hours": 24 if heat else 0, "elec": elec, "heat_total": heat,
            "t_out": t_out, "t_in": t_in}


def test_last_30_days_compares_only_matched_days_with_same_weather_days():
    today = datetime.date(2026, 10, 14)
    rows = []
    for i in range(1, 366):
        d = today - datetime.timedelta(days=i)
        t_out = 10.0 + 8.0 * math.cos(2 * math.pi * (d.timetuple().tm_yday - 200) / 365)
        need = max(0.0, 20.0 - t_out) * 0.6
        recent = i <= 30
        rows.append(_hist_row(d, round(need * (0.8 if recent else 1.0), 3), round(t_out, 2),
                              heat=round(need * 4, 3) if recent else None))
    rows.sort(key=lambda r: r["day"])
    c = eff.comparisons(rows, today)
    assert c["period"] == "2026-09-14..2026-10-13"
    assert c["comparable"] and c["matched_days"] >= 20 and -22 < c["elec_pct"] < -18
    assert c["now"]["elec_kwh"] < c["past_year"]["elec_kwh"]
    assert abs(c["now"]["t_out"] - c["past_year"]["t_out"]) < 1.5
    assert c["now"]["cop"] == 5.0 and c["now"]["cop_days"] == c["matched_days"]
    assert c["past_year"]["cop"] is None and c["cop_pct"] is None


def test_same_weather_scales_by_indoor_temperature_and_skips_non_heating_days():
    pool = [_hist_row(datetime.date(2026, 1, i), 6.0, 10.0, t_in=21.0) for i in range(1, 6)]
    pool.append(_hist_row(datetime.date(2026, 1, 9), 0.2, 10.0))
    cooler = _hist_row(datetime.date(2026, 10, 1), 4.5, 10.0, t_in=19.0)
    assert eff.expected_elec(cooler, pool) == 6.0 * 9.0 / 11.0
    assert eff.expected_elec(_hist_row(datetime.date(2026, 10, 1), 4.5, 15.0), pool) is None
    r = eff.vs_past_year([cooler, _hist_row(datetime.date(2026, 10, 2), 0.3, 10.0)], pool)
    assert r["heating_days"] == 1 and r["matched_days"] == 1 and r["reference_days"] == 5 and not r["comparable"]
    assert r["now"]["elec_kwh"] == 4.5 and r["past_year"]["t_in"] == 21.0


def test_past_year_side_weights_every_matched_day_equally():
    cold = [_hist_row(datetime.date(2026, 1, i), 8.0, 2.0, heat=24.0) for i in range(1, 11)]
    mild = [_hist_row(datetime.date(2026, 3, i), 4.0, 12.0, heat=16.0) for i in range(1, 4)]
    cur = [_hist_row(datetime.date(2026, 10, 1), 6.0, 2.0), _hist_row(datetime.date(2026, 10, 2), 3.0, 12.0)]
    r = eff.vs_past_year(cur, cold + mild)
    assert r["matched_days"] == 2 and r["reference_days"] == 13
    assert r["now"]["t_out"] == r["past_year"]["t_out"] == 7.0
    assert r["past_year"]["cop"] == 3.33 and r["past_year"]["cop_days"] == 2


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


def test_only_e02_is_ever_suggested_even_when_fan_and_defrost_preconditions_hold():
    assert set(eff.LADDER) == {"E02"} and (eff.LADDER["E02"]["min"], eff.LADDER["E02"]["max"]) == (4.0, 7.0)
    full = {**FULL, "F05": -4.0}
    ffp = eff.fingerprint(full)
    b = _with_fan(days_of(ffp, 0, 8), 350.0)
    now = max(x[0] for x in b) + 600
    rows = [day_row(d, ffp, rng=random.Random(d)) for d in range(8)]
    dm, dg = eff.compare_daily(rows, ffp)
    model, groups = eff.compare(b, ffp)
    settings = {ffp: full}
    for v in (3.0, 4.0):
        s = {**full, "E02": v}
        settings[eff.fingerprint(s)] = s
        groups[eff.fingerprint(s)] = {"days": 5, "verdict": "inconclusive"}
    assert "defrost_on_timer" in eff.hints(model, b, 0, 0, 3.5, now, full, _defrosts(10, now))
    a = eff.advise(buckets=b, groups=groups, settings=settings, current=full, baseline_fp=ffp, changes=[],
                   model=model, hint_list=["ok"], sh_target=3.5, now=now, day_rows=rows, day_groups=dg,
                   day_model=dm, defrosts=_defrosts(10, now))
    assert (a["action"], a["param"]) == ("done", None)
    assert eff._step("E02", 4.0, -1) is None and eff._step("E02", 7.0, 1) is None


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


def test_analyser_end_to_end_defrost_bookkeeping_and_recorder_days():
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
    assert 23 <= len(a.defrosts) <= 25
    a.set_days(eff.build_days(hourly(t0, 24), IDS, UTC), UTC)
    a.refresh(t0 + DAY + 600)
    d = a.last_day(t0 + DAY + 600)
    assert d["day"] == "1970-01-21" and d["cop"] == 2.0 and d["comparable"] and d["days_recorded"] == 1
    restored = eff.EfficiencyAnalyser(a.to_dict(0))
    assert restored.days == [] and len(restored.defrosts) == len(a.defrosts) and "days" not in a.to_dict(0)
    assert restored.tracked_since == 0


def test_due_change_keeps_its_first_since(monkeypatch):
    step = {"action": "change", "param": "E02", "from": 5.0, "to": 5.5, "days_left": 3, "reason": "x"}
    monkeypatch.setattr(an, "advise", lambda **kw: {**step, "since": kw["now"]})
    a = eff.EfficiencyAnalyser()
    a.update_settings(FULL, 0)
    a.refresh(1000)
    a.refresh(5000)
    assert a.advice["since"] == 1000
    b = eff.EfficiencyAnalyser(a.to_dict(5000))
    b.refresh(9000)
    assert b.advice["since"] == 1000
    monkeypatch.setattr(an, "advise", lambda **kw: {**step, "to": 4.5, "since": kw["now"]})
    b.refresh(9500)
    assert b.advice["since"] == 9500


def test_running_test_is_a_group_from_the_moment_of_the_change():
    a = eff.EfficiencyAnalyser()
    a.update_settings(BASE, 0)
    a.buckets = days_of(BFP, 0, 6)
    t = 6 * DAY + 600
    a.update_settings({"E02": 3.0}, t)
    nfp = a.current_fp()
    a.refresh(t + 60)
    assert a.groups[nfp] == {"buckets": 0, "days": 0, "delta_pct": None, "ci95_pct": None, "verdict": "settling"}
    a.refresh(t + eff.MIN_HOLD_S + 60)
    assert a.groups[nfp]["verdict"] == "collecting" and a.groups[nfp]["days"] == 0
    a.update_settings(BASE, t + 2 * DAY)
    a.refresh(t + 2 * DAY + 60)
    assert nfp not in a.groups and a.groups[BFP]["verdict"] == "baseline"


NOW = 100 * DAY + 3600


def _st(advice, hints=("ok",), flow=None, group="baseline"):
    return eff.summary(advice, list(hints), flow, group, NOW)


def test_every_state_has_one_message_and_a_consistent_apply():
    cases = [
        ({"action": "none", "reason": "settings_unknown"}, "learning", None),
        ({"action": "collecting", "days_left": 2, "reason": "baseline_needs_days"}, "learning", None),
        ({"action": "wait_heating", "reason": "no_heating", "param": "E02", "from": 5.0, "to": 5.5},
         "waiting_for_heating", None),
        ({"action": "change", "param": "E02", "from": 5.0, "to": 5.5, "days_left": 3}, "suggestion", "write"),
        ({"action": "revert", "param": "E02", "from": 5.5, "to": 5.0, "reason": "worse"}, "suggestion", "write"),
        ({"action": "accept", "param": "E02", "from": 5.0, "to": 5.5, "delta_pct": 2.1}, "suggestion", "baseline"),
        ({"action": "keep", "param": "E02", "days_left": 2, "reason": "need_more_days"}, "testing", None),
        ({"action": "done", "reason": "no_candidate"}, "no_change", None),
        ({"action": "check_curve", "reason": "short_cycling"}, "problem", None),
    ]
    for adv, state, kind in cases:
        st = _st(adv, group="E02=5.5" if adv["action"] in ("keep", "revert") else "baseline")
        assert st["state"] == state and st["state"] in eff.STATES, adv
        assert (st["apply"] or {}).get("kind") == kind, adv
        assert st["message"] and ("Apply" in st["message"]) == (kind is not None), adv


def test_suggestion_message_names_the_button_and_values():
    st = _st({"action": "change", "param": "E02", "from": 5.0, "to": 5.5, "days_left": 3})
    assert st["message"].startswith("Press Apply to set E02 from 5 to 5.5")
    assert st["apply"] == {"kind": "write", "param": "E02", "from": 5.0, "to": 5.5}
    assert st["next_check"] is None


def test_manual_change_is_measured_first_and_never_written_back():
    keep = _st({"action": "keep", "param": None, "days_left": 2, "reason": "need_more_days"}, group="E02=5.5 H22=1")
    assert keep["state"] == "testing" and keep["apply"] is None and "Press Apply" not in keep["message"]
    for reason in ("worse", "no_clear_gain"):
        res = _st({"action": "revert", "param": "H22", "from": 1.0, "to": 0.0, "reason": reason, "delta_pct": -3.0},
                  group="H22=1")
        assert res["state"] == "suggestion" and res["apply"] == {"kind": "baseline"}
        assert "nothing is written to the pump" in res["message"] and "H22=1" in res["message"]


def test_user_settings_are_watch_only():
    for p in ("H22", "H25", "H36", "P11", "F26", "A40"):
        assert p not in eff.LADDER
    pol = eff.suggestion_policy(["E02", "H22", "H25", "H36"])
    assert pol["watch_only"] == ["H22", "H25", "H36"]


def test_daily_cop_shows_yesterday_even_after_a_settings_change():
    a = eff.EfficiencyAnalyser()
    a.update_settings({"E02": 5.0}, 4 * DAY)
    a.update_settings({"E02": 5.5}, 5 * DAY + 3600)
    rows = eff.build_days(hourly(5 * DAY, 24, elec=0.25, heat=2.0), IDS, UTC)
    a.set_days(rows, UTC)
    d = a.last_day(6 * DAY + 60)
    assert d["cop"] == 4.0 and d["comparable"] is False and d["not_comparable_why"] == ["settings_changed"]
    assert eff.day_data_problems(rows[0]) == []
    a.set_days(eff.build_days(hourly(5 * DAY, 10), IDS, UTC), UTC)
    d = a.last_day(6 * DAY + 60)
    assert "cop" not in d and d["last_day_skipped"]["why"][0] == "coverage"
    assert a.last_day(5 * DAY + 7200).get("cop") is None


def test_next_check_is_never_in_the_past():
    for adv in ({"action": "keep", "not_before": NOW - 60, "days_left": 2},
                {"action": "collecting", "days_left": 1},
                {"action": "wait_heating", "days_left": 3},
                {"action": "keep", "reason": "settling_after_change", "not_before": NOW + 60}):
        t = _st(adv)["next_check"]
        assert t is None or t > NOW, adv
    for adv in ({"action": "change", "since": NOW - 10 * DAY, "days_left": 3}, {"action": "done"},
                {"action": "check_curve"}, {"action": "none"}):
        assert _st(adv)["next_check"] is None, adv


def test_flow_problem_overrides_the_status_and_keeps_the_pending_step():
    flow = {"delta_k": 12.4, "cop_pct": -11.0, "buckets": 30}
    st = _st({"action": "change", "param": "E02", "from": 5.0, "to": 5.5, "days_left": 3},
             hints=["flow_higher", "ok"], flow=flow)
    assert st["state"] == "problem" and st["apply"]["kind"] == "write"
    assert "12.4 K warmer" in st["message"] and "Also: Press Apply" in st["message"]
    st = _st({"action": "keep", "reason": "settling_after_change", "not_before": NOW + 60},
             hints=["flow_higher"], flow=flow, group="E02=5.5")
    assert st["state"] == "problem" and st["apply"] is None
    assert "Also: Testing E02=5.5: measuring starts after a 24 h settling time." in st["message"]


def test_flow_shift_compares_same_outdoor_temperature_only():
    def b(t, tout, tflow, cop):
        return [t, 30, tout, tflow, 3000.0 * cop / 3, 1000.0, 5, 100, "x", None]
    old = [b(NOW - 3 * DAY + i * 600, 11 + (i % 3), 30.0, 4.2) for i in range(30)]
    new = [b(NOW - 3600 * 5 + i * 600, 11 + (i % 3), 42.0, 3.5) for i in range(12)]
    f = eff.flow_shift(old + new, NOW)
    assert f["delta_k"] == 12.0 and f["cop_pct"] < -10 and f["buckets"] == 12
    assert "flow_higher" in eff.hints(None, old + new, 0, 0, None, NOW, flow=f)
    cold = [b(NOW - 3600 + i * 60, -5, 42.0, 3.0) for i in range(10)]
    assert eff.flow_shift(old + cold, NOW) is None
    same = [b(NOW - 3600 * 5 + i * 600, 11 + (i % 3), 30.5, 4.2) for i in range(12)]
    assert "flow_higher" not in eff.hints(None, old + same, 0, 0, None, NOW, flow=eff.flow_shift(old + same, NOW))


def test_flow_problem_holds_until_flow_is_clearly_back():
    seen = []
    was = False
    for delta in (2.9, 3.0, 2.9, 3.1, 2.8, 3.0, 2.9, 2.6, 2.4, 2.9):
        h = eff.hints(None, [], 0, 0, None, NOW, flow={"delta_k": delta, "cop_pct": -5.0, "buckets": 60}, flow_was_higher=was)
        was = "flow_higher" in h
        seen.append(was)
    assert seen == [False, True, True, True, True, True, True, True, False, False]


def test_analyser_feeds_the_last_flow_finding_back(monkeypatch):
    a = eff.EfficiencyAnalyser()
    a.update_settings(FULL, 0)
    seen = []
    for delta in (3.1, 2.8, 2.9, 2.4):
        monkeypatch.setattr(an, "flow_shift", lambda buckets, now, d=delta: {"delta_k": d, "cop_pct": -5.0, "buckets": 60})
        a.refresh(1000)
        seen.append(a.status(1000)["state"])
    assert seen == ["problem", "problem", "problem", seen[3]] and seen[3] != "problem"


def test_status_is_the_single_source_for_the_analyser():
    a = eff.EfficiencyAnalyser()
    a.update_settings(FULL, 0)
    a.set_baseline(0)
    a.refresh(1000)
    st = a.status(1000)
    assert st["state"] in eff.STATES and st["message"]
    assert a.flow is None
