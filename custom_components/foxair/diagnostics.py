"""Diagnostics download - no passwords."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if not coord:
        return {"error": "no coordinator"}
    sample = {}
    for k,v in list((coord.data or {}).items())[:50]:
        info = v.get("info",{})
        sample[str(k)] = {"raw": v.get("raw"), "value": v.get("value"), "code": info.get("code"), "type": info.get("type")}
    curve = {}
    try:
        from .heating_curve import curve_target_for_at
        at = (coord.data.get(2048) or {}).get("value")
        if at is not None:
            ct = curve_target_for_at(coord, float(at))
            curve = {"at": at, "curve_target": ct, "slope": (coord.data.get(1234) or {}).get("value"), "offset": (coord.data.get(1235) or {}).get("value"), "h36": (coord.data.get(1236) or {}).get("raw")}
    except Exception as e:
        curve = {"error": str(e)}
    return {
        "poll_blocks": getattr(coord, "POLL_BLOCKS", []),
        "stats": getattr(coord, "stats", {}),
        "data_keys": list((coord.data or {}).keys()),
        "data_count": len(coord.data or {}),
        "sample": sample,
        "curve": curve,
        "options": dict(entry.options),
        "data": {"host": entry.data.get("host"), "port": entry.data.get("port"), "slave": entry.data.get("slave")},
        "connected": getattr(getattr(coord, "client", None), "connected", False) if getattr(coord, "client", None) else False,
        "last_error": getattr(getattr(coord, "stats", {}), "get", lambda *a,**k: None)("last_error") if hasattr(coord, "stats") else None,
    }
