"""Diagnostics download - no passwords."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

def _reg_sample(v: dict) -> dict:
    info = v.get("info", {})
    return {"raw": v.get("raw"), "value": v.get("value"),
            "code": info.get("code"), "type": info.get("type")}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    coord = getattr(entry, "runtime_data", None) or hass.data.get("foxair", {}).get(entry.entry_id)
    if not coord:
        return {"error": "no coordinator"}
    data = dict(coord.data or {})
    # Key addrs the reply always needs (pump type, power/COP/flow sources,
    # firmware, curve). If a normal poll cycle missed them (EW11 timeout —
    # the coordinator aborts the rest of the cycle on connection errors),
    # fetch them live here so the file answers the question instead of
    # forcing another round-trip with the user.
    KEY_ADDRS = (1041,                              # H31 pump type
                 2059, 2054, 2060, 2077, 2072,      # T59 T54 T60 T39 T31
                 2042, 2043, 2062,                  # T36 T37 T34
                 2045, 2046,                        # T01 T02 inlet/outlet
                 2012,                              # run status (mode)
                 2104, 1234, 1235, 1236)            # fw version, curve
    missing = [a for a in KEY_ADDRS if a not in data]
    fetch_error = None
    if missing:
        try:
            out = await coord._fetch_addrs(set(missing))
            data.update(out)
            # Write back so computed sensors below (and entities) see them.
            try:
                coord.data = {**(coord.data or {}), **out}
            except Exception:  # noqa: BLE001 — never break diagnostics
                pass
        except Exception as e:  # noqa: BLE001 — diagnostics must never fail
            fetch_error = str(e)
    still_missing = [a for a in KEY_ADDRS if a not in data]
    # Full register dump, no cap — coord.data peaks around ~380 entries and
    # any slice hides exactly the regs needed for debugging (v0.6.7 lesson:
    # a [:50] slice hid all 2xxx power/COP/flow regs).
    registers = {str(k): _reg_sample(v) for k, v in data.items()}
    sample = dict(list(registers.items())[:50])  # compat with older tooling
    key_fetch: dict = {"requested": list(missing), "still_missing": still_missing}
    if fetch_error:
        key_fetch["fetch_error"] = fetch_error
    computed = {}
    try:
        from .computed import (compute_heating_power, compute_electrical_power,
                               compute_cop, compute_cop_mode, compute_cooling_power,
                               active_mode, _cval)
        opts = dict(entry.options)
        computed = {"heating_power_w": compute_heating_power(coord),
                    "cooling_power_w": compute_cooling_power(coord),
                    "electrical_power_w": compute_electrical_power(coord, opts),
                    "cop": compute_cop(coord, opts),
                    "cop_heating": compute_cop(coord, opts),
                    "cop_cooling": compute_cop_mode(coord, opts, "cooling"),
                    "cop_dhw": compute_cop_mode(coord, opts, "dhw"),
                    "active_mode": active_mode(coord),
                    "energy_kwh": dict(getattr(coord, "energy_kwh", {})),
                    "elec_source": (opts or {}).get("elec_source", "foxair_register")}
        meter = ((opts or {}).get("external_meter_entity") or "").strip()
        if meter:
            st = hass.states.get(meter)
            computed["meter_entity"] = meter
            computed["meter_state"] = st.state if st else None
            computed["meter_unit"] = (st.attributes.get("unit_of_measurement")
                                      if st else None)
        # Source register values behind the computed sensors, so a missing
        # computed value is directly explainable (None = not polled/answered).
        for label, addr in (("t59_heating_kw", 2059), ("t54_elec_kw", 2054),
                            ("t60_cop", 2060), ("t39_flow_m3h", 2077),
                            ("t31_freq_hz", 2072), ("t36_amps", 2042),
                            ("t37_dc_v", 2043), ("t34_ac_v", 2062)):
            computed[label] = _cval(coord, addr)
    except Exception as e:
        computed = {"error": str(e)}
    curve = {}
    try:
        from .heating_curve import curve_target_for_at
        hc = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
        hc_a = hc.get("addr_single", {}) if isinstance(hc, dict) else {}
        at = (coord.data.get(hc_a.get("at_sensor", 2048)) or {}).get("value")
        if at is not None:
            ct = curve_target_for_at(coord, float(at))
            curve = {"at": at, "curve_target": ct, "slope": (coord.data.get(hc_a.get("slope", 1234)) or {}).get("value"), "offset": (coord.data.get(hc_a.get("offset", 1235)) or {}).get("value"), "h36": (coord.data.get(hc_a.get("at_comp_en", 1236)) or {}).get("raw")}
    except Exception as e:
        curve = {"error": str(e)}
    foxair_info = {}
    try:
        fox = getattr(coord, "foxair", None)
        if fox is not None:
            foxair_info = {
                "fields": len(getattr(fox, "declared_fields", {})),
                "has_unit": getattr(coord, "unit", None) is not None,
                "max_span": getattr(fox, "max_span", None),
                "max_gap": getattr(fox, "max_gap", None),
            }
    except Exception:
        pass
    conn = hass.data.get("foxair_conn", {}).get(entry.entry_id)
    return {
        "poll_blocks": getattr(coord, "POLL_BLOCKS", []),
        "stats": getattr(coord, "stats", {}),
        "freshness": coord.freshness_summary() if hasattr(coord, "freshness_summary") else {},
        "data_keys": list((coord.data or {}).keys()),
        "data_count": len(coord.data or {}),
        "sample": sample,
        "registers": registers,
        "key_fetch": key_fetch,
        "computed": computed,
        "curve": curve,
        "options": dict(entry.options),
        "data": {"host": entry.data.get("host"), "port": entry.data.get("port"), "slave": entry.data.get("slave"), "name_prefix": entry.data.get("name_prefix", "foxair")},
        "connected": bool(getattr(conn, "_client", None) is not None) if conn else (getattr(getattr(coord, "client", None), "connected", False) if getattr(coord, "client", None) else bool(getattr(coord, "unit", None))),
        "last_error": (coord.stats or {}).get("last_error") if hasattr(coord, "stats") else None,
        "foxair_model": foxair_info,
        "firmware_version": coord.fw_version() if hasattr(coord, "fw_version") else 0,
    }
