# Tools

All generators are **required** and share the same source-of-truth: `custom_components/foxair/data/foxair_phnix_*.json` (from FoxAir_Control).

| Script | Purpose | When to run |
|---|---|---|
| `build_metadata.py` | `foxair_metadata.json` — 591 entries with `group`/`editable`/`min`/`max`/`risk`/`platform`/`icon` from `registers.json` + `knowledge.json` (117+ ranges parsed, `RANGE_OVERRIDES` for slope etc.) | After any `data/` update |
| `fix_translations.py` | `strings.json` + `translations/{en,de,ru}.json` — 595 sensor / 231 number / 86 select sorted numerically (50043 after 2180, non-numeric last), EN default, fixes German leak (Block Header Packet 3-8 etc.) and outdated 2125-2138 | After any `data/` update or i18n fix |
| `gen_bitfield_translations.py` | per-bit binary_sensor names (addr and code keys) + icons from `bit_map` and `BIT_TEXT` | After any `bit_map` change |
| `modbus_probe.py` | live read / verified write with `--watch` + `--restore` / unit scan; host from `.env` `MODBUS_*` | Before adding or changing register semantics |
| `check_regs.py` | HA state vs metadata (and `--direct` device) audit | Before a release with a live HA |

All three are run together on a data sync:

```bash
python3 tools/build_metadata.py && python3 tools/fix_translations.py
```

Outputs are committed — HACS installs the generated JSON/py only, no build step on the HA host.
