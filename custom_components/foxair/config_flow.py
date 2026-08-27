import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from pymodbus.client import AsyncModbusTcpClient
from .const import DOMAIN

class FoxAirConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    async def async_step_user(self, user_input=None):
        errors={}
        if user_input is not None:
            client=AsyncModbusTcpClient(host=user_input["host"], port=user_input["port"], timeout=3)
            ok=await client.connect()
            if ok:
                try: client.close()
                except: pass
                # carry enable_expert into options so it applies immediately after setup
                return self.async_create_entry(
                    title=f"FoxAir {user_input['host']}",
                    data=user_input,
                    options={"enable_expert": bool(user_input.get("enable_expert", False))},
                )
            errors["base"]="cannot_connect"
        cur_opts = {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("host", default="EW11-host"): str,
                vol.Required("port", default=8899): int,
                vol.Optional("slave", default=1): int,
                vol.Optional("enable_expert", default=cur_opts.get("enable_expert", False)): bool,
            }),
            errors=errors,
            description_placeholders={
                "warn": "Enable expert mode to expose advanced/dangerous parameters (A/C/E/F/D/H blocks). Leave off for normal use."
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return FoxAirOptionsFlow(config_entry)

class FoxAirOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry):
        self._entry = entry

    async def async_step_init(self, user_input=None):
        errors={}
        if user_input is not None:
            # require ack if enabling expert
            if user_input.get("enable_expert") and not user_input.get("expert_ack"):
                errors["base"]="need_ack"
            else:
                # store only enable_expert (ack is one-time)
                opts = {"enable_expert": bool(user_input.get("enable_expert"))}
                return self.async_create_entry(title="", data=opts)
        cur = self._entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("enable_expert", default=cur.get("enable_expert", False)): bool,
                vol.Required("expert_ack", default=False): bool,
            }),
            errors=errors,
            description_placeholders={"warn": "Dangerous: A/C/E/F/D/H can damage heat pump. Only enable if you know limits."},
        )
