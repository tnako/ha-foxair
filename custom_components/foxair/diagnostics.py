"""Diagnostics download - no passwords."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    return {
        "entry": {"host": entry.data.get("host"), "port": entry.data.get("port"), "slave": entry.data.get("slave")},
        "blocks": coord.POLL_BLOCKS if coord else [],
        "data_keys": list((coord.data or {}).keys())[:20] if coord else [],
        "sample": {k: v.get("raw") for k,v in list((coord.data or {}).items())[:5]} if coord else {},
        "note": "no secrets, no PDFs, see attribution"
    }
