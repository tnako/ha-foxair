import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from pymodbus.client import AsyncModbusTcpClient
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


def _validate_prefix(prefix: str) -> bool:
    prefix = prefix.strip().lower()
    if not prefix:
        return True  # empty defaults to "foxair"
    # Allow alphanumeric and underscore, max 32 chars
    return bool(re.match(r"^[a-z0-9_]{1,32}$", prefix))


async def _probe_modbus(host: str, port: int, slave: int) -> bool:
    client = AsyncModbusTcpClient(host=host, port=port, timeout=5)
    try:
        ok = await client.connect()
        # verify real Modbus answer, not just open TCP: read 3 popular addrs in one batch
        if ok:
            try:
                rr = await client.read_holding_registers(address=1011, count=3, device_id=slave)
            except TypeError:
                rr = await client.read_holding_registers(address=1011, count=3, slave=slave)
            ok = bool(rr and not rr.isError() and getattr(rr, "registers", None))
    except Exception as e:
        _LOGGER.debug("probe connect failed %s:%s %s", host, port, e)
        ok = False
    finally:
        try:
            client.close()
        except Exception:
            pass
    return ok


def _check_conflicts(entries, host, port, slave, name_prefix, exclude_entry_id=None):
    """Return error key ('name_prefix' or 'base') if host:port:slave or prefix collides."""
    for e in entries:
        if exclude_entry_id is not None and e.entry_id == exclude_entry_id:
            continue
        if e.data.get("name_prefix", "foxair") == (name_prefix or "foxair"):
            return "name_prefix"
        if (
            e.data.get("host") == host
            and int(e.data.get("port", 8899)) == port
            and int(e.data.get("slave", 1)) == slave
        ):
            return "base"
    return None


def _host_label(host: str, port: int) -> str:
    """Short host identifier for display (IP or hostname, no port if default)."""
    return f"{host}:{port}" if port != 8899 else host


class FoxAirConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        # Preserve user input across validation errors
        host = ""
        port = 8899
        slave = 1
        name_prefix = "foxair"
        enable_expert = False

        if user_input is not None:
            host = str(user_input.get("host", "modbus-bridge")).strip()
            port = int(user_input.get("port", 8899))
            slave = int(user_input.get("slave", 1))
            name_prefix = str(user_input.get("name_prefix", "foxair")).strip().lower()
            enable_expert = bool(user_input.get("enable_expert", False))
            if not _validate_host(host):
                errors["base"] = "cannot_connect"
            elif not (1 <= port <= 65535) or not (1 <= slave <= 247):
                errors["base"] = "cannot_connect"
            elif not _validate_prefix(name_prefix):
                errors["name_prefix"] = "invalid_prefix"
            else:
                conflict = _check_conflicts(self._async_current_entries(), host, port, slave, name_prefix)
                if conflict == "name_prefix":
                    errors["name_prefix"] = "prefix_in_use"
                elif conflict == "base":
                    errors["base"] = "already_configured"
                if not errors:
                    await self.async_set_unique_id(f"{host}:{port}:{slave}")
                    self._abort_if_unique_id_configured()
                    if await _probe_modbus(host, port, slave):
                        data = {"host": host, "port": port, "slave": slave}
                        if name_prefix and name_prefix != "foxair":
                            data["name_prefix"] = name_prefix
                        prefix_display = name_prefix or "foxair"
                        title = f"{prefix_display.title()} Heat Pump — {_host_label(host, port)}"
                        return self.async_create_entry(
                            title=title,
                            data=data,
                            options={"enable_expert": enable_expert},
                        )
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("host", default=host or "modbus-bridge"): str,
                    vol.Optional("port", default=port): int,
                    vol.Optional("slave", default=slave): int,
                    vol.Optional("name_prefix", default=name_prefix): str,
                    vol.Required("enable_expert", default=enable_expert): bool,
                }
            ),
            errors=errors,
            description_placeholders={
                "warn": "Enable expert mode to expose advanced/dangerous parameters (A/C/E/F/D/H blocks). Leave off for normal use.",
                "multi_pump": "Multiple pumps? Set a unique `name_prefix` (e.g. `house1`, `cottage`) and ensure the combination of host:port:slave is unique. Each pump needs its own integration entry.",
            },
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        data = entry.data
        # Pre-fill with current values
        host = data.get("host", "modbus-bridge")
        port = int(data.get("port", 8899))
        slave = int(data.get("slave", 1))
        name_prefix = data.get("name_prefix", "foxair")

        if user_input is not None:
            host = str(user_input.get("host", "")).strip()
            port = int(user_input.get("port", 8899))
            slave = int(user_input.get("slave", 1))
            name_prefix = str(user_input.get("name_prefix", "foxair")).strip().lower()
            if not _validate_host(host):
                errors["base"] = "cannot_connect"
            elif not (1 <= port <= 65535) or not (1 <= slave <= 247):
                errors["base"] = "cannot_connect"
            elif not _validate_prefix(name_prefix):
                errors["name_prefix"] = "invalid_prefix"
            else:
                conflict = _check_conflicts(
                    self._async_current_entries(), host, port, slave, name_prefix,
                    exclude_entry_id=entry.entry_id,
                )
                if conflict == "name_prefix":
                    errors["name_prefix"] = "prefix_in_use"
                elif conflict == "base":
                    errors["base"] = "already_configured"
                if not errors:
                    if await _probe_modbus(host, port, slave):
                        new_data = {"host": host, "port": port, "slave": slave,
                                    "name_prefix": name_prefix or "foxair"}
                        prefix_display = name_prefix or "foxair"
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates=new_data,
                            title=f"{prefix_display.title()} Heat Pump — {_host_label(host, port)}",
                            unique_id=f"{host}:{port}:{slave}",
                        )
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional("host", default=host): str,
                    vol.Optional("port", default=port): int,
                    vol.Optional("slave", default=slave): int,
                    vol.Optional("name_prefix", default=name_prefix): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "warn": "Changing the prefix renames all entity IDs for this pump (old names disappear). Host/port/slave can be changed freely.",
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
        data = self._entry.data
        prefix_display = data.get("name_prefix", "foxair")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("enable_expert", default=cur.get("enable_expert", False)): bool,
                    vol.Optional("expert_ack", default=cur.get("expert_ack", False)): bool,
                    vol.Optional(
                        "elec_source",
                        default=cur.get("elec_source", "foxair_register"),
                    ): vol.In(["foxair_register", "external_meter"]),
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
                "warn": f"Expert mode exposes advanced/dangerous parameters for {prefix_display.title()}. Acknowledge to enable.",
                "prefix": f"Device prefix: {prefix_display}",
            },
        )