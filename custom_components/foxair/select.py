"""Select platform for v0.3 — DIGI1/TIMER/SG as selects."""
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from .const import DOMAIN
import json, pathlib

_LOGGER = logging.getLogger(__name__)
DEVICE = DeviceInfo(identifiers={(DOMAIN, "foxair")}, name="FoxAir Modbus Heat Pump", manufacturer="FoxAir/PHNIX", model="Modbus TCP Heat Pump")

_VM_CACHE=None
def load_value_map(addr):
    global _VM_CACHE
    try:
        if _VM_CACHE is None:
            p = pathlib.Path(__file__).parent / "data/foxair_phnix_registers.json"
            _VM_CACHE = json.loads(p.read_text(encoding="utf-8-sig"))
        rec = _VM_CACHE.get(str(addr), {})
        return rec.get("value_map")
    except: return None

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    if not getattr(coord, "_metadata", None):
        await coord._load_map()
    ents=[]
    for addr_str, meta in (coord._metadata or {}).items():
        try: addr=int(addr_str)
        except: continue
        if meta.get("platform")!="select" or not meta.get("editable"):
            continue
        if meta.get("requires_expert") and not entry.options.get("enable_expert"):
            continue
        # need value_map or at least DIGI1 generic
        ents.append(FoxSelect(coord, addr, meta))
    add_entities(ents)

class FoxSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    def __init__(self, coord, addr, meta):
        super().__init__(coord)
        self._addr=addr
        self._meta=meta
        self._attr_unique_id=f"foxair_sel_{addr}"
        self._attr_translation_key=f"foxair_{addr}"
        self._attr_device_info=DEVICE
        risk=meta.get("risk")
        if risk=="dangerous":
            self._attr_entity_category=EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default=False
        elif risk=="advanced":
            self._attr_entity_category=EntityCategory.CONFIG
        # options from value_map or fallback 0..max
        vm = load_value_map(addr)
        if vm:
            # value_map keys are raw strings like "0","1"
            self._attr_options=[f"{k}: {v}" for k,v in sorted(vm.items(), key=lambda x: int(x[0]) if x[0].lstrip('-').isdigit() else x[0])]
            self._map=vm
        else:
            # generic DIGI1 range
            lo,hi = meta.get("min"), meta.get("max")
            if lo is not None and hi is not None:
                self._attr_options=[str(int(i)) for i in range(int(lo), int(hi)+1)]
                self._map={str(i):str(i) for i in range(int(lo),int(hi)+1)}
            else:
                self._attr_options=["0","1"]
                self._map={"0":"0","1":"1"}

    @property
    def current_option(self):
        rec=self.coordinator.data.get(self._addr)
        if not rec: return None
        raw=rec.get("raw")
        vm=self._map or {}
        # find key matching raw
        for k,v in vm.items():
            try:
                if int(k)==int(raw):
                    return f"{k}: {v}" if f"{k}: {v}" in (self._attr_options or []) else str(k)
            except: pass
        return str(raw)

    async def async_select_option(self, option: str) -> None:
        # option is like "1: Ja" or "1"
        raw_str=option.split(":",1)[0].strip()
        try: val=int(raw_str)
        except: val=int(option)
        ok=await self.coordinator.async_write_register(self._addr, float(val))
        if not ok:
            raise ValueError(f"Write rejected {self._addr}")

