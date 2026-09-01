"""FoxAir coordinator — tiered pymodbus polling (quick 30s / medium 120s / rare 300/600s) — revert from modbus_connection."""

import json
import pathlib
import asyncio
import logging
import time
import math
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryNotReady
from pymodbus.client import AsyncModbusTcpClient

from .const import MODBUS_MAX_SPAN, MODBUS_MAX_GAP, QUICK_INTERVAL, MEDIUM_INTERVAL, RARE_INTERVAL, CORE_MAIN_ADDRS

_LOGGER = logging.getLogger(__name__)

# ── Suppress noisy pymodbus transient-error logging ──────────────
# The EW11 gateway drops one packet every ~10 min (normal). Pymodbus
# logs each as ERROR "No response received after 3 retries" and the
# coordinator also logged at WARNING — double spam in HOAS "Errors".
# We downgrade coordinator logs to DEBUG and filter the pymodbus logger
# so only unexpected errors surface.
try:
    _pm_logger = logging.getLogger("pymodbus")
    _pm_logger.addFilter(lambda rec: "No response received after 3 retries" not in rec.getMessage())
    _pm2 = logging.getLogger("pymodbus.logging")
    _pm2.addFilter(lambda rec: "No response received after 3 retries" not in rec.getMessage())
except Exception:
    pass

# Config is loaded LAZILY off the event loop (see FoxAirCoordinator._load_config),
# because reading files at import time triggers HA 2026's blocking-call guard and
# aborts setup. These start empty and are filled once before the first poll.
_CONFIG_PATH = pathlib.Path(__file__).parent / "data/foxair_config.json"
_CFG: dict = {}
_TYPES: dict = {}
_DEAD_RANGES: list[tuple[int, int]] = []
_MARKERS: dict = {}


def _read_config_file() -> dict:
    """Synchronous file read — MUST be called inside async_add_executor_job."""
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _apply_config(cfg: dict) -> None:
    global _CFG, _TYPES, _DEAD_RANGES, _MARKERS
    _CFG = cfg or {}
    _TYPES = _CFG.get("types", {})
    _DEAD_RANGES = [(lo, hi) for lo, hi in _CFG.get("dead_ranges", [])]
    _MARKERS = _CFG.get("markers", {})


def s16(v): return v - 0x10000 if v & 0x8000 else v


def _decode_hhmm(raw: int) -> str:
    h = (raw >> 8) & 0xFF
    m = raw & 0xFF
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return str(s16(raw))


def scaled(dtype, raw):
    """Scale raw register value using types table from foxair_config.json."""
    dtype = (dtype or "RAW").upper()
    sv = s16(raw)
    spec = _TYPES.get(dtype)
    if spec:
        return sv * spec.get("scale", 1.0)
    # Fallback for unknown types
    return float(sv)


class FoxAirCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name="FoxAir", update_interval=timedelta(seconds=30))
        self.entry = entry
        self._entry_id = entry.entry_id
        self.client = None
        self.data = {}
        self.stats = {"polls": 0, "errors": 0, "last_ms": 0, "quick_polls": 0, "medium_polls": 0, "rare_polls": 0}
        self._regmap = None
        self._metadata = {}
        self._lock = asyncio.Lock()
        self._poll_counter = 0
        self._flow_ema = 0.0
        # debounced write coalescer: 3s window merges rapid changes into one FC16
        self._write_pending: dict[int, int] = {}
        self._write_pending_metas: dict[int, dict] = {}
        self._write_futures: list[asyncio.Future] = []
        self._write_flush_task: asyncio.Task | None = None
        self._write_delay = 3.0
        self._medium_done = False
        self._rare_done = False
        self._burst_task: asyncio.Task | None = None

    async def _load_config(self) -> None:
        """Load foxair_config.json off the event loop (HA 2026 blocks sync I/O)."""
        if _CFG:
            return
        cfg = await self.hass.async_add_executor_job(_read_config_file)
        _apply_config(cfg)

    async def _load_map(self):
        p = pathlib.Path(__file__).parent / "data/foxair_phnix_registers.json"

        def _load_reg():
            return json.loads(p.read_text(encoding="utf-8-sig"))

        self._regmap = await self.hass.async_add_executor_job(_load_reg)
        try:
            mp = pathlib.Path(__file__).parent / "data/foxair_metadata.json"

            def _load_meta():
                return json.loads(mp.read_text(encoding="utf-8-sig"))

            self._metadata = await self.hass.async_add_executor_job(_load_meta)
        except (OSError, json.JSONDecodeError) as e:
            _LOGGER.debug("metadata load failed: %s", e)
            self._metadata = {}

    def get_metadata(self, addr: int) -> dict:
        return (getattr(self, "_metadata", {}) or {}).get(str(addr), {})

    def marker(self, marker_name: str):
        """Look up a functional address marker from foxair_config.json.

        Returns the full marker record, e.g. {"addr_single": {...}, "addr_list": [...]}
        or {} if not found. Callers extract via .get("addr_single") / .get("addr_list").
        """
        return _MARKERS.get(marker_name, {})

    def _tier_addrs(self, tier: str, expert: bool) -> set[int]:
        if not self._metadata:
            return set()
        # Known-dead ranges come from foxair_config.json (dead_ranges).
        dead_addrs = {a for lo, hi in _DEAD_RANGES for a in range(lo, hi + 1)}
        # Expert gating applies to ALL tiers: with expert off, expert-block addrs are not polled.
        # Permanently hidden addrs (reserved/header/system/service) are NEVER polled.
        return {
            int(k)
            for k, v in self._metadata.items()
            if v.get("poll_tier") == tier and k.isdigit()
            and v.get("risk") != "blocked"
            and not v.get("hidden")
            and int(k) not in dead_addrs
            and int(k) < 50000
            and (expert or not v.get("requires_expert"))
        }

    def _validate_write(self, addr: int, value: float) -> tuple[bool, dict, str]:
        meta = self.get_metadata(addr)
        # special: power (1011) and mode (1012) have known limits even if metadata lacks them
        status = self.marker("status") or {}
        power_addr = status.get("addr_single", {}).get("power")
        mode_addr = status.get("addr_single", {}).get("mode")
        if addr == power_addr:
            if not math.isfinite(value) or not (0 <= value <= 1):
                return False, meta, f"1011 out of range [0,1] got {value}"
            return True, meta, ""
        if addr == mode_addr:
            if not math.isfinite(value) or not (0 <= value <= 4):
                return False, meta, f"1012 out of range [0,4] got {value}"
            if not meta.get("editable"):
                # allow even if metadata says not editable/empty code — this is core hvac preset
                meta = {**meta, "editable": True}
            return True, meta, ""
        if not meta.get("editable"):
            return False, meta, f"not editable group={meta.get('group')} risk={meta.get('risk')}"
        if meta.get("requires_expert") and not self.entry.options.get("enable_expert"):
            return False, meta, f"requires expert mode code={meta.get('code')}"
        if meta.get("hidden"):
            return False, meta, f"addr {addr} is reserved/system — hidden by design"
        if not math.isfinite(value):
            # TIME_HHMM may be string like "12:34" passed as float? already checked finite for numeric
            # allow time platform with string
            if meta.get("platform") == "time":
                return True, meta, ""
            return False, meta, "non-finite value"
        lo, hi = meta.get("min"), meta.get("max")
        # Select / time platforms are value_map or enum driven — raw values are
        # discrete enum choices (0, 1, 2, ...), NOT a continuous numeric range.
        # Their metadata min/max is informational (for number/slider fallback only)
        # and must NOT gate a write: e.g. H36 (1236) select value_map {0: Off, 1: On}
        # but metadata has min=1.0 from a stale parse — rejecting value=0 breaks
        # switching from curve to fixed. Validate only as a Modbus word (0..65535).
        platform = meta.get("platform")
        dtype = (meta.get("type") or "RAW").upper()
        if platform in ("select", "time") or meta.get("has_value_map"):
            if dtype in ("SG_MODE", "TIMER_MODE", "MODE_0_4"):
                if not (0 <= value <= 10):
                    return False, meta, f"{dtype} out of range [0,10] got {value}"
            elif dtype in ("TIME_HHMM", "TIMER_BITPAIR", "SG_MODE", "BITFIELD", "FAULT_BITS"):
                pass  # enum/time types — always valid Modbus word
            elif dtype == "RAW" and meta.get("risk") in ("safe", "advanced"):
                if not (0 <= value <= 65535):
                    return False, meta, f"RAW out of range [0,65535] got {value}"
            elif dtype == "DIGI1" and not meta.get("has_value_map"):
                # DIGI1 without value_map acts as a 0..5 selector — still a word
                if not (0 <= value <= 5):
                    return False, meta, f"DIGI1 out of range [0,5] got {value}"
            return True, meta, ""
        # Number platforms with explicit limits are range-gated as sliders.
        if meta.get("editable") and lo is None and hi is None:
            if dtype in ("TIME_HHMM", "TIMER_BITPAIR", "SG_MODE", "BITFIELD", "FAULT_BITS"):
                return True, meta, ""
            if dtype == "RAW" and meta.get("risk") in ("safe", "advanced"):
                # safe RAW like Sprachauswahl — allow 0-65535, device will clip
                if not (0 <= value <= 65535):
                    return False, meta, f"RAW out of range [0,65535] got {value}"
                return True, meta, ""
            return False, meta, f"missing limits code={meta.get('code')}"
        if lo is not None and hi is not None and not (lo - 1e-9 <= value <= hi + 1e-9):
            return False, meta, f"out of range [{lo}, {hi}]"
        return True, meta, ""

    def _coerce_write_value(self, addr: int, value: float, meta: dict):
        dtype = meta.get("type", "RAW")
        if dtype in ("TEMP", "TEMP1"):
            raw = int(round(value * 10))
        elif dtype in ("TEMP05",):
            raw = int(round(value * 2))
        elif dtype in ("DIGI5", "POWER_KW_X10", "BAR_X10", "FLOW_M3H_X10", "AMP_X10"):
            raw = int(round(value * 10))
        elif dtype == "FLOW_M3H_X100":
            raw = int(round(value * 100))
        elif dtype == "COP_X100":
            raw = int(round(value * 100))
        elif dtype == "AMP_X2":
            raw = int(round(value * 2))
        elif dtype == "DIGI6":
            raw = int(round(value * 1000))
        elif dtype == "DIGI19":
            raw = int(round(value * 100))
        elif dtype == "DIGI4":
            raw = int(round(value * 5))
        else:
            raw = int(round(value))
        if raw < 0:
            raw = raw & 0xFFFF
        else:
            raw = int(raw) & 0xFFFF
        return raw

    # ── debounced batch writer ──────────────────────────────────
    def _schedule_flush(self):
        if self._write_flush_task and not self._write_flush_task.done():
            self._write_flush_task.cancel()
        self._write_flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self):
        try:
            await asyncio.sleep(self._write_delay)
            await self._do_flush()
        except asyncio.CancelledError:
            pass

    async def _do_flush(self):
        if not self._write_pending:
            # nothing to do, resolve futures as ok
            futs = list(self._write_futures)
            self._write_futures.clear()
            for f in futs:
                if not f.done():
                    f.set_result(True)
            self._write_flush_task = None
            return
        pending = dict(self._write_pending)
        metas = dict(self._write_pending_metas)
        futs = list(self._write_futures)
        self._write_pending.clear()
        self._write_pending_metas.clear()
        self._write_futures.clear()
        self._write_flush_task = None
        # group contiguous addrs into single FC16 blocks
        sorted_addrs = sorted(pending.keys())
        blocks: list[tuple[int, list[int]]] = []
        cur_start = sorted_addrs[0]
        cur_vals = [pending[cur_start]]
        cur_end = cur_start
        for a in sorted_addrs[1:]:
            if a == cur_end + 1:
                cur_vals.append(pending[a])
                cur_end = a
            else:
                blocks.append((cur_start, cur_vals))
                cur_start = a
                cur_vals = [pending[a]]
                cur_end = a
        blocks.append((cur_start, cur_vals))
        cfg = self.entry.data
        sid = cfg.get("slave", 1)
        overall_ok = True
        # Serialize on the SINGLE shared connection (self.client) under self._lock.
        # The EW11 gateway is single-client and bridges/mixes streams when a second
        # TCP client connects — that produced the "transaction_id=37 but got id=1"
        # frame-corruption errors in the poll log after every UI write.
        async with self._lock:
            if not self.client or not getattr(self.client, "connected", False):
                try:
                    if self.client:
                        self.client.close()
                except Exception:
                    pass
                self.client = AsyncModbusTcpClient(host=cfg["host"], port=cfg["port"], timeout=8)
                okc = await self.client.connect()
            else:
                okc = True
            if not okc:
                _LOGGER.error("Write batch connect failed %s:%s", cfg["host"], cfg["port"])
                overall_ok = False
            else:
                for addr, vals in blocks:
                    try:
                        await asyncio.sleep(0.25)  # EW11 half-duplex pacing
                        try:
                            rr = await self.client.write_registers(address=addr, values=vals, slave=sid)
                        except TypeError:
                            rr = await self.client.write_registers(address=addr, values=vals, device_id=sid)
                        if rr.isError():
                            _LOGGER.error("Write batch %s %s error %s", addr, vals, rr)
                            overall_ok = False
                        else:
                            codes = [metas.get(addr + i, {}).get("code", str(addr + i)) for i in range(len(vals))]
                            _LOGGER.debug("Write OK FC16 %s (+%s) %s -> %s", addr, len(vals) - 1, codes, vals)
                    except Exception as e:
                        _LOGGER.error("Write batch %s exception %s", addr, e)
                        overall_ok = False
                if overall_ok:
                    await asyncio.sleep(0.35)
                    for addr in pending:
                        try:
                            try:
                                rr2 = await self.client.read_holding_registers(address=addr, count=1, slave=sid)
                            except TypeError:
                                rr2 = await self.client.read_holding_registers(address=addr, count=1, device_id=sid)
                            if not rr2.isError() and getattr(rr2, "registers", None):
                                raw2 = rr2.registers[0]
                                info = (self._regmap or {}).get(str(addr)) or {"type": metas[addr].get("type", "RAW")}
                                val2 = scaled(info.get("type", metas[addr].get("type", "RAW")), raw2)
                                self.data[addr] = {"raw": raw2, "value": val2, "info": info}
                        except Exception as e:
                            _LOGGER.debug("readback %s failed %s", addr, e)
                    self.async_update_listeners()
        # Request a fresh poll outside the lock (it re-acquires it).
        if overall_ok:
            self.hass.async_create_task(self.async_request_refresh())
        for f in futs:
            if not f.done():
                f.set_result(overall_ok)

    async def async_write_register(self, addr: int, value: float) -> bool:
        ok, meta, reason = self._validate_write(addr, value)
        if not ok:
            _LOGGER.error("Write blocked: %s %s", addr, reason)
            return False
        raw = self._coerce_write_value(addr, value, meta)
        fut = self.hass.loop.create_future()
        self._write_pending[addr] = raw
        self._write_pending_metas[addr] = meta
        self._write_futures.append(fut)
        self._schedule_flush()
        _LOGGER.debug("Write queued %s -> %s (delay %.1fs) pending=%s", addr, raw, self._write_delay, sorted(self._write_pending.keys()))
        return await fut

    async def async_write_many(self, mapping: dict[int, float]) -> bool:
        """Batch write: mapping addr->scaled value, coalesced into one FC16 if contiguous, debounced 3s."""
        if not mapping:
            return True
        metas: dict[int, dict] = {}
        raws: dict[int, int] = {}
        for addr, value in mapping.items():
            ok, meta, reason = self._validate_write(addr, float(value))
            if not ok:
                _LOGGER.error("Write blocked: %s %s", addr, reason)
                return False
            raw = self._coerce_write_value(addr, float(value), meta)
            raws[addr] = raw
            metas[addr] = meta
        fut = self.hass.loop.create_future()
        for addr, raw in raws.items():
            self._write_pending[addr] = raw
            self._write_pending_metas[addr] = metas[addr]
        self._write_futures.append(fut)
        self._schedule_flush()
        _LOGGER.debug("Write many queued %s pending=%s", raws, sorted(self._write_pending.keys()))
        return await fut

    def _batches_for_addrs(self, addrs: set[int], max_span=45, max_gap=8) -> list[tuple[int, int]]:
        if not addrs:
            return []
        sorted_addrs = sorted(addrs)
        batches: list[tuple[int, int]] = []
        cur_start = sorted_addrs[0]
        cur_end = sorted_addrs[0]
        for a in sorted_addrs[1:]:
            if a - cur_end <= max_gap and (a - cur_start + 1) <= max_span:
                # Check if this batch would span across a dead register range.
                # Even though dead addrs aren't in the `addrs` set, a contiguous
                # Modbus read (start..end) would include them and trigger EW11
                # corruption.  Split the batch before the dead zone.
                would_span_dead = any(
                    cur_start <= d_end and a >= d_start
                    for d_start, d_end in _DEAD_RANGES
                )
                if would_span_dead:
                    batches.append((cur_start, cur_end - cur_start + 1))
                    cur_start = a
                    cur_end = a
                    continue
                cur_end = a
            else:
                batches.append((cur_start, cur_end - cur_start + 1))
                cur_start = a
                cur_end = a
        batches.append((cur_start, cur_end - cur_start + 1))
        return batches

    async def _async_update_data(self):
        if self._regmap is None:
            await self._load_map()
        cfg = self.entry.data
        if not self.client or not getattr(self.client, "connected", False):
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
            self.client = AsyncModbusTcpClient(host=cfg["host"], port=cfg["port"], timeout=8)
            ok = await self.client.connect()
            if not ok:
                raise ConfigEntryNotReady(f"Modbus connect failed {cfg['host']}:{cfg['port']}")
        async with self._lock:
            # Tier selection
            self._poll_counter += 1
            is_first = self.stats["polls"] == 0
            enable_expert = bool(self.entry.options.get("enable_expert"))
            # Startup catch-up: first refresh polls quick only (fast setup);
            # medium/rare follow on later ticks via the normal schedule + _rare_done.
            if is_first:
                do_quick = True
                do_medium = False
                do_rare = False
            else:
                do_quick = True
                do_medium = (self._poll_counter % MEDIUM_INTERVAL == 0)
                rare_interval = RARE_INTERVAL * 2 if enable_expert else RARE_INTERVAL  # 600s expert, 300s non-expert
                do_rare = (self._poll_counter % rare_interval == 0)
                # startup catch-up: poll 2 = +medium, poll 3 = +rare (spread, no burst)
                if not self._medium_done and self._poll_counter >= 2:
                    do_medium = True
                    self._medium_done = True
                if not self._rare_done and self._poll_counter >= 3:
                    do_rare = True
                    self._rare_done = True
            addrs: set[int] = set()
            if do_quick:
                addrs.update(self._tier_addrs("quick", enable_expert))
            if do_medium:
                addrs.update(self._tier_addrs("medium", enable_expert))
            if do_rare:
                addrs.update(self._tier_addrs("rare", enable_expert))
            # Startup catch-up: always pull core main-device control registers
            # (1011/1012/1014/1030 etc.) on the FIRST poll regardless of tier,
            # so user-facing entities like "Allow defrost" (1014) and Silent Mode
            # (1030) are populated immediately instead of waiting for the rare
            # tier's first cycle (~90s) to render "unknown".
            if is_first:
                addrs.update(CORE_MAIN_ADDRS)
            # Fallback to at least quick if empty
            if not addrs:
                addrs = self._tier_addrs("quick", enable_expert)
            batches = self._batches_for_addrs(addrs, max_span=45, max_gap=8)
            t0 = time.monotonic()
            out: dict[int, dict] = {}
            for addr, qty in batches:
                try:
                    sid = cfg.get("slave", 1)
                    await asyncio.sleep(0.22)
                    try:
                        rr = await self.client.read_holding_registers(address=addr, count=qty, slave=sid)
                    except TypeError:
                        rr = await self.client.read_holding_registers(address=addr, count=qty, device_id=sid)
                    if rr.isError():
                        self.stats["errors"] += 1
                        _LOGGER.debug("read %s/%s error %s", addr, qty, rr)
                        continue
                    regs = rr.registers
                    for i, raw in enumerate(regs):
                        a = addr + i
                        info = self._regmap.get(str(a))
                        if not info:
                            continue
                        if info.get("type") == "BLOCK":
                            continue
                        # Only keep if this addr was requested (avoid filling gaps with stale)
                        if a not in addrs:
                            continue
                        out[a] = {"raw": raw, "value": scaled(info.get("type", "RAW"), raw), "info": info}
                except Exception as e:
                    self.stats["errors"] += 1
                    self.stats["last_error"] = str(e)
                    _LOGGER.debug("poll %s/%s exception %s", addr, qty, e)
                    # Connection-level failure (EW11 idle-drop, no response): abort the
                    # rest of this cycle's batches instead of storming a dead socket;
                    # next poll reconnects.
                    if type(e).__name__ in ("ConnectionException", "ConnectionResetError",
                                            "CancelledError") or "No response" in str(e) or "Connection" in str(e):
                        try:
                            self.client.close()
                        except Exception:
                            pass
                        self.client = None
                        break
                    continue
            self.stats["polls"] += 1
            if do_quick:
                self.stats["quick_polls"] += 1
            if do_medium:
                self.stats["medium_polls"] += 1
            if do_rare:
                self.stats["rare_polls"] += 1
            self.stats["last_ms"] = int((time.monotonic() - t0) * 1000)
            self.stats["last_tiers"] = f"quick={do_quick} medium={do_medium} rare={do_rare} batches={len(batches)} addrs={len(addrs)}"
            _LOGGER.debug("Poll #%s tiers quick=%s medium=%s rare=%s batches=%s addrs=%s ms=%s", self._poll_counter, do_quick, do_medium, do_rare, len(batches), len(addrs), self.stats["last_ms"])
            if not out and self.data:
                _LOGGER.debug("Poll returned empty, keeping prior data")
                return self.data
            if self.data:
                merged = dict(self.data)
                merged.update(out)
                self.data = merged
            else:
                self.data = out
            # Startup burst: after the first quick poll, immediately fetch
            # medium+rare tiers in background so expert entities don't stay
            # "unknown" for 60-90s waiting for poll #2/#3. Runs once, paced
            # with EW11 delays, serialized on the same _lock.
            if is_first and not self._burst_task:
                self._burst_task = self.hass.async_create_task(self._startup_burst())
            return self.data

    async def _fetch_addrs(self, addrs: set[int]) -> dict[int, dict]:
        """Read a set of addrs in batches (same EW11 pacing/dead-range logic)."""
        if not addrs:
            return {}
        cfg = self.entry.data
        batches = self._batches_for_addrs(addrs, max_span=45, max_gap=8)
        out: dict[int, dict] = {}
        async with self._lock:
            if not self.client or not getattr(self.client, "connected", False):
                if self.client:
                    try:
                        self.client.close()
                    except Exception:
                        pass
                    self.client = None
                self.client = AsyncModbusTcpClient(host=cfg["host"], port=cfg["port"], timeout=8)
                ok = await self.client.connect()
                if not ok:
                    _LOGGER.debug("burst connect failed %s:%s", cfg["host"], cfg["port"])
                    return {}
            for addr, qty in batches:
                try:
                    sid = cfg.get("slave", 1)
                    await asyncio.sleep(0.22)
                    try:
                        rr = await self.client.read_holding_registers(address=addr, count=qty, slave=sid)
                    except TypeError:
                        rr = await self.client.read_holding_registers(address=addr, count=qty, device_id=sid)
                    if rr.isError():
                        self.stats["errors"] += 1
                        _LOGGER.debug("burst read %s/%s error %s", addr, qty, rr)
                        continue
                    regs = rr.registers
                    for i, raw in enumerate(regs):
                        a = addr + i
                        if a not in addrs:
                            continue
                        info = self._regmap.get(str(a))
                        if not info or info.get("type") == "BLOCK":
                            continue
                        out[a] = {"raw": raw, "value": scaled(info.get("type", "RAW"), raw), "info": info}
                except Exception as e:
                    self.stats["errors"] += 1
                    _LOGGER.debug("burst poll %s/%s exception %s", addr, qty, e)
                    if type(e).__name__ in ("ConnectionException", "ConnectionResetError", "CancelledError") or "No response" in str(e) or "Connection" in str(e):
                        try:
                            self.client.close()
                        except Exception:
                            pass
                        self.client = None
                        break
        return out

    async def async_burst_missing(self, delay: float = 0.0):
        """Fetch any poll-tier addr missing from self.data (expert-aware).

        Used both by the startup burst and when options change (e.g. expert
        mode enabled) so newly visible entities don't sit at Unknown until
        the next scheduled medium/rare cycle (~60-90 s).
        """
        try:
            if delay:
                await asyncio.sleep(delay)
            enable_expert = bool(self.entry.options.get("enable_expert"))
            for tier in ("medium", "rare"):
                done_flag = f"_{tier}_done"
                # Skip tier already fetched in this coordinator lifetime
                if getattr(self, done_flag, False):
                    continue
                addrs = self._tier_addrs(tier, enable_expert)
                addrs = {a for a in addrs if a not in self.data}
                if not addrs:
                    # Mark done so we don't retry every call when empty
                    setattr(self, done_flag, True)
                    continue
                _LOGGER.debug("Burst missing: fetching %s tier %s addrs (delay=%.1f)", tier, len(addrs), delay)
                out = await self._fetch_addrs(addrs)
                if out:
                    self.data = {**self.data, **out}
                    setattr(self, done_flag, True)
                    key = f"{tier}_polls"
                    self.stats[key] = self.stats.get(key, 0) + 1
                    self.async_update_listeners()
                _LOGGER.debug("Burst missing %s done +%s regs", tier, len(out))
                # Pace between tiers: 0.35s for config-change bursts, 1.5s for startup
                await asyncio.sleep(1.5 if delay else 0.35)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.debug("burst missing failed: %s", e)

    async def _startup_burst(self):
        """Background fetch of medium+rare after first quick poll."""
        await self.async_burst_missing(delay=1.5)
        # Rare was paced inside async_burst_missing; startup path needs the
        # second-tier delay preserved (1.5s before medium, 0.35s between tiers)
        # so EW11 isn't hammered. The generic method already handles both.
