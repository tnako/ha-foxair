# AGENTS.md — Working in ha-foxair

## Quick Start
```bash
cd /Users/chado/work/GIT/ha-foxair
python tools/validate.py          # Run after EVERY edit (gate)
tools/deploy.sh  # reads HA_HOST from .env  # Deploy to HA (requires SSH)
```

## Repository Structure
```
ha-foxair/
├── custom_components/foxair/     # HA integration (source of truth)
│   ├── vendor/foxair_modbus/     # Vendored modbus_connection Component (591 regs)
│   ├── coordinator.py            # Tiered polling: quick(30s)/medium(120s)/rare(300s)
│   ├── sensor.py / climate.py / number.py / select.py / image.py
│   ├── const.py                  # TABS_CODE_ORDER = exact tabs.txt sequence
│   ├── translations/en/de/ru.json  # 3000+ lines each, CODE: prefix mandatory
│   └── data/*.json               # Register knowledge (foxair_phnix_registers.json = 5770 lines)
├── modbus/tabs.txt               # SOURCE OF TRUTH for register codes & order (247 lines)
├── tools/validate.py             # Version sync, i18n prefix check, syntax
├── tools/deploy.sh               # rsync + HA restart (HA_HOST env required)
├── VERSION / manifest.json / CHANGELOG.md
└── docs/archive/                 # Historical v0.3 reviews
```

## Critical Invariants (validate.py enforces)
- `VERSION` == `manifest.json.version`
- Every code in `modbus/tabs.txt` has `CODE: Name` prefix in **all three** translation files
- No double prefix (`H42: H42 Name` → fail)
- Python syntax clean

## Modbus Architecture (0.4.x)
- **Owned `ModbusConnection`** via `modbus_connection[pymodbus]` (not shared-bus)
- `vendor/foxair_modbus/heat_pump.py` = generated `Component` with 591 registers
- `max_span=45`, `max_gap=8` (EW11 gateway limits)
- Pooled reads via `Component.read_all()` — no manual `POLL_BLOCKS`

## Adding/Changing Registers
1. Edit `modbus/tabs.txt` (source of truth)
2. Update `custom_components/foxair/data/foxair_phnix_registers.json` (knowledge)
3. Regenerate `vendor/foxair_modbus/heat_pump.py` via `tools/gen_foxair_modbus.py`
4. Run `tools/validate.py` → fix i18n prefixes in `translations/*.json`
5. Bump `VERSION` + `manifest.json` + `CHANGELOG.md`
6. Deploy

## Common Tasks
| Task | Command |
|------|---------|
| Validate | `python tools/validate.py` |
| Deploy | `tools/deploy.sh  # reads HA_HOST from .env` |
| Bump version | Edit `VERSION`, `manifest.json`, `CHANGELOG.md` |
| Add register | Edit `modbus/tabs.txt` → regen vendor → validate |

## DO NOT
- Skip `validate.py` after edits
- Change `entity_id` (stable IDs required — only friendly names reorder)
- Commit generated vendor code without running validate

## Related Repos
- `../modbus/` — Go test client + `tabs.txt` mirror + PDF docs
- `../FoxAir_Control/` — Windows desktop app (Warmlink cloud, device info, firmware analysis)

## HA Environment
- HA Core 2026.8.2 on Debian 13 (Docker), REST API port 8123
- Supervisor token at `/usr/share/hassio/token` on host
- Use `ha_*` tools (pre-configured with HASS_URL/HASS_TOKEN) over raw curl