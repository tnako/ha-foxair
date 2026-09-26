# FoxAir Modbus Heat Pump for Home Assistant

Control and monitor your **FoxAir / PHNIX air-to-water heat pump** directly from Home Assistant over Modbus TCP — no cloud, no YAML.

![Version](https://img.shields.io/badge/version-0.7.14-blue) ![HA](https://img.shields.io/badge/Home%20Assistant-%3E%3D2026.9-green) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

![FoxAir Demo](docs/screenshots/foxair_demo.gif)

Register maps and scaling based on the reverse-engineering in [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control).

## What you get

- **Live diagnostics** — inlet/outlet, coil, ambient, exhaust, pressures, flow, compressor freq, fan RPM, voltages
- **Controls** — heating / DHW / cooling setpoints, SG Ready, pump modes, zone mixing valves, climate **Off / Heat** with 4 DHW presets
- **Hot water** — `water_heater.foxair_dhw`: tank temperature (T08), target (R01) within the unit's R36/R37 limits
- **Fault alarm** — `binary_sensor.foxair_fault` (problem) is on while any documented fault bit is set; `active_faults` lists them
- **PV surplus** — `switch.foxair_pv_surplus` for EVCC or HA automations, see below
- **Runtime counters** — compressor runtime (2032, h) and compressor starts (2023, firmware 3.3+) as total counters, read from the unit
- **Heating curve** — slope / offset / mode with an SVG graph image entity — no Lovelace YAML
- **Computed sensors** — heating power, electrical power, COP from `flow·ΔT`
- **Multiple pumps** — configurable entity prefix so each unit gets its own IDs
- **Safety** — expert mode gates installer controls; writes are validated
- **i18n** — English, German, Russian, all with `CODE:` prefix
- **Firmware-gated** — SG Ready modes 1/2 (SG01 / 1334), manual defrost / silent flag / manual heat (1016), and power-off-memory autostart (1018) are automatically hidden on devices running Firmware < 3.3 (auto-detected from register 2104) and appear when the firmware meets the gate

## How it works

Reads go through a single `pymodbus.AsyncModbusTcpClient` (the EW11 gateway allows only one TCP client) and a `FoxAirCoordinator` polling every 30 s. Entities read via shared metadata and write back with a fast 350 ms read-back. Each register carries `risk`, `requires_expert`, and `hidden` flags — hidden ones (system/reserved) are never created, polled, or written.

## Which temperature the thermostat shows (H25)

The climate entity follows the unit's own control settings, it never assumes outlet water:

| Setting | Climate current temperature | Climate target |
| --- | --- | --- |
| H25 = Outlet / Inlet / Buffer water | T02 / T01 / T07 | R02 heating, R03 cooling; the live curve target (2014) while heating with H36 = on |
| H25 = Room | T09 | R70 target room temperature |

With H36 = on the heating curve drives the target, so changing the thermostat target (for example with the +/- buttons) shifts the curve offset (1235) by the same amount. The slope stays unchanged, so the whole curve moves up or down. The new target shows at once and is replaced by the device value (2014) once the unit has recalculated.

The climate attributes `control_source`, `current_addr` and `target_addr` show which registers are in use. If they disagree with H25, run `tools/check_regs.py` (the `CLIMATE:*` rows) and include its output plus a diagnostics download in the issue. The heating-curve image always plots the heating water side; its y-axis names the H25 sensor.

## Requirements

- Home Assistant **>= 2026.9**
- Python `pymodbus>=3.6.0`
- FoxAir/PHNIX on Modbus TCP (tested with an Elfins EW11 at the default `host:8899 slave 1`)

## Installation via HACS (recommended)

1. Make sure [HACS](https://hacs.xyz/docs/use/) is installed.
2. **HACS → Integrations → ⋯ → Custom repositories** → add `https://github.com/tnako/ha-foxair` as `Integration`.
3. Search **FoxAir** → **Install** → **Restart**.
4. **Settings → Devices & Services → Add Integration → FoxAir Heat Pump** → host / port / slave (defaults fill in automatically).

You get a **FoxAir Heat Pump** device with sub-devices per block (setpoints, diagnostics, pump, SG Ready, …). Safe controls are on by default; enable **Expert mode** in the options to reach installer controls.

## Manual installation

Copy `custom_components/foxair` to `/config/custom_components/foxair` (HAOS: `scp -r custom_components/foxair homeassistant@homeassistant.local:/usr/share/hassio/homeassistant/custom_components/`), then restart.

## Configuration

- **Options** (⋯ on the integration card): turn on **Expert mode** (+ ack) to expose advanced controls; pick an **Electrical power source for COP**
- **Entity prefix** — set when adding the integration so several pumps don't collide (default: `foxair`).
  Each pump needs its own entry with a unique prefix (`house1`, `cottage`) AND a different
  Modbus slave ID (1, 2, …). Devices render as `House1 Heat Pump (slave 2)` with
  sub-devices (`House1 — Setpoints [R] (slave 2)`), entities as `sensor.house1_1158`.
  Host/port/slave/prefix stay editable via ⋯ → Reconfigure (prefix change renames all
  entity IDs of that pump). Diagnostics show host/port/slave/prefix per entry.
- **Climate** → `Off` / `Heat` + presets `Heating`, `Cooling`, `Heating+Hot Water`, `Cooling+Hot Water`
- **Heating curve** → Slope / Offset / Mode → live `sensor.foxair_heating_curve_target` + graph
- **PV surplus** → `switch.foxair_pv_surplus` (firmware 3.3+): on = SG Ready mode 4 High PV, off = mode 2 normal, written to the virtual SG input 8801. Needs **SG01 = Modbus / virtual SG input** (1334 = 3), no SG contacts wired. In EVCC use the *Home Assistant switch* charger with this entity. The unit applies a new SG mode at most every 10 minutes: the switch shows the request at once, `sensor.foxair_sgstatus` shows the mode the unit accepted. Mode 4 behaviour (setpoint raise, power) is set in the SG block (SG03-SG08)

## Help & diagnostics

Enable logging in `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.foxair: debug
    pymodbus: info
```

**Settings → Devices → FoxAir → Download diagnostics** shows host/port/slave, poll/error stats, and sample raw/value (no secrets).

More: [DEBUG.md](docs/DEBUG.md), [ROADMAP.md](docs/ROADMAP.md), [CHANGELOG.md](CHANGELOG.md).

## Development

- Generate metadata: `python3 tools/build_metadata.py`
- Sort / fix translations: `python3 tools/fix_translations.py`
- Validate: `python tools/validate.py`
- Audit registers: `python tools/check_regs.py` (set `HASS_URL`/`HASS_TOKEN` in `.env`; `--direct` for raw Modbus, `--codes H01,P02` to filter)
- Deploy: `tools/deploy.sh` (reads `HA_HOST` from `.env`)

## License

MIT — see [LICENSE](LICENSE)