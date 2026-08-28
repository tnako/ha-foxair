"""FoxAir coordinator — tiered pymodbus polling (quick 30s / medium 120s / rare 300/600s) — reverted from modbus_connection due to EW11 extra data handling."""

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

_LOGGER = logging.getLogger(__name__)

# Tier intervals (multiples of 30s base)
QUICK_INTERVAL = 1  # every poll (30s)
MEDIUM_INTERVAL = 4  # 120s
RARE_INTERVAL = 10  # 300s (600s when expert)


def s16(v): return v - 0x10000 if v & 0x8000 else v


def _decode_hhmm(raw: int) -> str:
    h = (raw >> 8) & 0xFF
    m = raw & 0xFF
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return str(s16(raw))


def scaled(dtype, raw):
    dtype = (dtype or "RAW").upper()
    sv = s16(raw)
    if dtype in ("TEMP", "TEMP1"):
        return sv / 10.0
    if dtype in ("TEMP05", "TEMP_0_5", "STEP_0_5C"):
        return sv / 2.0
    if dtype in ("DIGI5", "POWER_KW_X10", "KW_X10", "BAR_X10", "PRESSURE_BAR_X10", "FLOW_M3H_X10", "FLOW_X10", "AMP_X10", "CURRENT_A_X10"):
        return sv / 10.0
    if dtype in ("FLOW_M3H_X100", "FLOW_X100", "COP_X100", "COP100"):
        return sv / 100.0
    if dtype in ("AMP_X2", "CURRENT_A_X2"):
        return sv / 2.0
    if dtype in ("VOLT", "VOLTS", "V", "WATT", "WATTS", "POWER_W", "RPM", "FAN_RPM", "KWH", "ENERGY_KWH", "KWH_PER_H", "KW_PER_H"):
        return float(sv)
    if dtype == "DIGI6":
        return sv / 1000.0
    if dtype == "DIGI19":
        return sv / 100.0
    if dtype == "DIGI4":
        return sv / 5.0
    if dtype == "DIGI1":
        return float(sv)
    if dtype in ("TIME_HHMM", "HHMM"):
        return _decode_hhmm(raw)
    if dtype in ("BITFIELD", "FAULT_BITS", "TIMER_BITPAIR", "TIMER_MODE", "MODE_0_4", "SG_MODE", "RUN_MODE", "DAYS", "HOURS", "MINUTES", "SECONDS", "STEPS_N", "EEV_STEPS", "STEPS", "HZ", "FREQUENCY_HZ"):
        return float(sv)
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

    def _tier_addrs(self, tier: str) -> set[int]:
        if not self._metadata:
            return set()
        return {int(k) for k, v in self._metadata.items() if v.get("poll_tier") == tier and k.isdigit()}

    def _validate_write(self, addr: int, value: float) -> tuple[bool, dict, str]:
        meta = self.get_metadata(addr)
        if not meta.get("editable"):
            return False, meta, f"not editable group={meta.get('group')} risk={meta.get('risk')}"
        if meta.get("requires_expert") and not self.entry.options.get("enable_expert"):
            return False, meta, f"requires expert mode code={meta.get('code')}"
        if not math.isfinite(value):
            return False, meta, "non-finite value"
        lo, hi = meta.get("min"), meta.get("max")
        if meta.get("editable") and lo is None and hi is None:
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

    async def async_write_register(self, addr: int, value: float) -> bool:
        ok, meta, reason = self._validate_write(addr, value)
        if not ok:
            _LOGGER.error("Write blocked: %s %s", addr, reason)
            return False
        raw = self._coerce_write_value(addr, value, meta)
        cfg = self.entry.data
        sid = cfg.get("slave", 1)
        write_client = AsyncModbusTcpClient(host=cfg["host"], port=cfg["port"], timeout=8)
        try:
            okc = await write_client.connect()
            if not okc:
                _LOGGER.error("Write %s connect failed %s:%s", addr, cfg["host"], cfg["port"])
                return False
            try:
                rr = await write_client.write_registers(address=addr, values=[raw], slave=sid)
            except TypeError:
                rr = await write_client.write_registers(address=addr, values=[raw], device_id=sid)
            if rr.isError():
                _LOGGER.error("Write %s error %s", addr, rr)
                return False
            _LOGGER.warning("Write OK FC16 %s [%s] -> raw %s (scaled %.2f)", addr, meta.get("code"), raw, value)
            await asyncio.sleep(0.35)
            try:
                try:
                    rr2 = await write_client.read_holding_registers(address=addr, count=1, slave=sid)
                except TypeError:
                    rr2 = await write_client.read_holding_registers(address=addr, count=1, device_id=sid)
                if not rr2.isError() and getattr(rr2, "registers", None):
                    raw2 = rr2.registers[0]
                    info = (self._regmap or {}).get(str(addr)) or {"type": meta.get("type", "RAW")}
                    val2 = scaled(info.get("type", meta.get("type", "RAW")), raw2)
                    self.data[addr] = {"raw": raw2, "value": val2, "info": info}
                    self.async_update_listeners()
                    _LOGGER.warning("Write verify %s -> raw %s (scaled %.2f) fast-path", addr, raw2, val2)
            except Exception as e:
                _LOGGER.debug("fast readback %s failed %s", addr, e)
            self.hass.async_create_task(self.async_request_refresh())
            return True
        except Exception as e:
            _LOGGER.error("Write %s exception %s", addr, e)
            return False
        finally:
            try:
                write_client.close()
            except Exception:
                pass

    def _batches_for_addrs(self, addrs: set[int], max_span=45, max_gap=8) -> list[tuple[int, int]]:
        if not addrs:
            return []
        sorted_addrs = sorted(addrs)
        batches: list[tuple[int, int]] = []
        cur_start = sorted_addrs[0]
        cur_end = sorted_addrs[0]
        for a in sorted_addrs[1:]:
            if a - cur_end <= max_gap and (a - cur_start + 1) <= max_span:
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
            do_quick = True
            do_medium = is_first or (self._poll_counter % MEDIUM_INTERVAL == 0)
            enable_expert = bool(self.entry.options.get("enable_expert"))
            rare_interval = RARE_INTERVAL * 2 if enable_expert else RARE_INTERVAL  # 600s expert, 300s non-expert
            do_rare = (self._poll_counter % rare_interval == 0)
            addrs: set[int] = set()
            if do_quick:
                addrs.update(self._tier_addrs("quick"))
            if do_medium:
                addrs.update(self._tier_addrs("medium"))
            if do_rare:
                rare_addrs = self._tier_addrs("rare")
                if not enable_expert:
                    rare_addrs = {a for a in rare_addrs if self._metadata.get(str(a), {}).get("risk") == "safe"}
                    if not rare_addrs:
                        do_rare = False
                    else:
                        addrs.update(rare_addrs)
                else:
                    addrs.update(rare_addrs)
            # Fallback to at least quick if empty
            if not addrs:
                addrs = self._tier_addrs("quick")
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
                        _LOGGER.warning("read %s/%s error %s", addr, qty, rr)
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
                    _LOGGER.warning("poll %s exception %s", addr, e)
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
            return self.data
