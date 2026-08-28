# Roadmap

**Current:** `0.4.3` — HA **≥2026.3** via pip `modbus-connection[pymodbus]>=4.8` + vendored `foxair-modbus` (owned `ModbusConnection`, pooled reads `max_span=65`/`max_gap=12`, 469 fields, 595 translations sorted numerically). No HA 2026.9 required.

What shipped in 0.4.x:
- **0.4.0** — migrate from `AsyncModbusTcpClient`+12 `POLL_BLOCKS` to `modbus-connection` `Component` (`gauge`/`integer`), pooled reads, ~35% slimmer coordinator
- **0.4.1** — sync registers/knowledge from FoxAir_Control 0.2.62 (2178-2180 humidity/dewpoint, 2125-2128 DHW energy, 2136-2138 T04/power, ProductKey/C544 labels)
- **0.4.2** — i18n validation (English default, 0 German leak, 595 sensor parity)
- **0.4.3** — reorder translations numerically (2127→2136→2178→50043→50500) + generator sort

**Next:** `0.4.x` maintenance — register syncs, i18n, bugfixes, HA ≥2026.3 stays.

---

**0.5** — Require **HA 2026.9+**, switch to HA-bundled `modbus-connection` + shared `modbus` bus (`async_get_unit`/`async_get_temporary_unit`). Add `dependencies: ["modbus"]`, set `homeassistant: "2026.9.0"` in `hacs.json`/`manifest.json`, **remove** `modbus-connection`/`pymodbus` from pip `requirements` and delete any system-wide `pip install modbus-connection` (HA now bundles it). Same `foxair-modbus` model, just `ModbusUnit` source changes — sharing socket with Fronius/Sofar/Flexit on same gateway.

No YAML `modbus:` breakage — that still works. UI setup will share the bus automatically in 0.5.

Have an idea? Open an issue at https://github.com/tnako/ha-foxair/issues
