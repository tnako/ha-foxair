# Data

Source-of-truth is [dosordie/FoxAir_Control](https://github.com/dosordie/FoxAir_Control) `data/` — copied verbatim, PDFs not redistributed.

| File | Entries | Notes |
|---|---|---|
| `foxair_phnix_registers.json` | 591 (excl. `_comment`) | 200-215 ProductKey ASCII, 1001+ Block Headers, H/A/F/D/E/C/R/Z/G/P/SG/KG/T live; 2178-2180 humidity/dewpoint, 2125-2128 DHW 32-bit energy, 2136-2138 T04/power |
| `foxair_phnix_knowledge.json` | 560 | descriptions + defaults for min/max parsing (117+ ranges), SG Ready 8801 virtual 10-min hold |
| `foxair_phnix_display_registers.json` | 186 | HMI display registers — **not polled**, kept for reference only (`ARCHITECTURE_REVIEW` dead-data note fixed) |
| `foxair_metadata.json` | 591 | **Generated** by `tools/build_metadata.py` — `editable`/`platform`/`risk`/`group`/`icon`/`min`/`max`/`step` |

After updating `foxair_phnix_*.json`:

```bash
python3 tools/build_metadata.py && python3 tools/gen_foxair_modbus.py && python3 tools/fix_translations.py
```

Vendor `foxair_modbus` polls 469 fields (ProductKey 200-215 + C544/C37B 50043+ excluded from poll, diagnostic Header/Reserved). See `tools/README.md`.
