"""Bulk polling coordinator - port of FoxAir_Control standard_modbus_worker + core scaling. Includes stats for diagnostics."""
import json, pathlib, asyncio, logging, time
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryNotReady
from pymodbus.client import AsyncModbusTcpClient
from .const import POLL_BLOCKS

_LOGGER = logging.getLogger(__name__)

def s16(v): return v - 0x10000 if v & 0x8000 else v

def _decode_hhmm(raw: int) -> str:
    h=(raw>>8)&0xFF
    m=raw&0xFF
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return str(s16(raw))

def scaled(dtype, raw):
    dtype=(dtype or "RAW").upper()
    sv=s16(raw)
    if dtype in ("TEMP","TEMP1"):
        return sv/10.0
    if dtype in ("TEMP05","TEMP_0_5","STEP_0_5C"):
        return sv/2.0
    if dtype in ("DIGI5","POWER_KW_X10","KW_X10","BAR_X10","PRESSURE_BAR_X10","FLOW_M3H_X10","FLOW_X10","AMP_X10","CURRENT_A_X10"):
        return sv/10.0
    if dtype in ("FLOW_M3H_X100","FLOW_X100","COP_X100","COP100"):
        return sv/100.0
    if dtype in ("AMP_X2","CURRENT_A_X2"):
        return sv/2.0
    if dtype in ("VOLT","VOLTS","V","WATT","WATTS","POWER_W","RPM","FAN_RPM","KWH","ENERGY_KWH","KWH_PER_H","KW_PER_H"):
        return float(sv)
    if dtype == "DIGI6":
        return sv/1000.0
    if dtype == "DIGI19":
        return sv/100.0
    if dtype == "DIGI4":
        return sv/5.0
    if dtype == "DIGI1":
        return float(sv)
    if dtype in ("TIME_HHMM","HHMM"):
        return _decode_hhmm(raw)
    # BITFIELD, TIMER_BITPAIR, TIMER_MODE, SG_MODE etc. return raw int for HA numeric sensors
    if dtype in ("BITFIELD","FAULT_BITS","TIMER_BITPAIR","TIMER_MODE","MODE_0_4","SG_MODE","RUN_MODE","DAYS","HOURS","MINUTES","SECONDS","STEPS_N","EEV_STEPS","STEPS","HOURS","PERCENT","PCT","HZ","FREQUENCY_HZ"):
        return float(sv)
    return float(sv)


