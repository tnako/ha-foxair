"""Glue between the coordinator and the efficiency analyser: samples, settings, recorder history, persistence."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from . import computed as _computed
from .efficiency import LADDER, EfficiencyAnalyser
from .efficiency_autotest import PARAM
from .efficiency_history import HISTORY_DAYS, OWN_SUFFIXES, build_days, merge_days, stat_ids

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
SAVE_DELAY_S = 300
SETTINGS_EVERY_S = 600
REFRESH_EVERY_S = 3600
EXPECT_S = 900
HISTORY_TOPUP_DAYS = 2
OWN_MEANS = {"t_out": "t04", "t_flow": "t02"}

ADDR_SH_SUCTION = 2067
ADDR_EEV_STEPS = 2020
ADDR_COIL = 2049
ADDR_FAN_TARGET = 2076
ADDR_FLOW = 2077
ADDR_INLET = 2045
ADDR_LIMITER = 2139
RUN_STATUS_DEFROST = 2
WATER_W_PER_M3H_K = 1000.0 * 4186.0 / 3600.0

SETTING_ADDRS = {
    "E01": 1131, "E02": 1132, "E03": 1133, "E07": 1137, "E19": 1149,
    "E03-1": 1200, "E03-2": 1142, "E03-3": 1206, "E03-4": 1207, "E03-5": 1208,
    "E07-1": 1209, "E07-2": 1210, "E07-3": 1211, "E07-4": 1215, "E07-5": 1216,
    "F05": 1066, "F06": 1068, "F19": 1083, "F26": 1104,
    "P01": 1197, "P02": 1198, "P03": 1199, "P11": 1432, "P12": 1433, "A40": 1344,
    "C02": 1219, "C03": 1220, "C10": 1227,
    "D01": 1105, "D02": 1106, "D03": 1107, "D17": 1122, "D19": 1124,
    "A31": 1049, "A33": 1063, "A34": 1064, "H18": 1032,
    "H22": 1030, "H25": 1035, "H36": 1236,
}


def _val(coord, addr):
    rec = (coord.data or {}).get(addr)
    if not rec:
        return None
    v = rec.get("value")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def marker_addrs(coord) -> dict:
    status = (coord.marker("status") or {}).get("addr_single") or {}
    curve = (coord.marker("heat_curve") or {}).get("addr_single") or {}
    return {"hz": status.get("compressor_freq"), "t_flow": status.get("outlet_water_temp"),
            "t_out": curve.get("at_sensor")}


def settings_snapshot(coord) -> dict:
    """Tracked settings present in coord.data (expert mode polls most of them)."""
    out = {}
    for code, addr in SETTING_ADDRS.items():
        v = _val(coord, addr)
        if v is not None:
            out[code] = round(v, 1)
    return out


def _water_power(coord, t_flow):
    """Signed water-side power flow x cp x (outlet - inlet); negative while defrost pulls heat back."""
    flow, inlet = _val(coord, ADDR_FLOW), _val(coord, ADDR_INLET)
    if flow is None or inlet is None or t_flow is None or flow <= 0:
        return None
    return flow * WATER_W_PER_M3H_K * (t_flow - inlet)


def sample(coord, opts: dict) -> dict:
    """One poll's worth of analyser inputs: steady heating, daily totals and defrost tracking."""
    a = marker_addrs(coord)
    rs = _computed.run_status_raw(coord)
    mode = _computed.active_mode(coord)
    comp = _computed.compressor_running(coord) is True
    running = comp and mode == "heating"
    t_flow = _val(coord, a["t_flow"]) if a["t_flow"] else None
    q = _computed.compute_thermal_power(coord, "heating") if running else None
    p_all = _computed.compute_electrical_power(coord, opts)
    if mode in ("heating", "dhw") and comp:
        q_day = _computed.compute_thermal_power(coord, mode)
    elif mode == "defrost":
        q_day = _water_power(coord, t_flow)
    else:
        q_day = None
    return {
        "running": running,
        "steady_ok": rs != RUN_STATUS_DEFROST and not _computed.electric_heater_on(coord)
                     and not _val(coord, ADDR_LIMITER),
        "hz": _val(coord, a["hz"]) if a["hz"] else None,
        "t_out": _val(coord, a["t_out"]) if a["t_out"] else None,
        "t_flow": t_flow,
        "q": q, "p": p_all if running else None,
        "sh": _val(coord, ADDR_SH_SUCTION), "eev": _val(coord, ADDR_EEV_STEPS),
        "fan": _val(coord, ADDR_FAN_TARGET), "coil": _val(coord, ADDR_COIL),
        "rs": rs, "p_day": p_all, "q_day": q_day, "cooling": mode == "cooling" and comp,
        "heater": _computed.electric_heater_on(coord),
    }


