"""FoxAir coordinator — ModbusConnection + foxair-modbus pooled reads."""
import json
import pathlib
import asyncio
import logging
import time
import math
from datetime import timedelta

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

try:
    from .vendor.foxair_modbus import FoxAir
except Exception as e:
    try:
        from custom_components.foxair.vendor.foxair_modbus import FoxAir
    except Exception as e2:
        FoxAir = None
        _LOGGER.error("foxair_modbus vendor missing: %s / %s", e, e2)


def _decode_hhmm(raw: int) -> str:
    h = (raw >> 8) & 0xFF
    m = raw & 0xFF
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    sv = raw - 0x10000 if raw & 0x8000 else raw
    return str(sv)


class FoxAirCoordinator(DataUpdateCoordinator):
    # Tier intervals (multiples of 30s base)
    QUICK_INTERVAL = 1  # every poll (30s)
    MEDIUM_INTERVAL = 4  # every 4 polls (120s)
    RARE_INTERVAL = 10  # every 10 polls (300s)

    def __init__(self, hass, entry, unit, conn=None):
        super().__init__(hass, _LOGGER, name="FoxAir", update_interval=timedelta(seconds=30))
        self.entry = entry
        self._entry_id = entry.entry_id
        self.unit = unit
        self._conn = conn
        self.data = {}
        self.stats = {"polls": 0, "errors": 0, "last_ms": 0, "quick_polls": 0, "medium_polls": 0, "rare_polls": 0}
        self._regmap = None
        self._metadata = {}
        self._lock = asyncio.Lock()
        self._flow_ema = 0.0
        self._poll_counter = 0
        if FoxAir is not None and unit is not None:
            self.foxair = FoxAir(unit)
        else:
            self.foxair = None

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
        if dtype in ("DIGI1", "MODE_0_4", "SG_MODE", "TIMER_BITPAIR", "TIMER_MODE", "BITFIELD", "STEPS_N", "RAW"):
            return int(round(float(value)))
        return float(value)

    def _build_data(self) -> dict:
        out: dict[int, dict] = {}
        assert self.foxair is not None
        for name, fld in self.foxair.declared_fields.items():
            if not name.startswith("reg_"):
                continue
            try:
                a = int(name.split("_", 1)[1])
            except (ValueError, IndexError):
                continue
            val = getattr(self.foxair, name, None)
            if val is None:
                continue
            info = self._regmap.get(str(a)) if self._regmap else None
            if not info or info.get("type") == "BLOCK":
                continue
            if info.get("type") == "TIME_HHMM" and isinstance(val, int):
                try:
                    v = _decode_hhmm(val)
                    out[a] = {"raw": val, "value": v, "info": info}
                    continue
                except Exception:
                    pass
            out[a] = {"raw": val, "value": val, "info": info}
        return out

    async def async_write_register(self, addr: int, value: float) -> bool:
        ok, meta, reason = self._validate_write(addr, value)
        if not ok:
            _LOGGER.error("Write blocked: %s %s", addr, reason)
            return False
        if self.foxair is None:
            _LOGGER.error("Write failed: foxair model not initialized")
            return False
        field = f"reg_{addr}"
        if field not in self.foxair.declared_fields:
            _LOGGER.error("Write blocked: %s no field %s in model", addr, field)
            return False
        try:
            to_write = self._coerce_write_value(addr, value, meta)
            await self.foxair.write(field, to_write)
        except Exception as e:
            _LOGGER.error("Write %s exception %s", addr, e)
            return False
        _LOGGER.warning("Write OK %s [%s] -> %.2f", addr, meta.get("code"), value)
        await asyncio.sleep(0.35)
        try:
            await self.foxair.async_update()
            out = self._build_data()
            if out:
                merged = dict(self.data) if self.data else {}
                merged.update(out)
                self.data = merged
                self.async_update_listeners()
                _LOGGER.warning("Write verify %s fast-path updated", addr)
        except Exception as e:
            _LOGGER.debug("fast readback %s failed %s", addr, e)
        self.hass.async_create_task(self.async_request_refresh())
        return True

    def _tier_addrs(self, tier: str) -> set[int]:
        if not self._metadata:
            return set()
        return {int(k) for k, v in self._metadata.items() if v.get("poll_tier") == tier and k.isdigit()}

    async def _async_update_data(self):
        if self._regmap is None:
            await self._load_map()
        if self.foxair is None:
            raise UpdateFailed("FoxAir model not initialized (vendor missing)")
        async with self._lock:
            t0 = time.monotonic()
            # Determine which tiers to poll this cycle
            self._poll_counter += 1
            is_first = self.stats["polls"] == 0
            # Quick always, medium every 4 (and on first poll to seed), rare every 10 (expert only, not on first to keep first poll light: 75+42=117 regs vs 469)
            do_quick = True
            do_medium = is_first or (self._poll_counter % self.MEDIUM_INTERVAL == 0)
            enable_expert = bool(self.entry.options.get("enable_expert"))
            do_rare = enable_expert and (self._poll_counter % self.RARE_INTERVAL == 0)
            # Build addr set for this poll
            addrs: set[int] = set()
            if do_quick:
                addrs.update(self._tier_addrs("quick"))
            if do_medium:
                addrs.update(self._tier_addrs("medium"))
            if do_rare:
                # When non-expert and not first, skip rare entirely (saves ~18 batches)
                rare_addrs = self._tier_addrs("rare")
                if not enable_expert and not is_first:
                    # Keep only safe rare for non-expert (e.g., fault codes) - or skip all to save bus
                    rare_addrs = {a for a in rare_addrs if self._metadata.get(str(a), {}).get("risk") == "safe"}
                    # If still many, skip entirely for non-expert to maximize bus calmness
                    # Uncomment next line to skip rare completely when non-expert:
                    # rare_addrs = set()
                    if not rare_addrs:
                        do_rare = False
                    else:
                        addrs.update(rare_addrs)
                else:
                    addrs.update(rare_addrs)
            # Filter to fields actually present in FoxAir model (excludes BLOCK/ProductKey/50000+)
            model_addrs = {int(n.split("_", 1)[1]) for n in self.foxair.declared_fields if n.startswith("reg_")}
            poll_addrs = addrs & model_addrs
            # Fallback to quick if filter yields empty (should not happen)
            if not poll_addrs:
                poll_addrs = {int(n.split("_", 1)[1]) for n in self.foxair.declared_fields if n.startswith("reg_") and self._metadata.get(n.split("_", 1)[1], {}).get("poll_tier") == "quick"}
            # Temporarily filter FoxAir to poll only this tier's addrs (pooled reads still use max_span 45 / max_gap 8)
            orig_fields = self.foxair.declared_fields
            # Instance-level shadow to avoid mutating class
            filtered = {k: v for k, v in orig_fields.items() if k.startswith("reg_") and int(k.split("_", 1)[1]) in poll_addrs}
            # If filtering would remove all, fall back to full
            if not filtered:
                filtered = orig_fields
            self.foxair.declared_fields = filtered
            try:
                await self.foxair.async_update()
            except Exception as e:
                self.stats["errors"] += 1
                self.stats["last_error"] = str(e)
                _LOGGER.warning("FoxAir async_update failed (tiers quick=%s medium=%s rare=%s addrs=%s): %s", do_quick, do_medium, do_rare, len(poll_addrs), e)
                raise UpdateFailed(str(e)) from e
            finally:
                self.foxair.declared_fields = orig_fields
            out = self._build_data()
            # _build_data only returns values for filtered addrs; merge with prior
            self.stats["polls"] += 1
            if do_quick:
                self.stats["quick_polls"] += 1
            if do_medium:
                self.stats["medium_polls"] += 1
            if do_rare:
                self.stats["rare_polls"] += 1
            self.stats["last_ms"] = int((time.monotonic() - t0) * 1000)
            self.stats["last_tiers"] = f"quick={do_quick} medium={do_medium} rare={do_rare} addrs={len(poll_addrs)}"
            _LOGGER.debug("Poll #%s tiers quick=%s medium=%s rare=%s addrs=%s ms=%s", self._poll_counter, do_quick, do_medium, do_rare, len(poll_addrs), self.stats["last_ms"])
            if not out and self.data:
                _LOGGER.debug("Poll returned empty, keeping prior data")
                return self.data
            if self.data and len(out) < 5:
                merged = dict(self.data)
                merged.update(out)
                self.data = merged
            else:
                if self.data:
                    merged = dict(self.data)
                    merged.update(out)
                    self.data = merged
                else:
                    self.data = out
            return self.data
