# Roadmap

**0.1** - Live diagnostics (temperatures, flow, compressor). Bulk reading, HACS install.

**0.2** - Full register set. Everyday controls stay visible, expert controls are hidden as Diagnostic until you enable them. Translations EN/DE/RU.

**0.3** - Safe writing with limits, SG Ready, pump modes and climate controls. On/Off as `hvac_mode: Off` (1011), 4 presets `Heating`/`Cooling`/`Heating+Hot Water`/`Cooling+Hot Water` (1012), curve panel.

**0.4** - Modern Modbus via `modbus-connection` + standalone `foxair-modbus` library (pip) — **HA ≥2026.3, no 2026.9 required**. Own `ModbusConnection(ModbusTcpParams)` via `modbus_connection.pymodbus`, pooled reads (one per space vs 12 `POLL_BLOCKS`), typed `Component` model (`gauge`/`coil`/`uint32`), pytest mock, ~30-35% less code in `custom_components/foxair`. Same entities; YAML `modbus:` still works. `manifest.json` adds `requirements: ["modbus-connection[pymodbus]>=4.8","foxair-modbus>=0.1.0"]`, no `dependencies: ["modbus"]`.

**0.5** - Require **HA 2026.9+**, switch to HA-bundled `modbus-connection` + shared `modbus` bus (`async_get_unit`/`async_get_temporary_unit`). Add `dependencies: ["modbus"]`, set `homeassistant: "2026.9.0"` in `hacs.json`/`manifest.json`, **remove** `modbus-connection`/`pymodbus` from pip `requirements` and delete any system-wide `pip install modbus-connection` (HA now bundles it). Same `foxair-modbus` model, just `ModbusUnit` source changes — sharing socket with Fronius/Sofar/Flexit on same gateway.

Details: `.hermes/plans/2026-08-28-v0.4-modbus-connection-migration.md` (11 tasks) · https://developers.home-assistant.io/docs/modbus/introduction · https://developers.home-assistant.io/blog/2026/07/05/modernizing-modbus

Have an idea? Open an issue at https://github.com/tnako/ha-foxair/issues
