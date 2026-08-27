from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN, POPULAR_ADDRS

async def async_setup_entry(hass, entry, add_entities):
    coord=hass.data["foxair"][entry.entry_id]
    # Phase0: 10 T live, Phase1 will expand to all but hidden diagnostic disabled
    addrs=(2045,2046,2048,2049,2051,2053,2044,2057,2062,2072)
    ents=[FoxSensor(coord, addr) for addr in addrs if addr in coord.data]
    add_entities(ents)

class FoxSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coord, addr):
        super().__init__(coord)
        self._addr=addr
        rec=coord.data.get(addr, {})
        info=rec.get("info", {}) if rec else {}
        self._attr_unique_id=f"foxair_{addr}"
        self._attr_name=f"FoxAir {info.get('code','')} {info.get('name','')}".strip()
        self._attr_native_unit_of_measurement=info.get("unit")
        self._attr_device_info=DeviceInfo(identifiers={(DOMAIN, "foxair")}, name="FoxAir Heat Pump", manufacturer="FoxAir/PHNIX", model="Modbus TCP")
        # popular enabled, hidden diagnostic would be disabled_by_default in Phase1
        self._attr_entity_registry_enabled_default=addr in POPULAR_ADDRS
        if addr not in POPULAR_ADDRS:
            self._attr_entity_category="diagnostic"
    @property
    def native_value(self):
        rec=self.coordinator.data.get(self._addr)
        return rec["value"] if rec else None
    @property
    def extra_state_attributes(self):
        rec=self.coordinator.data.get(self._addr)
        if not rec: return {}
        info=rec.get("info",{})
        return {"raw": rec.get("raw"), "address": self._addr, "block": info.get("block"), "type": info.get("type")}
