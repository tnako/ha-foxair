# Roadmap

**Current:** `0.5.x` (`0.5.4`) — HA **≥2026.3** via `pymodbus>=3.6.0` (single `AsyncModbusTcpClient`, `coordinator._lock`, tiered polling `quick 30 s` / `medium 120 s` / `rare 300-600 s`, batched `max_span=45`/`max_gap=8`).

**Next:** `0.5.x` maintenance — register syncs, i18n, bugfixes, HA ≥2026.3 stays.

**Future** — when a future HA release bundles `modbus-connection` with a shared `modbus` bus, migrate to it: add `dependencies: ["modbus"]`, bump `homeassistant` in `hacs.json`/`manifest.json`, drop `pymodbus` from pip `requirements`, and switch the coordinator to `async_get_unit` / `async_get_temporary_unit`. Same `foxair-modbus` model, just the `ModbusUnit` source changes — shares the socket with other devices on the same gateway. No YAML `modbus:` breakage expected; UI setup will share the bus automatically.

Have an idea? Open an issue at https://github.com/tnako/ha-foxair/issues
