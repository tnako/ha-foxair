import voluptuous as vol
from homeassistant import config_entries
from pymodbus.client import AsyncModbusTcpClient
from .const import DOMAIN

class FoxAirConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    async def async_step_user(self, user_input=None):
        errors={}
        if user_input is not None:
            # quick connect test - no secrets logged
            client=AsyncModbusTcpClient(host=user_input["host"], port=user_input["port"], timeout=3)
            ok=await client.connect()
            if ok:
                try: client.close()
                except: pass
                return self.async_create_entry(title=f"FoxAir {user_input['host']}", data=user_input)
            errors["base"]="cannot_connect"
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required("host", default="EW11-host"): str,
            vol.Required("port", default=8899): int,
            vol.Optional("slave", default=1): int,
        }), errors=errors)
