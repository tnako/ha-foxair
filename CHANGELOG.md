## 0.3.7
- refactor: reorganize into per-block HA devices mirroring FoxAir_Control ParameterSettingsDialog BLOCK_SHORT (H/A/F/D/E/C/R/T/Z/G/P/SG/KG/ERR) + Main Heat Pump on top
- Main device [climate + 1011 ON/OFF + 1012 mode + 1157-1159 setpoints + 1234-1236 curve + 2048/2046 live] stays first (climate card)
- each block becomes sub-device FoxAir — <label> [BLOCK] via Main (e.g. Setpoints [R], Diagnostics/Live [T], Pump [P], Defrost [D], Compressor [C], EVI/EEV [E], Fan [F], Protection [A], Hardware [H], Zone [Z], SG Ready [SG], Legionella [G]); grouping uses metadata.block identical to FoxAir_Control data/foxair_phnix_registers.json + BLOCK_SHORT_DE
- fix duplication: sensor no longer created for editable number/select (was R06 1174 sensor + number both foxair_1174) — writable owns entity only — cuts ~70 duplicates, editable stays number/select, read-only stays sensor
- min/max still from FoxAir_Control data/foxair_phnix_knowledge.json description parsing (e.g. "-40.0 10.0°C,TEMP1" -> -40/10, "0,0 bis 10,0°C" -> 0/10, "1 180min" -> 1/180) via build_metadata.py parse_range + per-type fallbacks; unbounded or Rxx-bounded (R36 bis R37) fallback to safe range so write fail-closed

## 0.3.6
- i18n: fix SG & all 61 dropdowns German-only — options now use HA state translation slugs (off/on/single_contact/dhw etc) with proper en/de/ru; 1334 Single/Dual contact, 1011 Off/On, 1012 DHW/Heating/Cooling etc; select.py now uses translation_key + slug maps + legacy fallback; strings + translations for 86 selects

## 0.3.5
- ci: fix hassfest dependencies — add http (views) + frontend (panel) to dependencies (was only frontend), fixes [DEPENDENCIES] Using component http error from 0.3.4

## 0.3.4
- fix 15-review batch: coordinator reconnect + partial poll merge + json off loop + 0.05s (was 0.3s×7), diagnostics full stats/sample/curve, security parse_range hex/degenerate fail-closed + 37 null fallback, climate DHW R01 1157 + HEAT_COOL raw4 + 2012 hvac_action + dynamic min/max, arch TIME_HHMM→sensor, a11y mdi:binary→logic-gate + heating_curve_target icon, sensor MINUTES no DURATION, number DTYPE + category POPULAR aligned, views hoisted + logged, heating_curve envelope R10/R11 + R31/R34, const DEVICE central, manifest frontend dep, panel auto-sidebar, README heating curve

## 0.3.3
- heating curve (Way B) inside integration — no Lovelace edits: auto sidebar panel "FoxAir Curve" (iframe /api/foxair/heating-curve-panel) + SVG endpoint /api/foxair/heating_curve.svg (AT -20..20 vs Flow 10..70, R10/R11 band, fixed R02 dashed, live AT dot + 2014 validation)
- Way A fixed R02 (1158) vs Way B slope (1234 0.1..3.0) + offset (1235 -5..5) + H36 enable (1236) — curve formula target=35+offset+slope*(20-AT) clamped R10/R11 & R31/R34 envelope; Zone Z kept separate (Z06/Z07 mixing, not curve)
- sensor.foxair_heating_curve_target computed from live AT 2048, exposed with panel/svg attrs; slope/offset made advanced (no expert ack) and added to POPULAR
- panel + views registered in __init__.py via hass.http + frontend.async_register_built_in_panel (awaited), views.py + heating_curve.py new

## 0.3.2
- hotfix: restore missing _load_map after dedup regression (0.3.1 coordinator had 0 _load_map -> UpdateFailed); verified 1 _load_map + get_metadata + async_write_register
- validate: py_compile all platforms, coordinator now correctly loads 573 metadata entries, climate heating/cooling verified R02 20-60 R03 7-28

