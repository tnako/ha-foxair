"""FoxAir coordinator — ModbusConnection + foxair-modbus pooled reads."""
import json, pathlib, asyncio, logging, time, math
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryNotReady

_LOGGER = logging.getLogger(__name__)

try:
    from .vendor.foxair_modbus import FoxAir
except Exception as e:
    try:
        from custom_components.foxair.vendor.foxair_modbus import FoxAir
    except Exception as e2:
        FoxAir = None  # will fail at runtime if vendor missing
        _LOGGER.error("foxair_modbus vendor missing: %s / %s", e, e2)

def _decode_hhmm(raw: int) -> str:
    h=(raw>>8)&0xFF
    m=raw&0xFF
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    # fallback signed
    sv = raw - 0x10000 if raw & 0x8000 else raw
    return str(sv)

# legacy scaled helper kept for time hhmm fallback and compat; primary scaling via FoxAir model
def s16(v): return v - 0x10000 if v & 0x8000 else v

class FoxAirCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry, unit, conn=None):
        super().__init__(hass, _LOGGER, name="FoxAir", update_interval=timedelta(seconds=30))
        self.entry=entry
        self._entry_id = entry.entry_id
        self.unit = unit
        self._conn = conn
        self.data={}
        self.stats={"polls":0,"errors":0,"last_ms":0}
        self._regmap=None
        self._metadata={}
        self._lock = asyncio.Lock()
        self._flow_ema = 0.0
        if FoxAir is not None and unit is not None:
            self.foxair = FoxAir(unit)
        else:
            self.foxair = None

    async def _load_map(self):
        p=pathlib.Path(__file__).parent/"data/foxair_phnix_registers.json"
        def _load_reg():
            return json.loads(p.read_text(encoding="utf-8-sig"))
        self._regmap = await self.hass.async_add_executor_job(_load_reg)
        try:
            mp=pathlib.Path(__file__).parent/"data/foxair_metadata.json"
            def _load_meta():
                return json.loads(mp.read_text(encoding="utf-8-sig"))
            self._metadata = await self.hass.async_add_executor_job(_load_meta)
        except Exception:
            self._metadata = {}

    def get_metadata(self, addr: int) -> dict:
        return (getattr(self, "_metadata", {}) or {}).get(str(addr), {})

    async def async_write_register(self, addr: int, value: float) -> bool:
        """Validated write via foxair-modbus model. Returns True if sent."""
        meta = self.get_metadata(addr)
        if not meta.get("editable"):
            _LOGGER.error("Write blocked: %s not editable (group=%s risk=%s)", addr, meta.get("group"), meta.get("risk"))
            return False
        if meta.get("requires_expert") and not self.entry.options.get("enable_expert"):
            _LOGGER.error("Write blocked: %s [%s] requires expert mode", addr, meta.get("code"))
            return False
        if not math.isfinite(value):
            _LOGGER.error("Write blocked: %s non-finite %.2f", addr, value)
            return False
        lo, hi = meta.get("min"), meta.get("max")
        if meta.get("editable") and lo is None and hi is None:
            _LOGGER.error("Write blocked: %s [%s] missing limits", addr, meta.get("code"))
            return False
        if lo is not None and hi is not None:
            if not (lo - 1e-9 <= value <= hi + 1e-9):
                _LOGGER.error("Write blocked: %s=%.2f out of range [%.2f, %.2f]", addr, value, lo, hi)
                return False
        if self.foxair is None:
            _LOGGER.error("Write failed: foxair model not initialized")
            return False
        field = f"reg_{addr}"
        if field not in self.foxair.declared_fields:
            _LOGGER.error("Write blocked: %s no field %s in model", addr, field)
            return False
        # Pre-handle TIME_HHMM string values? coordinator expects float writes only.
        try:
            # integer fields need int
            f = self.foxair.declared_fields[field]
            # decide int vs float based on field type name: gauge expects float, integer expects int
            # We pass rounded int for integer types to avoid 0.0 float issues
            to_write = int(round(value)) if f.__class__.__name__ == "NumberField" and getattr(f, "scale", 1.0) == 1.0 and field in [f"reg_{a}" for a in [1011,1012]] else value
            # generic: if field is integer-like (scale 1.0 and signed int), send int
            # Use metadata type hint: DIGI1 etc => int
            dtype = meta.get("type","RAW")
            if dtype in ("DIGI1","MODE_0_4","SG_MODE","TIMER_BITPAIR","TIMER_MODE","BITFIELD","STEPS_N","RAW"):
                to_write = int(round(float(value)))
            await self.foxair.write(field, to_write)
        except Exception as e:
            _LOGGER.error("Write %s exception %s", addr, e)
            return False
        _LOGGER.warning("Write OK %s [%s] -> %.2f", addr, meta.get("code"), value)
        await asyncio.sleep(0.35)
        try:
            await self.foxair.async_update()
            # rebuild data quickly for fast-path
            out = {}
            for name, fld in self.foxair.declared_fields.items():
                if not name.startswith("reg_"):
                    continue
                try:
                    a=int(name.split("_")[1])
                except: continue
                val=getattr(self.foxair, name, None)
                # TIME_HHMM: decode to string like old scaled? Keep int but platforms expect int; keep as int.
                info=(self._regmap or {}).get(str(a)) or {"type": meta.get("type","RAW")}
                # handle TIME_HHMM string decode for value alias
                if info.get("type")=="TIME_HHMM" and isinstance(val, int):
                    try:
                        val_str=_decode_hhmm(val)
                        # store string as value for that sensor type
                        out[a]={"raw": val, "value": val_str, "info": info}
                        continue
                    except: pass
                out[a]={"raw": val, "value": val, "info": info}
            # merge into self.data
            if out:
                merged=dict(self.data) if self.data else {}
                merged.update(out)
                self.data=merged
                self.async_update_listeners()
                _LOGGER.warning("Write verify %s fast-path updated", addr)
        except Exception as e:
            _LOGGER.debug("fast readback %s failed %s", addr, e)
        self.hass.async_create_task(self.async_request_refresh())
        return True

    async def _async_update_data(self):
        if self._regmap is None:
            await self._load_map()
        if self.foxair is None:
            raise UpdateFailed("FoxAir model not initialized (vendor missing)")
        async with self._lock:
            t0=time.monotonic()
            try:
                await self.foxair.async_update()
            except Exception as e:
                self.stats["errors"]+=1
                self.stats["last_error"]=str(e)
                _LOGGER.warning("FoxAir async_update failed: %s", e)
                raise UpdateFailed(str(e)) from e
            out={}
            for name, fld in self.foxair.declared_fields.items():
                if not name.startswith("reg_"):
                    continue
                try:
                    a=int(name.split("_")[1])
                except: continue
                val=getattr(self.foxair, name, None)
                if val is None:
                    continue
                info=self._regmap.get(str(a)) if self._regmap else None
                if not info:
                    continue
                if info.get("type")=="BLOCK":
                    continue
                # TIME_HHMM handling
                if info.get("type")=="TIME_HHMM" and isinstance(val, int):
                    try:
                        v=_decode_hhmm(val)
                        out[a]={"raw": val, "value": v, "info": info}
                        continue
                    except: pass
                out[a]={"raw": val, "value": val, "info": info}
            self.stats["polls"]+=1
            self.stats["last_ms"]=int((time.monotonic()-t0)*1000)
            if not out and self.data:
                _LOGGER.debug("Poll returned empty, keeping prior data")
                return self.data
            if self.data and len(out) < 5:  # sanity: keep prior if tiny
                merged=dict(self.data)
                merged.update(out)
                self.data=merged
            else:
                # merge partial: keep prior for blocks that failed
                if self.data:
                    merged=dict(self.data)
                    merged.update(out)
                    self.data=merged
                else:
                    self.data=out
            return self.data
