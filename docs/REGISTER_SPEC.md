# FoxAir/PHNIX Modbus Register Specification

> **Source of truth:** `modbus/tabs.txt` (this repo) — all other files derived.

## Tab Structure (Order Matters)
| Tab | Block | Title | Range | Count | Poll Tier |
|-----|-------|-------|-------|-------|-----------|
| H   | Base/Hardware    | 1018–1043 | 21 | quick |
| A   | Protection/Limits| 1061–1100 | 23 | medium |
| F   | Fan              | 1121–1147 | 17 | medium |
| D   | Defrost          | 1151–1200 | 26 | rare |
| E   | EVI/EEV          | 1211–1260 | 25 | rare |
| R   | Setpoints        | 1271–1337 | 37 | quick |
| P   | Pump             | 1351–1380 | 14 | medium |
| G   | Legionella       | 1391–1397 | 7  | rare |
| C   | Compressor       | 1411–1430 | 11 | medium |
| Z   | Zone             | 1441–1470 | 16 | medium |
| O   | Outputs          | 1501–1517 | 11 | quick |
| S   | Switches         | 1521–1530 | 7  | quick |
| T   | Diagnostics/Live | 2001–2180 | 54 | quick+medium |
| SG  | SG Ready         | 1334, 8801(virtual) | 2 | quick |
| KG  | Timer            | 1601–1750 | 20 | rare |
| ERR | Fault            | 1801–1850 | 15 | quick |

**Total: 296 codes → 591 registers (some codes span multiple registers)**

## Data Types & Scaling
| Type | Scale | Unit | HA Device Class |
|------|-------|------|-----------------|
| TEMP1      | ÷10   | °C   | temperature |
| TEMP05     | ÷2    | °C   | temperature |
| DIGI1      | ×1    | —    | — |
| DIGI5      | ÷10   | —    | — |
| DIGI6      | ÷1000 | —    | — |
| VOLT       | ×1    | V    | voltage |
| AMP_X10    | ÷10   | A    | current |
| BAR_X10    | ÷10   | bar  | pressure |
| FLOW_M3H_X10 | ÷10 | m³/h | — |
| RPM        | ×1    | rpm  | — |
| WATT       | ×1    | W    | power |
| KWH        | ×1    | kWh  | energy |
| COP_X100   | ÷100  | —    | — |

## Writable Registers (Subset)
| Code | Addr | Type | Min | Max | Risk | Notes |
|------|------|------|-----|-----|------|-------|
| H01  | 1018 | DIGI1 | 0 | 1 | safe | Power-off memory |
| H05  | 1021 | DIGI1 | 0 | 1 | safe | Cooling enable |
| R01  | 1271 | TEMP1 | 150 | 700 | safe | DHW target |
| R02  | 1272 | TEMP1 | 70 | 280 | safe | Heating target |
| R03  | 1273 | TEMP1 | 50 | 250 | safe | Cooling target |
| 1234 | 1234 | TEMP1 | 20 | 200 | advanced | Heating curve slope |
| 1235 | 1235 | TEMP1 | -50 | 50 | advanced | Heating curve offset |
| 1334 | 1334 | DIGI1 | 0 | 3 | safe | SG Ready mode |
| 8801 | 8801 | DIGI1 | 0 | 1 | safe | Virtual SG Ready |

> Full writable list with ranges: `custom_components/foxair/data/foxair_phnix_knowledge.json` → `"writable"` entries.

## Cross-Repo Mapping
| Artifact | Location | Purpose |
|----------|----------|---------|
| `tabs.txt` | `modbus/tabs.txt` / `ha-foxair/modbus/tabs.txt` | **Source of truth** — code, name, order |
| `foxair_phnix_registers.json` | `ha-foxair/custom_components/foxair/data/` + `FoxAir_Control/core/` | Full register metadata (type, scale, limits, writable, desc) |
| `foxair_phnix_knowledge.json` | Same | Parsed ranges, value maps, risk tiers |
| `heat_pump.py` | `ha-foxair/custom_components/foxair/vendor/foxair_modbus/` | Generated `modbus_connection.Component` (591 regs) |
| `registerMap` | `modbus/main.go` | Go test client subset |
| `TABS_CODE_ORDER` | `ha-foxair/custom_components/foxair/const.py` | HA entity creation order |

## Regeneration Pipeline
```bash
# 1. Edit source
vim modbus/tabs.txt

# 2. Update knowledge JSON (manual or semi-auto)
#    foxair_phnix_registers.json ← tabs.txt + PDF specs
#    foxair_phnix_knowledge.json ← registers.json + value maps

# 3. Regenerate vendor Component
cd ha-foxair
python tools/gen_foxair_modbus.py

# 4. Validate (i18n prefixes, version, syntax)
python tools/validate.py

# 5. Sync to FoxAir_Control (if needed)
cp custom_components/foxair/data/foxair_phnix_*.json sibling desktop app repo/core/
```

## Maintenance Notes
- **Never edit generated files directly** (`heat_pump.py`, `TABS_CODE_ORDER`)
- **Tabs.txt is the contract** — if it's not in tabs.txt, it doesn't exist
- **Translations must mirror tabs.txt prefixes exactly** (`H01: Name`, not `Name [H01]`)
- **New registers → add to tabs.txt first**, then propagate