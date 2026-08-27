from homeassistant.components.climate import ClimateEntity, HVACMode, ClimateEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN

HVAC_MAP = {0: HVACMode.OFF, 1: HVACMode.HEAT, 2: HVACMode.COOL, 3: HVACMode.HEAT_COOL, 4: HVACMode.HEAT_COOL}
HVAC_REV = {v:k for k,v in HVAC_MAP.items()}

class FoxAirClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "foxair_climate"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]
    _attr_min_temp = 15
    _attr_max_temp = 55

    def __init__(self, coord):
        super().__init__(coord)
        self._attr_unique_id = "foxair_climate"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, "foxair")}, name="FoxAir Modbus Heat Pump", manufacturer="FoxAir/PHNIX", model="Modbus TCP")

    @property
    def current_temperature(self):
        rec = self.coordinator.data.get(2046)
        return rec["value"] if rec else None

    @property
    def target_temperature(self):
        # heating target R02 1158
        rec = self.coordinator.data.get(1158)
        return rec["value"] if rec else None

    @property
    def hvac_mode(self):
        # 1011 off? 1012 mode
        off = self.coordinator.data.get(1011)
        mode = self.coordinator.data.get(1012)
        if off and off["raw"] == 0:
            return HVACMode.OFF
        if mode:
            return HVAC_MAP.get(mode["raw"], HVACMode.HEAT)
        return HVACMode.HEAT

    @property
    def hvac_action(self):
        return self.hvac_mode

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        if temp is None: return
        raw = int(round(temp*10))
        # write via coordinator - try slave/device_id fallback
        cfg = self.coordinator.entry.data
        sid = cfg.get("slave",1)
        client = self.coordinator.client
        try:
            await client.write_register(address=1158, value=raw, slave=sid)
        except TypeError:
            await client.write_register(address=1158, value=raw, device_id=sid)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode):
        # 1011 on/off + 1012 mode
        cfg = self.coordinator.entry.data
        sid = cfg.get("slave",1)
        client = self.coordinator.client
        if hvac_mode == HVACMode.OFF:
            try:
                await client.write_register(address=1011, value=0, slave=sid)
            except TypeError:
                await client.write_register(address=1011, value=0, device_id=sid)
        else:
            # ensure on
            try:
                await client.write_register(address=1011, value=1, slave=sid)
            except TypeError:
                await client.write_register(address=1011, value=1, device_id=sid)
            mode_val = HVAC_REV.get(hvac_mode, 1)
            try:
                await client.write_register(address=1012, value=mode_val, slave=sid)
            except TypeError:
                await client.write_register(address=1012, value=mode_val, device_id=sid)
        await self.coordinator.async_request_refresh()

async def async_setup_entry(hass, entry, add_entities):
    coord = hass.data["foxair"][entry.entry_id]
    add_entities([FoxAirClimate(coord)])
