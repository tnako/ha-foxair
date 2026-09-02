# Roadmap

**Current:** `0.5.2` — HA **≥2025.3** via `pymodbus>=3.6.0` (single `AsyncModbusTcpClient`, `coordinator._lock`, tiered polling `quick 30 s` / `medium 120 s` / `rare 300-600 s`, batched `max_span=45`/`max_gap=8`).

What shipped in 0.5.x:
- **0.5.0** — configurable entity prefix (multiple pumps), timer overhaul (TIME_DECIMAL/TIME_SPLIT, `switch` platform), i18n double-prefix fix
- **0.5.1 / 0.5.2** — code-quality passes (bare `except` → `except Exception`, ruff E701/E702/F401)

What shipped in 0.4.x:
- Pooled reads replacing 12 manual `POLL_BLOCKS`, metadata-driven visibility (`risk`/`requires_expert`/`hidden`), dead-range splitting, heating-curve panel, computed sensors
- `modbus-connection` was evaluated and **reverted** — EW11 `extra data` framing breaks it; integration stays on owned `pymodbus` client (see `coordinator.py:1`)

**Next:** `0.5.x` maintenance — register syncs, i18n, bugfixes, HA ≥2025.3 stays.

**Future** — when a future HA release bundles `modbus-connection` with a shared `modbus` bus, migrate to it: add `dependencies: ["modbus"]`, bump `homeassistant` in `hacs.json`/`manifest.json`, drop `pymodbus` from pip `requirements`, and switch the coordinator to `async_get_unit` / `async_get_temporary_unit`. Same `foxair-modbus` model, just the `ModbusUnit` source changes — shares the socket with other devices on the same gateway. No YAML `modbus:` breakage expected; UI setup will share the bus automatically.

Have an idea? Open an issue at https://github.com/tnako/ha-foxair/issues
