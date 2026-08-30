# FoxAir Modbus Heat Pump for Home Assistant

Control and monitor your **FoxAir / PHNIX air-to-water heat pump** directly from Home Assistant over Modbus TCP — no cloud, no YAML.

![Version](https://img.shields.io/badge/version-0.4.28-blue) ![HA](https://img.shields.io/badge/Home%20Assistant-%3E%3D2026.3-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

Registers and scaling are based on the reverse-engineering in [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) (591 registers, FoxAir_Control 0.2.62 / 5607b5a).

## What you get

- **Live diagnostics** — inlet/outlet, coil, ambient, exhaust, pressures, flow, compressor freq, fan RPM, voltages
- **New in 0.4.x** — humidity sensor temp / relative humidity / dewpoint (2178-2180), DHW energy 32-bit counters (2125-2128), T04 secondary outdoor temp (2136), WP power without booster (2137-2138)
- **Controls** — heating / DHW / cooling setpoints (R01-R03), SG Ready (1334 + virtual 8801), pump modes, zone mixing valves, climate **Off / Heat** with 4 DHW presets
- **Heating curve** — slope (1234) / offset (1235) / mode (1236) with live panel **FoxAir Curve** (iframe `/api/foxair/heating-curve-panel`, SVG `/api/foxair/heating_curve.svg`) — no Lovelace YAML
- **Computed sensors** — heating power, electrical power, COP from water `flow·ΔT` with EMA + hold-last-good and configurable `elec_source` (register 2054 / V×A / external meter)
- **Safety** — 3-tier risk (`safe`/`advanced`/`dangerous`/`blocked`), expert mode gated behind ack, all writes min/max validated (117+ ranges parsed from knowledge)
- **i18n** — English default (strings.json = en), German and Russian, 595 sensor keys sorted numerically (50043+ after 2180), no German leak

## How it works (0.4.x)

- **Pooled reads** via vendored `foxair-modbus` (`custom_components/foxair/vendor/foxair_modbus` — `modbus_connection` `Component` `gauge`/`integer`, `max_span=65`/`max_gap=12`, one request per contiguous space instead of 12 manual `POLL_BLOCKS`)
- **Owned connection** `ModbusConnection(ModbusTcpParams(host,port)).for_unit(slave)` via `modbus_connection[pymodbus]>=4.8` (HA ≥2026.3, no 2026.9 required — see [Roadmap](docs/ROADMAP.md))
- **Coordinator** `FoxAirCoordinator` (`DataUpdateCoordinator`, 30 s) + `FoxAir( unit ).async_update()`; entities (`sensor`/`number`/`select`/`climate`/`image`) read via `get_metadata` and write via `async_write_register` with fast 350 ms read-back
- **591** entries in `foxair_metadata.json` (234 safe / 259 advanced / 7 dangerous / 91 blocked), 469 polled fields (service ProductKey 200-215 and C544/C37B 50043+ excluded from poll)

## Requirements

- Home Assistant **≥2026.3** ( `modbus-connection[pymodbus]>=4.8` via `manifest.json` requirements)
- FoxAir/PHNIX on Modbus TCP (tested via `Elfins EW11` @ `EW11-host:8899 slave 1` — defaults)

## Installation via HACS (recommended)

1. Ensure [HACS](https://hacs.xyz/docs/use/) is installed.
2. **HACS → Integrations → ⋯ → Custom repositories** → add `https://github.com/tnako/ha-foxair` as `Integration`.
3. Search **FoxAir** in HACS → **Install** → **Restart**.
4. **Settings → Devices & Services → Add Integration → FoxAir Heat Pump** → host / port / slave (defaults `EW11-host` / `8899` / `1`).

Device appears as **FoxAir Heat Pump** with sub-devices per block (`R` setpoints, `T` diagnostics incl. humidity, `P` pump, `SG` SG Ready, …). Safe controls are enabled; installer controls are `Diagnostic` disabled until you enable the entity (or enable Expert mode).

## Manual installation

Copy `custom_components/foxair` to `/config/custom_components/foxair` on your HA host (HAOS: `scp -r custom_components/foxair root@homeassistant.local:/usr/share/hassio/homeassistant/custom_components/`), restart.

## Configuration

- **Options** ( ⋯ on the integration card): `Enable expert mode` + `I understand the risk` ack → exposes `advanced`/`dangerous` numbers/selects; `Electrical power source for COP` (foxair_register / foxair_v_a with gains / external_meter)
- **Climate** `climate.foxair` → `Off` (1011=0) / `Heat` (1011=1) + presets `Heating`/`Cooling`/`Heating+Hot Water`/`Cooling+Hot Water` (1012, DHW-only mapped)
- **Heating curve** numbers `Heating Curve Slope/Offset/Mode` on the main device → native curve target sensor `sensor.foxair_heating_curve_target` (2014) and panel/SVG

## Help and diagnostics

- `configuration.yaml`:

  ```yaml
  logger:
    logs:
      custom_components.foxair: debug
      modbus_connection: debug
  ```

- **Settings → Devices → FoxAir → Download diagnostics** → host/port/slave, polls/errors/last_ms, sample raw/value (no passwords)
- See [DEBUG.md](docs/DEBUG.md), [ROADMAP.md](docs/ROADMAP.md), [CHANGELOG.md](CHANGELOG.md)

## Data source & attribution

Register maps, block names and scaling are based on the reverse-engineering in [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) (`data/foxair_phnix_registers.json` + `foxair_phnix_knowledge.json` copied verbatim, PDFs not redistributed). Thank you to its authors. Display registers (`foxair_phnix_display_registers.json`) are kept for reference only (not polled).

## Development

- Generate metadata: `python3 tools/build_metadata.py` (591 entries, diagnostic group for 2125-2138+2178-2180)
- Generate vendor model: `python3 tools/gen_foxair_modbus.py` (469 fields; ProductKey/C544 excluded from poll)
- Fix i18n: `python3 tools/fix_translations.py` (sorts 595 sensor / 231 number / 86 select numerically, EN=DE/RU parity, fixes German leak)

## License

MIT — see [LICENSE](LICENSE)
