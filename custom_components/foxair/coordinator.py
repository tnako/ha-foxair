"""Bulk polling coordinator - port of FoxAir_Control standard_modbus_worker + core scaling."""
import json, pathlib, struct, asyncio, logging
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pymodbus.client import AsyncModbusTcpClient
from .const import POLL_BLOCKS

_LOGGER = logging.getLogger(__name__)

def s16(v): return v - 0x10000 if v & 0x8000 else v

def scaled(dtype, raw):
    dtype=(dtype or "RAW").upper()
    sv=s16(raw)
    if dtype in ("TEMP","TEMP1"): return sv/10.0
    if dtype in ("HZ",): return sv
    if dtype=="PERCENT": return sv
    if dtype=="FLOW_M3H_X100": return sv/100.0
    if dtype in ("POWER_KW_X10","BAR_X10","AMP_X10"): return sv/10.0
    if dtype in ("DIGI5",): return sv/10.0
    if dtype=="DIGI1": return sv
    return sv

class FoxAirCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name="FoxAir", update_interval=timedelta(seconds=10))
        self.entry=entry
        self.client=None
        self.data={}
        self._load_map()
    def _load_map(self):
        p=pathlib.Path(__file__).parent/"data/foxair_phnix_registers.json"
        self.regmap=json.loads(p.read_text(encoding="utf-8-sig"))
    async def _async_update_data(self):
        cfg=self.entry.data
        if not self.client:
            self.client=AsyncModbusTcpClient(host=cfg["host"], port=cfg["port"], timeout=4)
            await self.client.connect()
        out={}
        for addr,qty,_ in POLL_BLOCKS:
            try:
                rr=await self.client.read_holding_registers(address=addr, count=qty, slave=cfg.get("slave",1))
                if rr.isError():
                    _LOGGER.warning("read %s/%s error %s", addr, qty, rr)
                    continue
                regs=rr.registers
                for i, raw in enumerate(regs):
                    a=addr+i
                    info=self.regmap.get(str(a))
                    if not info: continue
                    dtype=info.get("type","RAW")
                    out[a]={"raw":raw, "value":scaled(dtype,raw), "info":info}
                await asyncio.sleep(0.05)
            except Exception as e:
                _LOGGER.warning("poll %s exception %s", addr, e)
        self.data=out
        return out
