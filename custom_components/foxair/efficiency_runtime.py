"""Glue between the coordinator and the efficiency analyser: samples, settings, persistence."""
from __future__ import annotations

import logging
import time

from . import computed as _computed
from .efficiency import EfficiencyAnalyser

_LOGGER = logging.getLogger(__name__)

STORE_VERSION = 1
SAVE_DELAY_S = 300
SETTINGS_EVERY_S = 600
REFRESH_EVERY_S = 3600

ADDR_SH_SUCTION = 2067
ADDR_EEV_STEPS = 2020
RUN_STATUS_DEFROST = 2

SETTING_ADDRS = {
    "E01": 1131, "E02": 1132, "E03": 1133, "E07": 1137, "E19": 1149,
    "E03-1": 1200, "E03-2": 1142, "E03-3": 1206, "E03-4": 1207, "E03-5": 1208,
    "E07-1": 1209, "E07-2": 1210, "E07-3": 1211, "E07-4": 1215, "E07-5": 1216,
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
    """EEV settings present in coord.data (expert mode polls them)."""
    out = {}
    for code, addr in SETTING_ADDRS.items():
        v = _val(coord, addr)
        if v is not None:
            out[code] = round(v, 1)
    return out


def sample(coord, opts: dict) -> dict:
    """One poll's worth of analyser inputs; heating-only, defrost and heater polls are not steady."""
    a = marker_addrs(coord)
    rs = _computed.run_status_raw(coord)
    running = _computed.compressor_running(coord) is True and _computed.active_mode(coord) == "heating"
    q = _computed.compute_thermal_power(coord, "heating") if running else None
    p = _computed.compute_electrical_power(coord, opts) if running else None
    return {
        "running": running,
        "steady_ok": rs != RUN_STATUS_DEFROST and not _computed.electric_heater_on(coord),
        "hz": _val(coord, a["hz"]) if a["hz"] else None,
        "t_out": _val(coord, a["t_out"]) if a["t_out"] else None,
        "t_flow": _val(coord, a["t_flow"]) if a["t_flow"] else None,
        "q": q, "p": p,
        "sh": _val(coord, ADDR_SH_SUCTION), "eev": _val(coord, ADDR_EEV_STEPS),
    }


class EfficiencyRuntime:
    """Owns the analyser for one config entry; all hass calls go through here."""

    def __init__(self, hass, coord, store):
        self.hass = hass
        self.coord = coord
        self.store = store
        self.analyser = EfficiencyAnalyser()
        self._settings_ts = 0.0
        self._refresh_ts = 0.0
        self._fetched: dict = {}
        self._fetched_once = False
        self._settings_task = None
        self._refresh_task = None

    async def async_load(self) -> None:
        data = await self.store.async_load()
        self.analyser = EfficiencyAnalyser(data)
        await self.hass.async_add_executor_job(self.analyser.refresh, time.time())
        self._settings_ts = time.time()
        missing = {a for a in SETTING_ADDRS.values() if a not in (self.coord.data or {})}
        if missing:
            self._settings_task = self.hass.async_create_task(self._fetch_settings(missing))
        else:
            self._publish_settings()

    def _data(self) -> dict:
        return self.analyser.to_dict(time.time())

    def schedule_save(self) -> None:
        self.store.async_delay_save(self._data, SAVE_DELAY_S)

    async def async_save(self) -> None:
        await self.store.async_save(self._data())

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
            closed = self.analyser.observe(now, sample(self.coord, self.coord.entry.options))
            if closed:
                self.schedule_save()
            if closed or now - self._refresh_ts >= REFRESH_EVERY_S:
                self.request_refresh()
        except Exception:
            _LOGGER.exception("efficiency analyser poll failed")

    @staticmethod
    def _task_running(task) -> bool:
        return task is not None and not task.done()


    def request_refresh(self) -> None:
        if not self._task_running(self._refresh_task):
            self._refresh_task = self.hass.async_create_task(self._refresh())

    async def _refresh(self) -> None:
        self._refresh_ts = time.time()
        await self.hass.async_add_executor_job(self.analyser.refresh, self._refresh_ts)
        self.coord.async_update_listeners()

    async def _fetch_settings(self, addrs: set[int]) -> None:
        """Read EEV settings that the tiered poll skips (expert mode off); never written to coord.data."""
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
            rec = self.analyser.update_settings(snap, time.time())
            if rec:
                _LOGGER.info("EEV settings changed: %s", rec["diff"])
                self.schedule_save()
                self.request_refresh()

    async def async_set_baseline(self) -> None:
        self.analyser.set_baseline(time.time())
        await self.async_save()
        await self._refresh()

    async def async_shutdown(self) -> None:
        for task in (self._settings_task, self._refresh_task):
            if task is not None and not task.done():
                task.cancel()
        await self.async_save()
