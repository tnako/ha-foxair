# AGENTS.md — Working in ha-foxair

## Quick Start
```bash
cd .
python tools/validate.py          # Run after EVERY edit (gate)
tools/deploy.sh  # reads HA_HOST from .env  # Deploy to HA (requires SSH)
```

## Repository Structure
```
ha-foxair/
├── custom_components/foxair/     # HA integration (source of truth)
│   ├── coordinator.py            # pymodbus polling quick(30s)/medium(120s)/rare(300-600s)
│   │                             #   + debounced write coalescer + tier/hidden filtering
│   ├── sensor.py / climate.py / number.py / select.py / image.py
│   ├── const.py                  # loads foxair_config.json; order/sort/device routing
│   ├── translations/en/de/ru.json  # 3000+ lines each, CODE: prefix mandatory
│   └── data/
│       ├── foxair_config.json    # EDIT HERE: blocks, expert_blocks, HIDDEN ranges,
│       │                         #   dead_ranges, types, markers, per-addr overrides
│       ├── foxair_phnix_registers.json  # raw register knowledge (name/type/mode)
│       ├── foxair_metadata.json  # GENERATED — per-addr: platform, risk, requires_expert,
│       │                         #   hidden, poll_tier, group, min/max. Runtime truth.
│       └── foxair_phnix_knowledge.json
├── modbus/tabs.txt               # SOURCE OF TRUTH for register codes & order (247 lines)
├── tools/build_metadata.py       # registers+config -> metadata.json (RUN AFTER config edits)
├── tools/validate.py             # Version sync, i18n prefix check, syntax
├── tools/check_regs.py           # Register audit: tabs.txt+metadata codes vs HA entities (+ --direct Modbus)
├── tools/deploy.sh               # rsync + HA restart (HA_HOST env required)
├── VERSION / manifest.json / CHANGELOG.md
└── docs/archive/                 # Historical v0.3 reviews
```

## Fast Path — how to navigate without burning tool calls
Read metadata.json ONCE and derive everything from it; do NOT re-read
foxair_phnix_registers.json (5770 lines) or grep the 3×3000-line translation
files for register questions. One-shot recipes instead of exploratory loops:
- "Is addr X visible / editable / polled / hidden, which device/tab/tier?" →
  ONE call: `python3 -c "import json; print(json.load(open('custom_components/foxair/data/foxair_metadata.json'))['<X>'])"`
- "Show me the whole picture" → `python3 tools/metadata_report.py` (counts per
  group/risk/tier/hidden + any addrs in hidden ranges; extend it, don't re-derive).
- Entity-visibility bugs → check `requires_expert` + `hidden` + `risk` in metadata
  first; the platform code just filters on those 3 fields — never hunt through
  sensor.py/number.py/select.py unless a filter is suspected broken.
- Live-state checks → `ha_get_state` / `curl $HASS_URL/api/states` filtered in ONE
  pass (source HASS_URL/HASS_TOKEN from .env); no repeated single-entity probes.
- Modbus bus errors (transaction_id mismatch / Repeating / No response) → the
  EW11 allows ONE TCP client. Grep for `AsyncModbusTcpClient(` — there must be
  exactly one client lifetime, all I/O serialized on `coordinator._lock`.
  A second connect anywhere (write path, config flow probe, tools) = frame corruption.
- Register add/change: edit `foxair_config.json` (hidden/dead_ranges/overrides) or
  `foxair_phnix_registers.json` (names/types) → `python3 tools/build_metadata.py`
  → `python3 tools/validate.py`. Do NOT hand-edit foxair_metadata.json — regen clobbers it.
Budget: ≤10 tool calls for a "why is entity X shown/broken" diagnosis; if more,
you skipped the metadata one-shot and are grepping blind.

## Critical Invariants (validate.py enforces)
- `VERSION` == `manifest.json.version`
- Every code in `modbus/tabs.txt` has `CODE: Name` prefix in **all three** translation files
- No double prefix (`H42: H42 Name` → fail)
- Python syntax clean

## Modbus Architecture (0.4.x)
- Own `pymodbus.AsyncModbusTcpClient` (single socket, serialized under `coordinator._lock`).
  `modbus_connection` was tried and REVERTED (0.4.10) — EW11 `extra data` breaks it.
- Batches built from `foxair_metadata.json` poll tiers; `max_span=45`, `max_gap=8`,
  split around `dead_ranges` (EW11 gateway limits).
- Visibility model per register in metadata: `risk` (safe/advanced/dangerous/blocked),
  `requires_expert` (expert-mode gated), `hidden` (NEVER shown/polled — reserved/system).
- `vendor/foxair_modbus/` is generated but unused at runtime (kept for reference).

## Adding/Changing Registers
1. Edit `modbus/tabs.txt` (source of truth) if a NEW tab code is involved
2. Update `custom_components/foxair/data/foxair_phnix_registers.json` (knowledge)
   and/or `foxair_config.json` (hidden/dead_ranges/overrides/tiers)
3. Regenerate metadata: `python3 tools/build_metadata.py`
   (only if touching vendor code: `python3 tools/gen_foxair_modbus.py`)
4. Run `tools/validate.py` → fix i18n prefixes in `translations/*.json`
5. Bump `VERSION` + `manifest.json` + `CHANGELOG.md`
6. Deploy

## Common Tasks
| Task | Command |
|------|---------|
| Validate | `python tools/validate.py` |
| Check registers | `python tools/check_regs.py` (needs HASS_URL/HASS_TOKEN in `.env`; `--direct` adds raw Modbus reads, `--codes H01,P02` filters, `--show-all` lists everything) |
| Deploy | `tools/deploy.sh  # reads HA_HOST from .env` |
| Bump version | Edit `VERSION`, `manifest.json`, `CHANGELOG.md` |
| Add register | Edit `modbus/tabs.txt` → regen vendor → validate |

### check_regs.py — register end-to-end audit
Checks all 310 codes (tabs.txt order + metadata-only codes: KG timers, T-Diag,
ERR, SG, sub-codes) against live HA entities via REST, optionally against the
device directly (`--direct`, EW11 single-client — pause the integration for a
clean comparison). Verdicts: OK / UNKNOWN / UNAVAILABLE / MISMATCH /
NOT-EXPOSED (disabled or hidden entity, informational) / EXPERT-ONLY /
BITFIELD-REG + NON-HOLDING (no per-code entity by design: O/S blocks = regs
2019/2034; H43/E01/T35 coil/cloud-only). Exit 1 only on real problems
(UNKNOWN/UNAVAILABLE/MISMATCH/NO-RESPONSE).

## DO NOT
- Skip `validate.py` after edits
- Change `entity_id` (stable IDs required — only friendly names reorder)
- Commit generated vendor code without running validate

## Related Repos
- `sibling modbus repo/` — Go test client + `tabs.txt` mirror + PDF docs
- `sibling desktop app repo/` — Windows desktop app (Warmlink cloud, device info, firmware analysis)

## HA Environment
- HA Core (Docker) — see .env
- Supervisor token at `<supervisor-token-path>` on host
- Use `ha_*` tools (pre-configured with HASS_URL/HASS_TOKEN) over raw curl