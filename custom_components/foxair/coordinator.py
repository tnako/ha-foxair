"""Bulk polling coordinator - port of FoxAir_Control standard_modbus_worker + core scaling. Includes stats for diagnostics."""
import json, pathlib, asyncio, logging, time
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryNotReady
from pymodbus.client import AsyncModbusTcpClient
from .const import POLL_BLOCKS

_LOGGER = logging.getLogger(__name__)

def s16(v): return v - 0x10000 if v & 0x8000 else v
def scaled(dtype, raw):
    dtype=(dtype or "RAW").upper()
    sv=s16(raw)
    if dtype in ("TEMP","TEMP1"): return sv/10.0
    if dtype=="TEMP05": return sv/2.0
    if dtype in ("HZ",): return sv
    if dtype=="PERCENT": return sv
    if dtype=="FLOW_M3H_X100": return sv/100.0
    if dtype=="FLOW_M3H_X10": return sv/10.0
    if dtype in ("POWER_KW_X10","BAR_X10","AMP_X10"): return sv/10.0
    if dtype in ("DIGI5",): return sv/10.0
    if dtype=="AMP_X2": return sv/2.0
    if dtype=="DIGI1": return sv
    return sv

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

    async def _load_map(self):
        p=pathlib.Path(__file__).parent/"data/foxair_phnix_registers.json"
        text = await self.hass.async_add_executor_job(lambda: p.read_text(encoding="utf-8-sig"))
        self._regmap = json.loads(text)

    async def _async_update_data(self):
        if self._regmap is None:
            await self._load_map()
        cfg=self.entry.data
        if not self.client:
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
                    await asyncio.sleep(0.3)
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
                    _LOGGER.warning("poll %s exception %s", addr, e)
                    raise UpdateFailed(str(e)) from e
            self.stats["polls"]+=1
            self.stats["last_ms"]=int((time.monotonic()-t0)*1000)
            self.data=out
            return out
