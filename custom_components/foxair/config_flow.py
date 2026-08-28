import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN
import logging
import re

_LOGGER = logging.getLogger(__name__)


def _validate_host(host: str) -> bool:
    host = host.strip()
    if not host or len(host) > 253:
        return False
    if re.search(r"\s", host):
        return False
    return True


class FoxAirConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = str(user_input.get("host", "EW11-host")).strip()
            port = int(user_input.get("port", 8899))
            slave = int(user_input.get("slave", 1))
            if not _validate_host(host):
                errors["base"] = "cannot_connect"
            elif not (1 <= port <= 65535) or not (1 <= slave <= 247):
                errors["base"] = "cannot_connect"
            else:
                try:
                    from modbus_connection import ModbusTcpParams
                    from modbus_connection.pymodbus import ModbusConnection

                    conn = ModbusConnection(ModbusTcpParams(host=host, port=port), timeout=3)
                    unit = conn.for_unit(slave)
                    try:
                        await unit.read_holding_registers(1011, 1)
                        ok = True
                    finally:
                        try:
                            await conn.close()
                        except Exception:
                            pass
                except Exception as e:
                    _LOGGER.debug("probe failed %s:%s slave %s: %s", host, port, slave, e)
                    ok = False
                if ok:
                    user_input["host"] = host
                    return self.async_create_entry(
                        title=f"FoxAir {host}",
                        data=user_input,
                        options={"enable_expert": bool(user_input.get("enable_expert", False))},
                    )
                errors["base"] = "cannot_connect"
        cur_opts = {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("host", default="EW11-host"): str,
                    vol.Optional("port", default=8899): vol.All(int, vol.Range(min=1, max=65535)),
                    vol.Optional("slave", default=1): vol.All(int, vol.Range(min=1, max=247)),
                    vol.Required("enable_expert", default=cur_opts.get("enable_expert", False)): bool,
                }
            ),
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
        errors = {}
        if user_input is not None:
            if user_input.get("enable_expert") and not user_input.get("expert_ack"):
                errors["base"] = "need_ack"
            else:
                for k, default in (
                    ("elec_source", "foxair_register"),
                    ("external_meter_entity", ""),
                    ("v_gain", 1.0),
                    ("v_offset", 0.0),
                    ("i_gain", 0.1),
                    ("i_offset", 0.0),
                ):
                    if k in user_input and user_input[k] == "":
                        if k in self._entry.options:
                            user_input[k] = self._entry.options[k]
                        else:
                            user_input[k] = default
                opts = {**self._entry.options, **user_input}
                opts.pop("expert_ack", None)
                return self.async_create_entry(title="", data=opts)
        cur = self._entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("enable_expert", default=cur.get("enable_expert", False)): bool,
                    vol.Optional("expert_ack", default=cur.get("expert_ack", False)): bool,
                    vol.Optional(
                        "elec_source",
                        default=cur.get("elec_source", "foxair_register"),
                    ): vol.In(
                        {
                            "foxair_register": "FoxAir Unit Power register (2054) — accurate, no calibration",
                            "foxair_v_a": "Voltage x Current (2062 x 2057) — calibratable",
                            "external_meter": "External HA power-meter entity",
                        }
                    ),
                    vol.Optional(
                        "external_meter_entity",
                        default=cur.get("external_meter_entity", ""),
                    ): str,
                    vol.Optional("v_gain", default=cur.get("v_gain", 1.0)): vol.Coerce(float),
                    vol.Optional("v_offset", default=cur.get("v_offset", 0.0)): vol.Coerce(float),
                    vol.Optional("i_gain", default=cur.get("i_gain", 0.1)): vol.Coerce(float),
                    vol.Optional("i_offset", default=cur.get("i_offset", 0.0)): vol.Coerce(float),
                }
            ),
            errors=errors,
            description_placeholders={
                "warn": "Dangerous: A/C/E/F/D/H can damage heat pump. Only enable if you know limits.\n\nElectrical-power source is used by the COP sensor. Choose the FoxAir register for best accuracy, or V x A / an external meter and calibrate against a real power meter."
            },
        )
