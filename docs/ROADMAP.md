# Roadmap

**Current:** `0.7.x` - HA **>=2026.9**, `pymodbus>=3.6.0` (single `AsyncModbusTcpClient`, `coordinator._lock`, tiered polling quick 30 s / medium 120 s / rare 300 s, batched `max_span=100`/`max_gap=30`, config-driven). Firmware-gated entities (2104): 3.3, 3.4, 3.5.

**Next (needs data from a live unit):**
- Energy counters 2118/2120/2122/2124 and DHW 2125-2128 (32-bit pairs) as Energy dashboard sources. They exist from firmware V3.4; blocked on knowing how defrost energy is booked into them.
- Writable heating/summer cut-off 1464/1465 (V3.5) once the threshold and the 1465 unit are confirmed live.
- Input current L1-L3 (2029-2031): untested, stay blocked until one unit confirms they read back without breaking a batch.

**Not planned:** heat/cool as thermostat modes. The mode word 1012 combines heating/cooling with DHW (0 DHW only, 1 heat, 2 cool, 3 heat + DHW, 4 cool + DHW), so HVAC modes and presets would write the same register; see climate history in CHANGELOG 0.3.x.

**Future** - when a future HA release bundles `modbus-connection` with a shared `modbus` bus, migrate to it: add `dependencies: ["modbus"]`, bump `homeassistant` in `hacs.json`/`manifest.json`, drop `pymodbus` from pip `requirements`, and switch the coordinator to `async_get_unit` / `async_get_temporary_unit`.

Have an idea? Open an issue at https://github.com/tnako/ha-foxair/issues