class FoxAirCoordinator(DataUpdateCoordinator):
    POLL_BLOCKS = POLL_BLOCKS
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name="FoxAir", update_interval=timedelta(seconds=30))
        self.entry=entry
        self.client=None
        self.data={}
        self.stats={"polls":0,"errors":0,"last_ms":0}
        self._regmap=None
        self._lock = asyncio.Lock()
        self._metadata={}

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
        """Validated write with min/max and expert guard. Returns True if sent."""
        meta = self.get_metadata(addr)
        if not meta.get("editable"):
            _LOGGER.error("Write blocked: %s not editable (group=%s risk=%s)", addr, meta.get("group"), meta.get("risk"))
            return False
        if meta.get("requires_expert") and not self.entry.options.get("enable_expert"):
            _LOGGER.error("Write blocked: %s [%s] requires expert mode (enable in Options)", addr, meta.get("code"))
            return False
        import math
        if not math.isfinite(value):
            _LOGGER.error("Write blocked: %s non-finite %.2f", addr, value)
            return False
        lo, hi = meta.get("min"), meta.get("max")
        # fail-closed if bounds missing for editable dangerous: require limits
        if meta.get("editable") and lo is None and hi is None:
            _LOGGER.error("Write blocked: %s [%s] missing limits (metadata null)", addr, meta.get("code"))
            return False
        if lo is not None and hi is not None:
            if not (lo - 1e-9 <= value <= hi + 1e-9):
                _LOGGER.error("Write blocked: %s=%.2f out of range [%.2f, %.2f]", addr, value, lo, hi)
                return False
        dtype = meta.get("type","RAW")
        raw = value
        try:
            if dtype in ("TEMP","TEMP1"):
                raw = int(round(value*10))
            elif dtype in ("TEMP05",):
                raw = int(round(value*2))
            elif dtype in ("DIGI5","POWER_KW_X10","BAR_X10","FLOW_M3H_X10","AMP_X10"):
                raw = int(round(value*10))
            elif dtype == "FLOW_M3H_X100":
                raw = int(round(value*100))
            elif dtype == "COP_X100":
                raw = int(round(value*100))
            elif dtype == "AMP_X2":
                raw = int(round(value*2))
            elif dtype == "DIGI6":
                raw = int(round(value*1000))
            elif dtype == "DIGI19":
                raw = int(round(value*100))
            elif dtype == "DIGI4":
                raw = int(round(value*5))
            else:
                raw = int(round(value))
            # signed to unsigned for modbus u16
            if raw < 0:
                raw = (raw & 0xFFFF)
            else:
                raw = int(raw) & 0xFFFF
        except Exception as e:
            _LOGGER.error("Write conversion failed %s: %s", addr, e)
            return False
        cfg=self.entry.data
        sid=cfg.get("slave",1)
        async with self._lock:
            try:
                try:
                    rr=await self.client.write_register(address=addr, value=raw, slave=sid)
                except TypeError:
                    rr=await self.client.write_register(address=addr, value=raw, device_id=sid)
                if rr.isError():
                    _LOGGER.error("Write %s error %s", addr, rr)
                    return False
                _LOGGER.warning("Write OK %s [%s] -> raw %s (scaled %.2f)", addr, meta.get("code"), raw, value)
                await self.async_request_refresh()
                return True
            except Exception as e:
                _LOGGER.error("Write %s exception %s", addr, e)
                return False

    async def _async_update_data(self):
        if self._regmap is None:
            await self._load_map()
        cfg=self.entry.data
        # reconnect if client missing or not connected
        if not self.client or not getattr(self.client, "connected", False):
            if self.client:
                try: self.client.close()
                except: pass
                self.client = None
            self.client=AsyncModbusTcpClient(host=cfg["host"], port=cfg["port"], timeout=8)
            ok=await self.client.connect()
            if not ok:
                raise ConfigEntryNotReady(f"Modbus connect failed {cfg['host']}:{cfg['port']}")
        async with self._lock:
            out={}; t0=time.monotonic()
            for addr,qty,_ in POLL_BLOCKS:
                try:
                    slave_id=cfg.get("slave",1)
                    # small pause to let bridge breathe - 300ms like Control 900ms init
                    await asyncio.sleep(0.05)
                    try:
                        rr=await self.client.read_holding_registers(address=addr, count=qty, slave=slave_id)
                    except TypeError:
                        rr=await self.client.read_holding_registers(address=addr, count=qty, device_id=slave_id)
                    if rr.isError():
                        self.stats["errors"]+=1
                        _LOGGER.warning("read %s/%s error %s", addr, qty, rr)
                        continue
                    regs=rr.registers
                    for i, raw in enumerate(regs):
                        a=addr+i
                        info=self._regmap.get(str(a))
                        if not info: continue
                        if info.get("type")=="BLOCK": continue
                        out[a]={"raw":raw, "value":scaled(info.get("type","RAW"),raw), "info":info}
                except Exception as e:
                    self.stats["errors"]+=1
                    self.stats["last_error"]=str(e)
                    _LOGGER.warning("poll %s exception %s", addr, e)
                    continue
            self.stats["polls"]+=1
            self.stats["last_ms"]=int((time.monotonic()-t0)*1000)
            # merge partial: keep prior values for blocks that failed this cycle
            if not out and self.data:
                _LOGGER.debug("Poll returned empty, keeping prior data")
                return self.data
            if self.data and len(out) < len(self._regmap or {}):
                merged = dict(self.data)
                merged.update(out)
                self.data = merged
            else:
                self.data=out
            return self.data