def history_sources(prefix: str, opts: dict) -> dict:
    own = {k: f"sensor.{prefix}_{s}" for k, s in OWN_SUFFIXES.items()}
    own.update({k: f"sensor.{prefix}_{s}" for k, s in OWN_MEANS.items()})
    return stat_ids(own, opts)


def read_statistics(hass, ids: dict, start: datetime, end: datetime) -> dict:
    """Hourly change/mean rows per statistic id, start as epoch seconds (runs in the recorder executor)."""
    from homeassistant.components.recorder.statistics import statistics_during_period

    wanted = {sid for sid in ids.values() if sid}
    units = {"energy": "kWh", "temperature": "°C"}
    rows = statistics_during_period(hass, start, end, wanted, "hour", units, {"change", "mean"})
    return {sid: [dict(r) for r in v] for sid, v in rows.items()}


class EfficiencyRuntime:
    """Owns the analyser for one config entry; all hass calls go through here."""

    def __init__(self, hass, coord, store):
        self.hass = hass
        self.coord = coord
        self.store = store
        self.analyser = EfficiencyAnalyser()
        self._settings_ts = 0.0
        self._refresh_ts = 0.0
        self._save_ts = time.time()
        self._fetched: dict = {}
        self._fetched_once = False
        self._settings_task = None
        self._refresh_task = None
        self._write_task = None
        self._expect: dict[str, tuple[float, str, float]] = {}
        self._history_full = False
        self.history_error: str | None = None

    async def async_load(self) -> None:
        data = await self.store.async_load()
        self.analyser = EfficiencyAnalyser(data)
        await self.async_load_history()
        await self.hass.async_add_executor_job(self.analyser.refresh, time.time())
        self._settings_ts = time.time()
        missing = {a for a in SETTING_ADDRS.values() if a not in (self.coord.data or {})}
        if missing:
            self._settings_task = self.hass.async_create_task(self._fetch_settings(missing))
        else:
            self._publish_settings()

    async def async_load_history(self) -> None:
        """Daily rows from recorder long-term statistics: all 400 days once, then the last 2 days each refresh."""
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.util import dt as dt_util
        except ImportError:
            self.history_error = "recorder_unavailable"
            return
        tz = dt_util.get_default_time_zone()
        ids = history_sources(str((self.coord.entry.data or {}).get("name_prefix") or "foxair"),
                              self.coord.entry.options)
        days = HISTORY_TOPUP_DAYS if self._history_full else HISTORY_DAYS
        end = datetime.now(timezone.utc)
        start = dt_util.start_of_local_day(end - timedelta(days=days)).astimezone(timezone.utc)
        try:
            hourly = await get_instance(self.hass).async_add_executor_job(read_statistics, self.hass, ids, start, end)
        except Exception as e:
            self.history_error = f"{type(e).__name__}: {e}"
            _LOGGER.warning("efficiency: reading recorder statistics failed: %s", e)
            return
        rows = build_days(hourly, ids, tz)
        self.analyser.set_days(merge_days(self.analyser.days if self._history_full else [], rows), tz)
        self.analyser.history_sources = ids
        self._history_full, self.history_error = True, None

    def _data(self) -> dict:
        return self.analyser.to_dict(time.time())

    def schedule_save(self) -> None:
        self.store.async_delay_save(self._data, SAVE_DELAY_S)

    async def async_save(self) -> None:
        await self.store.async_save(self._data())

    def tz(self):
        try:
            from homeassistant.util import dt as dt_util
            return dt_util.get_default_time_zone()
        except ImportError:
            return timezone.utc

    def on_poll(self) -> None:
        """Called by the coordinator after each successful poll (event loop)."""
        try:
            now = time.time()
            self._publish_settings()
            sh = _val(self.coord, SETTING_ADDRS["E02"])
            if sh is not None:
                self.analyser.sh_target = sh
            if now - self._settings_ts >= SETTINGS_EVERY_S and not self._task_running(self._settings_task):
                self._settings_ts = now
                missing = {a for a in SETTING_ADDRS.values() if a not in (self.coord.data or {})}
                if missing:
                    self._settings_task = self.hass.async_create_task(self._fetch_settings(missing))
            s = sample(self.coord, self.coord.entry.options)
            closed = self.analyser.observe(now, s)
            at = self.analyser.autotest
            if at.running and "short_cycling" in self.analyser.hint_list:
                at.stop("short_cycling", now)
                closed = True
            closed = at.observe(now, s, self.tz(), self._e02()) or closed
            self._autotest_tick(now)
            if closed or now - self._save_ts >= SAVE_DELAY_S:
                self._save_ts = now
                self.schedule_save()
            if closed or now - self._refresh_ts >= REFRESH_EVERY_S:
                self.request_refresh()
        except Exception:
            _LOGGER.exception("efficiency analyser poll failed")

    def _e02(self) -> float | None:
        v = _val(self.coord, SETTING_ADDRS[PARAM])
        return round(v, 1) if v is not None else self._fetched.get(PARAM)

    def _autotest_tick(self, now: float) -> None:
        """Start the write the autotest wants (slot change, finish, stop restore); one at a time."""
        at = self.analyser.autotest
        want = at.want(now, self.tz())
        if want is None or self._task_running(self._write_task):
            return
        if self._e02() == want:
            if at.wrote(want, now, written=False):
                self.analyser.set_baseline(now)
            return
        self._write_task = self.hass.async_create_task(self._autotest_write(want))

    async def _autotest_write(self, value: float) -> None:
        at = self.analyser.autotest
        try:
            await self.async_write_setting(PARAM, value, "autotest")
        except ValueError as e:
            _LOGGER.warning("Efficiency autotest: %s", e)
            if at.running:
                at.stop("write_failed", time.time())
            else:
                at.restore_failed()
            await self.async_save()
            self.coord.async_update_listeners()
            return
        if at.wrote(value, time.time()):
            self.analyser.set_baseline(time.time())
        await self.async_save()
        self.request_refresh()

    async def async_set_autotest(self, on: bool) -> None:
        """Switch the E02 autotest on (from the current E02) or off (E02 back to its value at the start)."""
        at, now = self.analyser.autotest, time.time()
        if on and not at.running:
            if not self.coord.entry.options.get("enable_expert"):
                raise ValueError(f"{PARAM} is an expert setting: turn on expert mode in the integration options first")
            e02 = self._e02()
            if e02 is None:
                raise ValueError(f"{PARAM} not read from the pump yet; try again in a minute")
            at.start(now, self.tz(), e02)
        elif not on and at.running:
            at.stop("user", now)
        await self.async_save()
        self._autotest_tick(now)
        self.coord.async_update_listeners()

    async def async_undo(self) -> dict:
        """Write back every setting EEF changed to its value before EEF, then forget all tests."""
        at = self.analyser.autotest
        if at.running:
            at.stop("undo", time.time(), restore=False)
        if self._task_running(self._write_task):
            await self._write_task
        targets = self.analyser.undo_targets()
        for code, (now_val, before) in targets.items():
            await self.async_write_setting(code, before, "undo", expect=now_val)
        self.analyser.reset_tests(time.time())
        await self.async_save()
        self.request_refresh()
        _LOGGER.info("Efficiency undo: %s; test history cleared", targets or "nothing to write back")
        return targets

    @staticmethod
    def _task_running(task) -> bool:
        return task is not None and not task.done()

    def request_refresh(self) -> None:
        if not self._task_running(self._refresh_task):
            self._refresh_task = self.hass.async_create_task(self._refresh())

    async def _refresh(self) -> None:
        self._refresh_ts = time.time()
        await self.async_load_history()
        await self.hass.async_add_executor_job(self.analyser.refresh, self._refresh_ts)
        self.coord.async_update_listeners()

    async def _fetch_settings(self, addrs: set[int]) -> None:
        """Read tracked settings the tiered poll skips; never written to coord.data."""
        try:
            out = await self.coord._fetch_addrs(addrs)
        except Exception as e:
            _LOGGER.debug("efficiency settings read failed: %s", e)
            return
        for code, addr in SETTING_ADDRS.items():
            rec = out.get(addr)
            if rec and rec.get("value") is not None:
                self._fetched[code] = round(float(rec["value"]), 1)
        self._fetched_once = bool(out)
        self._publish_settings()

    def _publish_settings(self) -> None:
        """Hand the analyser a complete snapshot only, so the fingerprint never grows key by key."""
        snap = {**self._fetched, **settings_snapshot(self.coord)}
        polled = all(a in (self.coord.data or {}) for a in SETTING_ADDRS.values())
        if polled or self._fetched_once:
            now = time.time()
            exp = {k: v for k, v in self._expect.items() if now - v[2] <= EXPECT_S}
            moved = {k: v for k, v in snap.items() if k in self.analyser.current and self.analyser.current[k] != v}
            by = None
            if moved and all(k in exp and round(exp[k][0], 1) == round(v, 1) for k, v in moved.items()):
                by = exp[next(iter(moved))][1]
            rec = self.analyser.update_settings(snap, now, by)
            if rec:
                for k in moved:
                    self._expect.pop(k, None)
                _LOGGER.info("Heat pump settings changed%s: %s", f" by {by}" if by else "", rec["diff"])
                at = self.analyser.autotest
                if at.running and not by:
                    if PARAM in moved:
                        at.stop("manual_change", now, restore=False)
                    else:
                        at.mark_mixed(now, self.tz())
                self.schedule_save()
                self.request_refresh()

    async def async_set_baseline(self) -> None:
        self.analyser.set_baseline(time.time())
        await self.async_save()
        await self._refresh()

    async def async_write_setting(self, code: str, value: float, by: str, expect: float | None = None) -> None:
        """The only EEF write path: ladder settings only (E02), in range, pump value checked before and after."""
        if code not in LADDER:
            raise ValueError(f"{code} is watch-only; nothing written")
        lo, hi = LADDER[code]["min"], LADDER[code]["max"]
        if by != "undo" and not lo <= value <= hi:
            raise ValueError(f"{code}={value} is outside {lo:g}-{hi:g}; nothing written")
        addr = SETTING_ADDRS[code]
        now_val = _val(self.coord, addr)
        if now_val is None:
            now_val = self._fetched.get(code)
        if expect is not None and (now_val is None or round(now_val, 1) != round(expect, 1)):
            raise ValueError(f"{code} is {now_val} on the pump, expected {expect}; nothing written")
        self._expect[code] = (value, by, time.time())
        if not await self.coord.async_write_register(addr, value):
            self._expect.pop(code, None)
            raise ValueError(f"writing {code}={value} failed or was blocked")
        got = _val(self.coord, addr)
        if got is None or round(got, 1) != round(value, 1):
            raise ValueError(f"{code} read back {got}, expected {value}")
        _LOGGER.info("Efficiency %s: %s %s -> %s", by, code, now_val, value)
        self._fetched[code] = round(got, 1)
        self._publish_settings()

    async def async_apply(self) -> str:
        """Do what the current suggestion says; returns 'written', 'baseline' or raises ValueError."""
        st = self.analyser.status(time.time())
        act = st["apply"]
        if not act:
            raise ValueError(st["message"])
        if act["kind"] == "baseline":
            await self.async_set_baseline()
            return "baseline"
        await self.async_write_setting(act["param"], act["to"], "apply", expect=act["from"])
        return "written"

    async def async_shutdown(self) -> None:
        for task in (self._settings_task, self._refresh_task, self._write_task):
            if task is not None and not task.done():
                task.cancel()
        await self.async_save()
