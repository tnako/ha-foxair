# FoxAir Modbus Heat Pump for Home Assistant

Control and monitor your FoxAir / PHNIX heat pump directly from Home Assistant over Modbus TCP.

This integration reads the heat pump in efficient bulk blocks, so the Modbus bus stays calm and responsive. The register layout and scaling are the same as used in FoxAir_Control.

**Roadmap:** `0.4` ships now on pip `modbus-connection` (HA ≥2026.3) — `0.5` moves to HA 2026.9+ built-in shared bus (see `docs/ROADMAP.md`).

**What you get**
- Live temperatures, pressures, flow and compressor state
- Heating / hot water setpoints you can safely adjust
- Pump and SG Ready controls
- Expert settings hidden by default - enable only if you know what they do
- English, German and Russian names

## Installation via HACS (recommended)

1. Ensure [HACS](https://hacs.xyz/docs/use/) is installed.
2. In Home Assistant open **HACS -> Integrations -> three dots -> Custom repositories**.
3. Add `https://github.com/tnako/ha-foxair` with category `Integration`.
4. Search for **FoxAir** in HACS, hit **Install**, then **Restart**.
5. Go to **Settings -> Devices & Services -> Add Integration -> FoxAir Heat Pump**.
6. Enter host, port and slave ID (defaults are `EW11-host`, `8899`, `1`).

Your heat pump appears as one device with entities grouped like in FoxAir_Control:
`R` heating setpoints, `T` live diagnostics, `P` pump, `SG` SG Ready and so on. Safe everyday controls are enabled, installer controls are hidden under **Diagnostic** - enable them per entity if needed.

## Manual installation

Copy `custom_components/foxair` to `/config/custom_components/foxair` on your Home Assistant host (HAOS: `scp -r custom_components/foxair root@your-ha:/usr/share/hassio/homeassistant/custom_components/`), then restart.

## Help and diagnostics

- Set `custom_components.foxair: debug` in `logger` to see detailed polling logs.
- Use **Settings -> Devices -> FoxAir -> Download diagnostics** to export a support file (contains addresses and raw values, no passwords).
- See `docs/DEBUG.md` and `CHANGELOG.md` for details.

## Attribution

Register maps, block names and value scaling are based on the amazing reverse-engineering in [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control). PDFs and manuals from that project are not redistributed here - thank you to its authors.

## License

MIT - see LICENSE

## Heating Curve Panel
After install a sidebar **FoxAir Curve** appears (iframe `/api/foxair/heating-curve-panel`) with live chart `Slope/Offset/Fixed R02` and SVG `/api/foxair/heating_curve.svg` — no dashboard YAML needed.
