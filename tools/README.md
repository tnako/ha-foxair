# Tools

All generators are **required** and share the same source-of-truth: `custom_components/foxair/data/foxair_phnix_*.json` (from FoxAir_Control).

| Script | Purpose | When to run |
|---|---|---|
| `build_metadata.py` | `foxair_metadata.json` — 591 entries with `group`/`editable`/`min`/`max`/`risk`/`platform`/`icon` from `registers.json` + `knowledge.json` (117+ ranges parsed, `RANGE_OVERRIDES` for slope etc.) | After any `data/` update |
| `gen_foxair_modbus.py` | `vendor/foxair_modbus/heat_pump.py` — 469 `Component` `gauge`/`integer` fields (`max_span=65`/`max_gap=12`), excludes service ProductKey 200-215 and C544/C37B 50043+ from poll | After any `data/` update |
| `fix_translations.py` | `strings.json` + `translations/{en,de,ru}.json` — 595 sensor / 231 number / 86 select sorted numerically (50043 after 2180, non-numeric last), EN default, fixes German leak (Block Header Packet 3-8 etc.) and outdated 2125-2138 | After any `data/` update or i18n fix |

All three are run together on a data sync:

```bash
python3 tools/build_metadata.py && python3 tools/gen_foxair_modbus.py && python3 tools/fix_translations.py
```

Outputs are committed — HACS installs the generated JSON/py only, no build step on the HA host.