## 0.3.1
- audit fixes: dedup coordinator _load_map, climate heating/cooling flows (target R02 vs R03 mode-aware RAW 0-4 DHW/Heat/Cool mapping, hvac_action from compressor freq 2072, validated writes via coordinator), const 2057 popular conflict removed, select value_map cached (75× file IO -> 1), metadata R02/R03 limits corrected to R10/R11 R08/R09 (20-60 / 7-28), build_metadata now ignores Rxx bis Ryy interdependent ranges
- optimisation: shield-alert remains for dangerous, number BOX for dangerous, slider for safe; device info centralized; translation keys preserved de/ru

## 0.3.0
- v0.3 metadata: every register now has group, editable, min/max/step, risk, platform (tools/build_metadata.py -> data/foxair_metadata.json 573 entries: 107 blocked, 197 safe, 158 advanced, 111 dangerous; 332 editable: 231 number + 75 select + 24 time)
- protection: 3-tier risk (safe/advanced/dangerous) identical to FoxAir_Control groups H/A/F/D/E/C/R/P/Z/G/SG/KG/T; sensor shows readback, number/select provide writes only when validated
- expert mode: config_flow options `enable_expert` + `expert_ack` (required) — without it, dangerous (A/C/E/F/D/H10 etc 110 regs) are not created and writes blocked; advanced (P/Z/G) are CONFIG category, dangerous are DIAGNOSTIC disabled by default
- validated writes: coordinator.async_write_register checks editable, expert ack, min/max (parsed 117 ranges from knowledge like "-40 bis 10°C"), inverse scaling, modbus FC16; out-of-range blocked and logged
- UX: box vs slider mode, shield-alert icon for dangerous, group/risk/min/max exposed as sensor attributes, options reload triggers entity re-creation
- icons: extended to number/select (231+75) with group icons
- translations: added options strings for en/de/ru + number/select keys (FoxAir_Control naming)

## 0.2.11
- RU: T-Diag1-3 popular sensors now Russian (were English fallback)

## 0.2.10
- fix translations: remaining 9 German names (SG Ready Auswahl/aktiver Modus/Schlafmodus/Leistung, Heizungsvorlauf/Raumtemperatur/AC-Spannung/DC-Bus etc.) now EN/RU

## 0.2.9
- fix CI hassfest: manifest keys sorted (domain, name, then alphabetical) - previous error: Manifest keys are not sorted correctly

## 0.2.8
- fix CI hassfest: remove invalid 'icon' from manifest (hassfest error: not a valid option at 'icon'), HACS now passes

## 0.2.7
- fix CI: hacs.json remove invalid 'hacs' key, add content_in_root; manifest add integration_type device + quality_scale custom; validate workflow ignore topics/brands until repo topics/brands PR configured

## 0.2.6
- registry review vs FoxAir_Control + modbus folder: fix scaling & units for 13 missing types (TIME_HHMM, STEPS_N, MINUTES/SECONDS/HOURS/DAYS, BITFIELD, TIMER_*, COP_X100, DIGI6/DIGI19)
- expand POLL_BLOCKS 5->7 frames to cover full 1001-1540 + 2001-2149 (was missing 20 non-BLOCK sensors: factory test 1371-1380, pump P11-P16 1432-1444, etc.)
- sensor DTYPE_MAP now covers all 30 registry types with correct device_class/unit
- TIME_HHMM now shows HH:MM string instead of raw int

## 0.2.5
- translations: entity_id stays English (foxair_{addr}), friendly names now properly localized in 3 languages
- strings.json/en.json English (source), de.json German, ru.json Russian (was German/English fallback)
- Russian: full translation for all visible/popular sensors (T, R, H, P, SG) + block headers, fallback English only for 189 diagnostic internals

## 0.2.4
- fix translations: all 573 entity names now English in strings.json/en.json (replaces remaining German like Abgastemperatur, Auslasswassertemperatur, Niederdruck, etc.)
- fix orphan devices: auto-cleanup legacy per-block devices (foxair_H, foxair_A…) left from <0.2.3 - they appeared as 11 unavailable "FoxAir Modbus Heat Pump" devices
- ru.json synced to English fallback (was German) so Russian UI no longer shows German names
- BLOCK_SHORT labels translated to English

# Changelog

## 0.2.3 - 2026-08-27
- Fix: back to 1 device (was 20 devices per block) - grouping via name prefix [R01]/[T01] like Control

## 0.2.2 - 2026-08-27
- Fix climate SyntaxError, blocking file, Modbus storm

## 0.2.1 - 2026-08-27
- Friendly names + block grouping

## 0.2.0 - 2026-08-27
- Full bulk + climate
