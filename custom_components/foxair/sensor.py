from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import POPULAR_ADDRS

async def async_setup_entry(hass, entry, add_entities):
    coord=hass.data["foxair"][entry.entry_id]
    ents=[]
    for addr, rec in coord.data.items():
        info=rec["info"]
        # Phase0: only T live 2045 etc + a few popular, enabled filtering
        if addr not in (2045,2046,2048,2049,2051,2053,2044,2057,2062,2072):
            continue
        ents.append(FoxSensor(coord, addr, rec))
    add_entities(ents)

class FoxSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coord, addr, rec):
        super().__init__(coord)
        self._addr=addr
        info=rec["info"]
        self._attr_unique_id=f"foxair_{addr}"
        self._attr_name=f"FoxAir {info.get('code','') } {info.get('name','')}".strip()
        self._attr_native_unit_of_measurement=info.get("unit")
        # popular enabled, others disabled handled via const later
    @property
    def native_value(self):
        rec=self.coordinator.data.get(self._addr)
        return rec["value"] if rec else None
