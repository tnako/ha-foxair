## 0.4.39 - 2026-09-01
- fix(hoas): eliminate HOAS error/warning spam — three root causes:
  - fix(const): lazy-load foxair_config.json off event loop (blocking-call warning)
  - fix(device): pre-create main device before sub-devices (via_device warning)
  - fix(poll): downgrade transient Modbus drops to DEBUG + filter duplicate pymodbus ERROR

## 0.4.38
|- fix(coordinator): "Разрешить разморозку" (Allow defrost, reg 1014) and Silent Mode On/Off (H22, reg 1030) showed "unknown" on device page after HA restart — these are binary value_map selects (DIGI1, options disabled/enabled) on the main device with `poll_tier: rare` (300/600s), so the first rare poll fires ~90s after startup; before that `coordinator.data[1014]` is empty and `select.current_option()` returns None → state renders as "unknown". Fix: the coordinator's first poll (startup catch-up) now always includes `CORE_MAIN_ADDRS` (1011/1012/1014/1030/...etc.) regardless of tier, so core control registers are populated immediately — they keep their rare tier for ongoing polling (no bus overhead). This is NOT an expert-mode issue — `requires_expert` was already false for both. Also corrected the DIGI1 generic fallback range from (0-5) to (0-1) in build_metadata.py (DIGI1 with value_map is binary; 0-5 was wrong and only affected non-value_map RAW fallback).

## 0.4.37
|- fix(timer): TIMER_BITPAIR day-of-week bitmask (KG13-KG60, addrs 1268-1270) now uses select entity with named day options ('off', 'mon', 'tue', 'weekdays_mon_fri', 'weekends_sat_sun', 'every_day_mon_sun', etc.) instead of confusing 0/1 selects. The select entity decodes the low byte of the 16-bit register and writes the selected byte to both timer slots. Fixed entity category logic in select.py to match number.py — safe-risk entities with tab codes are now visible by default.
|

## 0.4.36
|- feat(timer): KG timer start/stop (KG1-KG12 / addrs 1256-1267) now use HA `time` entity platform instead of rendering as boolean/select. New `time.py` platform converts TIME_HHMM registers (HH high-byte / MM low-byte) to proper `datetime.time` with native Lovelace time picker UI. Added `time` to `PLATFORMS` in `__init__.py`, excluded `time` platform entities from `sensor.py` to prevent duplication, and added `foxair_time_` prefix to `_cleanup_orphaned_entities`. Translations added to `strings.json` + `en/de/ru.json`.|
|
## 0.4.35
|- fix(data): hide display-firmware / unusable addresses that rendered as unbounded sliders showing bare "0" — added hidden ranges `[1015, 1015]` (Sprachauswahl / language selection, unknown value map), `[1017, 1017]` (Logo-Auswahl / logo selection, unknown value map), `[1025, 1026]` (H38/H39 display-firmware language/logo codes, value map unknown), `[1078, 1079]` (ASM Zone2 compensation params), `[1348, 1352]` (C13-E21 display-firmware parameters not visible in app) to `foxair_config.json`. Address 1016 (Silent Status bitfield) also stays hidden — the proper Silent Mode On/Off toggle is addr 1030 (H22) which is now exposed in normal mode.
|- fix(data): add min/max ranges for remaining editable number entities that lacked them — `1335` SG sleep time 0-180min, `1036` indoor unit type 0-3, `1061` fan power curve 0-2000rpm, `1204` main pump power 0-500W, `1326-1331` circulation timer HHMM 0-2359, `1332/1333` timer bitmasks 0-65535. All formerly rendered as unbounded sliders (no min/max).
|- feat(data): make Silent Mode toggle (H22 / addr 1030) visible in normal mode (not expert-only) by adding it to `CORE_NON_EXPERT_ADDRS` in `build_metadata.py` — already a proper On/Off select with value_map, was hidden behind expert gate despite being a user-facing control.
|
## 0.4.34
|- refactor(image): legend helper `_legend_item` now draws both marker and text label internally, eliminating fragile external text-offset math (was `x - label_w - 30`, now computed inside the helper from `SWATCH_W`/`LEGEND_GAP`/`LEGEND_ITEM_GAP` constants). Marker-to-text gap fixed to 1px, inter-item spacing 30px. Separator bar between line-swatch and dot-marker groups preserved. render_test.py now asserts exact 1px gap and marker types (line vs dot).
|
## 0.4.33
|- fix(coordinator): H36 AT-compensation select (reg 1236) write blocked with "out of range [1.0, 6.0]" — switching from Curve to Fixed mode failed. Root cause: `_validate_write` applied numeric min/max range checking to select entities (value_map-driven enum 0/1), which should not be range-gated. Fix: select/time platforms now skip the min/max range check entirely (they validate as Modbus words only). This also fixes the same latent bug for 7 other selects with min>0 (1020, 1024, 1032, 1041, 1046, 1069, 1236).
|- fix(data): `build_metadata.py` `parse_range` regex used `..` (any-two-chars) instead of `\.\.` (literal dots), causing false range matches on register-number-bearing descriptions — e.g. "Register 1236 = H36" parsed as range [1, 6]. This corrupted min/max for 107 addresses, silently truncating number-entity sliders (e.g. 1039 Frostschutzdiff was 0-1°C instead of 0-50°C; time HHMM entities 0-3 instead of 0-23; zone temps 0-2 instead of -30..60). Fix: regex now uses `\.\.` for literal two-dot separators. Regenerated `foxair_metadata.json` (279 entries changed across 107 addresses).
|
## 0.4.31
|- fix(image): heating curve SVG regression — restored axis tick dots at -30/-20/-10/0/10/20 (were removed in the 0.4.27 rewrite leaving only labels), fixed live-AT-label overlap with the reference cross at AT=0 and the after-compensation label (now clamped to left of dot with adaptive left/right placement), and eliminated legend right-summary collision by switching from right-aligned overflow-prone layout to a two-row legend (swatch+labels on top row, compact summary left-aligned on bottom row) with actual width estimation instead of `len()*7` heuristic.
|
## 0.4.30
- feat(privacy/safety): permanently hide reserved/system addrs — new `hidden` flag per register in `foxair_metadata.json`, ranges configured in `foxair_config.json` `hidden`. Covers protocol block headers (auto via type=BLOCK), `Reserviert`/block-header Reserve words, WiFi barcode/PHNIX ProductKey (200-215, 1001-1008), system clock (1250-1255), factory-test ASM (1361-1380), System-2/leftover ASM orphans, internal status & firmware info (2033-2149), service/OTA/board addrs (50000+). 193 registers hidden; expert view 591→398; normal mode unchanged. Hidden addrs are never created as entities (sensor/number/select), never polled (coordinator), writes are rejected, and `_cleanup_orphaned_entities` removes them from the registry in BOTH modes (previously skipped when expert=on).
- fix(modbus): write flush no longer opens a second TCP client to the EW11 — `_do_flush()` reused a fresh `AsyncModbusTcpClient` while the poll connection was live; the single-socket gateway merges both streams → `transaction_id=37 but got id=1, Skipping` / `Repeating...` frame corruption after every UI write. Writes now go through the shared poll connection under `self._lock` with 0.25 s EW11 pacing.
- fix(coordinator): dead-range filter compared str keys against int set (`k not in dead_addrs` never matched) → addr 200-215 ProductKey block was polled in expert mode → `No response received after 3 retries`. Now `int(k)`; plus poll loop aborts remaining batches on a connection-level failure and forces reconnect next cycle instead of storming a dead socket.

## 0.4.29
|- feat(devices): nicer names for the split T devices — renamed to `FoxAir — Live [T_Live]` and `FoxAir — Diagnostic [T_Diagnostic]` (dropped the redundant "Diagnostics/" prefix from the device labels).

## 0.4.28
|- feat(devices): split T Diagnostics/Live into two devices — Live (always visible, default) and Diagnostic (expert-only). Live device contains operational registers (temps, pressure, power, COP, flow, compressor freq, voltages, currents, fan speeds, energy counters); Diagnostic device contains ASM-derived values (T-Diag1-3), EVI temps (T10/T11), max driver frequency (T32), and secondary/duplicate paths (2136-2138). Diagnostic registers now have `requires_expert: true` and route to device `FoxAir — Diagnostics/Diagnostic [T_Diagnostic]` via `tab` field in metadata. Live registers route to `FoxAir — Diagnostics/Live [T_Live]`.

## 0.4.27
|- fix(climate): H36 AT-compensation enable (reg 1236) was treated as expert-only (block H in EXPERT_BLOCKS), so it was never polled in non-expert mode — `control_mode` always returned "fixed" even when set to "curve". Now 1236 is in CORE_NON_EXPERT_ADDRS, polled quick-tier, and the select entity is created/visible without expert mode.
|- fix(views): heating curve SVG legend no longer overlaps the plot — moved to a dedicated bottom strip with a dark background box, repositioned band/fixed-line/dot labels to the left side of the curve, expanded canvas from 800x400 to 800x460.
|
## 0.4.25
- refactor: introduce `foxair_config.json` as single source of truth for blocks, data types, dead ranges, functional markers, and per-register overrides — consumed by `build_metadata.py`, `const.py`, `coordinator.py`, `climate.py`, `heating_curve.py`, `sensor.py`, `views.py`, `diagnostics.py`; replaces ~60 hardcoded address constants and ~230 lines of duplicated tables in const.py/build_metadata.py.
- refactor(coordinator): DEAD_RANGES now loaded from config; `dead_ranges` config key drives batch splitting (200-215, 2029-2032) — same behavior, tunable without code changes.
- refactor(climate): replace magic address 1011/1012/1158/1159/2014/2048 with `coord.marker()` accessors (`status.power`, `status.mode`, `setpoints.heating/cooling_target`, `heat_curve.live_target`, `heat_curve.at_sensor`).
- refactor(heating_curve): use `heat_curve` marker for slope/offset/AT-sensor instead of hardcoded 1234/1235/2048.
- refactor(views/diagnostics): heating curve panel and diagnostics use marker resolution for curve addresses.
- refactor(const): DTYPE_SPEC, BLOCK_SHORT, EXPERT_BLOCKS, BLOCK_ORDER, poll intervals, modbus limits, CORE_MAIN_ADDRS all derived from foxair_config.json at import time.
- chore: bump version.

## 0.4.24
- fix(select): eliminate blocking file read in `load_value_map` — `select.py` re-read the 5770-line register JSON synchronously in `FoxSelect.__init__`, which HA 2026.8+'s blocking-call detector flagged, causing select entities (SG01 etc.) to fail setup and show "unknown". Now uses coordinator's already-async-loaded `_regmap`.
- fix(coordinator): split Modbus batches around dead/unreadable register ranges (200-215, 2029-2032) — previously read(2011, 31) spanned write-only T-Diag5-8 registers, and the EW11 bridge corrupted the batch response ("No response after 3 retries"). Now splits into non-spanning sub-batches.
- fix(metadata): mark T-Diag5-8 (2029-2032, write-only FC16) as `risk: blocked` and remove from `T_MEDIUM` poll tier in `build_metadata.py` so they are never polled.

## 0.4.23
- fix(i18n): lowercase translation keys (`foxair_s_s02`..`s10`) — HA rejects uppercase in keys
- fix(vendor): correct register 1131 comment `# E01 DIGI1` (was wrong `# E17`)
- chore(docs): remove stale v0.3 archive, fix `max_span`/`max_gap` in DEBUG.md, sync ROADMAP to 0.4.22

## 0.4.22
- fix(sensor): `NameError: name 'code' is not defined` in `_sensor_key` — 0.4.20 removed the `code = ...` assignment but kept `entity_sort_key(addr, code, block)`, so the whole sensor platform failed to set up (all ~170 sensors incl. every `T` Diagnostics entity were missing; only legacy `modbus`-platform sensors remained). Restored the assignment.

## 0.4.21
- fix(i18n): de-dup `CODE: CODE ...` double prefix (`H42: H42 Einschalt...`, `D30: D30 ...`) and add missing `T-Diag`/`H30`/`Z08`/`E03-*` prefixes — all `strings.json`/`en`/`de`/`ru` now strictly `CODE: Name` like `modbus/tabs.txt` for strong friendly-name sort; no `entity_id` change (stable).
- fix(devices): validate `T`/`O`/`S`/`ERR` still create `FoxAir — Diagnostics/Live [T]` etc via `device_for_addr` — `T`/`O` missing on the test HA host was `modbus` yaml overlap, `ha-foxair` `T` now 54 `quick+medium` polled and shown.

## 0.4.20
- fix(order): revert `0.4.19` `entity_id` (`object_id`) to `0.4.18` — keep `entity_id` stable (`dont change entity names`), only friendly names control order.
- feat(order): friendly names now `CODE: Name` prefix (`H01: Auto start`, `T02: Outlet...`) exactly like `modbus/tabs.txt` — alphabetical by friendly name == `H→A→F→D→E→R→P→G→C→Z→O→S→T` strong order; `sensor`/`number`/`select` still `sorted(..., key=entity_sort_key)` for creation order.

## 0.4.19
- feat(order): strong `entity_id` order via `entity_object_id` — `sensor`/`number`/`select` now `foxair_{block:02d}_{code:03d}_{code}_{addr:05d}` lexically == `modbus/tabs.txt` (handles `E03-1` after `E19`, `Z→O→S→T` vs alphabetical, `H→A` etc) — reinstall (delete+add) recreates `entity_id`s in strict tab order; friendly names unchanged (`Name [CODE]` suffix).

## 0.4.18
- feat(order): strict `tabs.txt` order `H→A→F→D→E→R→P→G→C→Z→O→S→T` — `BLOCK_SHORT`/`APP_TAB_TITLES` reordered, `TABS_CODE_ORDER[232]` + `entity_sort_key` in `const.py`; `sensor/number/select` now `sorted(..., key=entity_sort_key)` instead of random dict order — each menu and each entity in required order, fixes hoas random order. `FoxAir_Control` main table now also `code_sort_key` + `_register_sort_key` sorted by tabs order not numeric.
- fix(devices): `2046 T02`/`2048 T04` removed from `CORE_MAIN_ADDRS` — all `T` now strictly under device `FoxAir — Diagnostics/Live [T]` (was 2 addrs forced to MAIN for curve convenience, now 1:1 with `tabs.txt`).

## 0.4.17
- fix(ci): `entity.climate.foxair_climate.state.hvac_mode` object → flat `state.off/heat` strings (hassfest `value should be a string`).

## 0.4.16
- fix(devices): add `O` (Outputs) and `S` (Switches) per `modbus/tabs.txt` — `2034` and future `O/S` addrs no longer fall back to main device; matches `H/A/F/D/E/C/R/T/Z/G/P` + `SG/KG` layout.

## 0.4.15
- fix(H36): `1236` AT-Kompensation `1-6` → `0-1` (Nein/Ja) — `select 1236` from fixed (`0`) was rejected as out of range; same for `1046 H37`. Both now `0-1` in `foxair_metadata.json` (proven via `foxair_phnix_registers.json` value_map).

## 0.4.14
- fix(validate): allow `select`/`time`/`SG`/`Timer` without `min/max` (79 addrs had `missing limits` — e.g. `SG01`, `KG*`, `TIMER_MODE`, `TIME_HHMM`) — now permits `value_map`/`safe RAW 0-65535` instead of blocking (keeps `dangerous` RAW block).

## 0.4.13
- fix(climate): preset `Cooling` failed "1012 missing limits" — metadata has no min/max for 1012; add hard limits `1011 0-1`, `1012 0-4` bypass in `_validate_write` (also fixes `1011+1012` batch).

## 0.4.12
- fix(i18n): climate `Off/On` (`Выкл/Вкл`, `Aus/Ein`) — flat `state.off/heat` + nested `state.hvac_mode` for HA 2026.8 (was only nested, still showed "Обогрев"). Clear browser cache / reload translations after update.

## 0.4.11
- fix(climate): `hvac_modes` now shows **Off/On** (was Off/Heating) via `state.hvac_mode heat→On` translations (en/de/ru); `Off` is pure `1011=0`.
- fix(climate): presets (Heating/Cooling/…+Hot Water) via single `FC16 1011+1012` batched write — no "conflict with registry" when switching to cooling while Off.
- feat(core): 3s debounced write coalescer in coordinator (`async_write_many`) — rapid `1011+1012` / number/select changes merge into one `FC16` per contiguous block (e.g. `1011+1012` = one call), restores EW11 calm.

## 0.4.10
- fix(modbus): revert transport `modbus_connection` → `pymodbus AsyncModbusTcpClient` for polling — EW11 `extra data`/`transaction_id mismatch` makes `modbus_connection` drop `1011×2`/`2029×45` even with `message_spacing 0.22` (proven live: `pymodbus` 1011×45 ok, `modbus_connection` fail). Keep `0.22s` gap between batches (as 0.3) and tiered `poll_tier` (quick 30s 75 regs / medium 120s 42 regs / rare 300s/600s via `foxair_metadata.json`) with `pymodbus`. Config flow probe also reverted to simple `connect()` (was `read 1011,1`).

## 0.4.9
- fix(modbus): restore EW11 half-duplex gap `message_spacing=0.22s` (was 0) in `ModbusConnection` for both poll and config_flow probe — fixes `transaction_id mismatch` / `Repeating` / `No response` on EW11 that caused `1011×65` then `2029×45` failures after 0.4.0 (0.3 had `sleep 0.22` between POLL_BLOCKS).

## 0.4.8
- fix(poll): swap rare intervals — less data when non-expert → 300s (10×30s), more data when expert (352 rare) → 600s (20×30s) to keep bus calm (was vice versa 300s expert / skip non-expert).

## 0.4.7
- feat(poll): 3-tier polling (quick 30s / medium 120s / rare 300s) — 75 quick (R setpoints 1157-1243 + 1011/1012 power/mode + 1234-1236 curve + T primary 2045/2046/AT/flow/power/COP 2054/2059/2060/2077 + 2013/2014 curve) / 42 medium (T secondary EVI/pressures/fan + Z targets + P10 + KWH) / 352 rare (H/A/C/F/D/E/Z/G/P/SG/KG/ERR) — `poll_tier` in `foxair_metadata.json` for easy tuning, expert `rare` only if `enable_expert` (saves ~18 batches when off). First poll quick+medium only (117 regs, 13 batches) to avoid EW11 overload; write stays optimistic 0.35s + verify.
- fix: `max_span 45` kept (65→45 in 0.4.6) + tiered cuts avg bus from ~31 batches/30s to ~8/30s (quick) + 5/120s + 18/300s.

## 0.4.6
- fix(modbus): EW11 gateway drops large reads — `read_holding_registers(1011,65)` → `Modbus Error: No response` then `1346,13` transaction_id mismatch (your log). `max_span 65→45, max_gap 12→8` (live tested EW11-host:8899: 65/60 fail, 55/45/30 ok). Reduces per-request words and fragmentation; pooled reads now align with pre-0.4 `POLL_BLOCKS` 45-60 sizes.

## 0.4.5
- fix(config_flow): connectivity `cannot_connect` after 0.4 migration — Modbus read timeout 3s→5s + TCP fallback (raw `open_connection`) restoring pre-0.4 `connect()` behavior; fixes false negatives when gateway accepts TCP but register 1011 read races
- fix(config_flow): slave ID (and port) were slider due to `vol.Range` — now plain `int` number box with manual 1-247 / 1-65535 validation; shows `Slave ID = 1` as expected
- fix(i18n): restore `enable_expert` friendly text in setup (was raw `enable_expert` key) — add `config.user.data.enable_expert` + `config.user.description {warn}` + `config.error.cannot_connect/need_ack` in strings/en/de/ru (EN/DE/RU localized); options `need_ack` also localized

## 0.4.4
- chore(repo): audit and clean leftovers — update README/docs to 0.4.3, archive v0.3 reviews, validate tools, update data/README
  - README 0.4.3 (591 regs, pooled reads, humidity/energy, vendor, curve panel, HA ≥2026.3) replacing outdated 0.4 roadmap blurb
  - docs/ROADMAP 0.4.3 current + 0.5 plan (HA 2026.9 shared bus)
  - archive `ARCHITECTURE_REVIEW.md`/`SECURITY_REVIEW.md` v0.3 → `docs/archive/*_v0.3.md` + archive README (outdated POLL_BLOCKS/573 counts)
  - tools kept: `build_metadata`+`gen_foxair_modbus` core, `fix_translations` maintenance — added `tools/README.md` with run command; `modbus/tabs.txt` header; `data/README` 591 table; `hacs.json` 2024.1→2026.3, `info.md` expanded; `icons.json`+`brand/` duplication kept intentionally (HACS vs HA runtime)

## 0.4.3
- chore(i18n): reorder translations by numeric key (2127→2136→2178→50043→50500) — fixes 50043-50512 inserted between 2128 and 2136; sort all entity domains (sensor/number/select) numerically, non-numeric (cop etc) after; update fix_translations generator to sort on save

## 0.4.2
- i18n: validate & fix translations — English default everywhere, no German leak
  - added 18 missing sensors (2178-2180 humidity/dewpoint, 50043-50512 C37B/C544, productkey 200-215 updated) + 3 computed (heating_power/electrical_power/cop) to strings.json; strings↔en now 1:1 (595 sensor, 231 number, 86 select) with English default
  - fixed German leak in en: Block Header Packet 3-8 (1181-1190,1271-1278,1361-1368,1451-1458,1547-1548,2001-2008,2091-2098) were still German; also 50501-50512 Hardwarecode etc; 2125-2128 & 2136-2138 outdated candidate/Reserved now DHW energy & T04/power
  - de/ru completeness: 0 missing keys vs en; de German, ru Russian (Cyrillic) for popular, English fallback for diagnostics as before; switch foxair_power added to all
  - edge: de/ru block headers now correct (German vs English fallback for ru diagnostics), all select states verified

## 0.4.1
- sync: registers/knowledge from FoxAir_Control 0.2.62 (up to 5607b5a) — 18 new, 300+ corrections
  - new read-only diagnostics: humidity sensor 2178 (°C), relative humidity 2179 (% rF), dewpoint 2180 (°C); DHW energy 32-bit counters 2125-2128 (electric/thermal high/low); T04 second path 2136, WP power 2137/2138 without booster
  - corrected: 2057 AC Input Current, 2071 compressor setpoint freq (2072 is actual), 2109 internal status, 2125-2128 naming, 2136-2138 vs placeholder
  - relabeled: 200-215 from BLOCK to PHNIX/Aliyun ProductKey ASCII (privacy — excluded from HA poll, not polled), 50500-50512 C544 board info + 50043-50044 C37B OTA status (excluded from poll — direct Modbus only), SG Ready 1334 virtual mode 8801 documented in knowledge (10-min hold)
  - cleanup: removed empty `tab:""` (256 entries) and per-code `tab:"H"/"A"` noise, fixed WiFi barcode serial WF2210250475→WF2403150123 in knowledge, sensor DTYPE for U16/ASCII
- vendor: foxair_modbus regenerated 469 fields (+3 humidity, product/service ranges excluded from poll), metadata 574→591 entries, diagnostics group for new T sensors

## 0.4.0
- feat(modbus): migrate to pip `modbus-connection` model via vendored `foxair-modbus` (HA ≥2026.3). Own `ModbusConnection(ModbusTcpParams)` via `modbus_connection.pymodbus` — no 2026.9 required.
- feat(lib): new standalone `foxair-modbus` vendor — single source from `foxair_phnix_registers.json`, 466 `Component` fields (`gauge`/`integer`), pooled reads via `max_span=65`/`max_gap=12` (one per space vs 12 `POLL_BLOCKS`).
- perf: pooled reads (fewer Modbus round-trips, lower bridge load) via `Component.async_update()`.
- refactor: coordinator owns `ModbusUnit` (not `AsyncModbusTcpClient`), drops manual `POLL_BLOCKS`/`scaled()`/`_lock` connect logic (~40% slimmer); config_flow probes via owned `ModbusConnection`; `__init__.py` lifecycle `await conn.close()` on unload.
- fix: retains 0.3.45 500 fix + 0.3.46 climate On/Off + i18n.
- note: v0.5 will switch to HA-bundled `modbus-connection` and require 2026.9, dropping pip install.

## 0.3.46
- fix(climate): hvac is now pure On/Off — `hvac_modes=[Off, Heat]` where Heat means On (1011=1, 1012 kept). Presets are the 4 DHW combos: `Heating` (1), `Cooling` (2), `Heating + Hot Water` (3), `Cooling + Hot Water` (4). `Hot Water only` (0) is legacy read-only mapped to Heating+Hot Water and not selectable. `async_set_hvac_mode` Off writes 1011=0, On writes 1011=1 (0->defaults to Heating). `async_set_preset_mode` powers on and writes 1012. No more Heating-vs-Cooling conflict between mode and preset.
- fix(i18n): add missing `elec_source`/`external_meter_entity`/`v_gain`/`v_offset`/`i_gain`/`i_offset` translations to `en`/`ru`/`de` so Options shows friendly labels instead of raw `elec_source`.

## 0.3.45
- fix(config_flow): fix 500 on Options flow — HA cannot convert `vol.Any(In(...), "")` to UI schema. Reverted to plain `vol.In` / `vol.Coerce(float)` validators (all power fields stay `Optional` with defaults) so enabling Expert with just the ack works and the form loads.

## 0.3.44
- fix(config_flow): COP calibration no longer blocks Expert mode — all power fields (`elec_source`, `external_meter_entity`, `v_gain`/`v_offset`/`i_gain`/`i_offset`) are now truly optional with permissive validators (`vol.Any` + empty-string allowed) and empty values keep existing/defaults. `expert_ack` is Optional, `elec_source` defaults to `foxair_register` (no calibration). Enabling expert with just the ack now succeeds.
- i18n: added missing options strings for the 6 power fields so they show as optional in the UI.

## 0.3.43
- fix(climate): On/Off is now a proper climate mode (`hvac_modes=[Off, Heat, Cool]` via reg 1011) instead of a separate boolean switch. `switch.foxair_power` removed from PLATFORMS — power is controlled via the climate card. `async_set_hvac_mode` now writes 1011 for Off and 1011+1012 (preserving DHW bit) for Heat/Cool.
- fix(climate): preset friendly names — `Hot Water only`, `Heating`, `Heating + Hot Water`, `Cooling`, `Cooling + Hot Water` (raw 0..4). Display, attributes and setters all use the same names.
- fix(config_flow): COP calibration no longer mandatory for Expert mode — `elec_source` is now `Optional` (defaults to `foxair_register`, no calibration). All COP fields keep defaults and existing options are merged, not discarded, when expert is toggled.

## 0.3.42
- fix: removed the phantom `computed` platform that broke integration load ("Setup failed for 'computed': Integration not found"). The heating-power / electrical-power / COP sensors now live on the standard `sensor` platform (moved into sensor.py). `computed.py` deleted.
- note: `foxair_heating_power` / `foxair_electrical_power` / `foxair_cop` keep the same unique_ids as the old YAML template sensors — once the old modbus/template block is removed from configuration.yaml the new integration versions take over the same entity_ids (continuous InfluxDB history). Until then the old template sensors win the duplicate-id.

## 0.3.41
- fix(climate): AT-compensation target now reads the heat pump's own computed curve target (reg 2014, "Temperaturwert nach Wetterkompensation") — exact parity with the vendor app (was off by a constant ~0.8°C from the linear offset/slope recompute). Formula retained as fallback.
- fix(climate): separated On/Off from the mode selector. The climate card is now purely the operation-mode selector (Heat / Cool / HeatCool + DHW presets); power On/Off lives exclusively on the separate `switch.foxair_power` (reg 1011). Setting a mode no longer toggles power.

## 0.3.40
- feat: computed (derived) sensors — `foxair_heating_power`, `foxair_electrical_power`, `foxair_cop`.
  - Heating power = (flow/3600)·ρ·cp·ΔT from registers 2077/2045/2046, with an EMA flow smoother + "hold-last-good" guard for the flaky water-flow sensor and forced zero when the compressor is off.
  - Electrical-power source for COP is configurable in Options: FoxAir Unit Power register 2054 (default, accurate, no calibration), V×A (2062×2057) with tunable gain/offset, or an external HA power-meter entity.
  - COP = heating_power / electrical_power, guarded against standby/garbage values.

## 0.3.39
- feat: optimistic UI updates for toggles/mode changes — Power switch (1011), climate hvac_mode, and climate preset_mode now flip instantly on tap instead of waiting for the Modbus round-trip. Failed writes roll back; coordinator read-back/poll reconciles to the real device value.

## 0.3.38
- feat: separate Power switch (switch.foxair_power, reg 1011) so On/Off is no longer bundled into the climate mode selector.
- fix(climate): target temperature is now shown in AT-compensation (weather-curve) mode — pinned to the live curve value (offset − slope·AT) with min==max so the slider is visible but locked (target is derived, not directly settable). Fixed setpoint still editable in fixed mode.

## 0.3.37
- fix(climate): in AT-compensation (weather-curve) mode (H36 / reg 1236 = 1) the climate card now shows the computed curve target (offset − slope·AT, reg 2048) instead of the fixed setpoint register. The target-temperature slider is hidden in curve mode (PRESET_MODE stays to switch modes); setting temp directly in curve mode is rejected with a hint to tune slope/offset. Fixed setpoint still shown only in fixed mode.

## 0.3.36
- fix: add repository-root `brand/` directory (icon.png + @2x, logo) so the HACS store card shows the integration icon. The inner `custom_components/foxair/brand/` feeds HA's local /api/brands; HACS store listing needs the root-level `brand/` (see HACS issue #5171).

## 0.3.35
- feat: optimistic UI updates for number + select writes — slider/mode shows the new value instantly on release instead of waiting for the Modbus round-trip (can be ~1-2s). Failed writes roll back; coordinator read-back/poll reconciles to the real device value.

## 0.3.34
- feat: heating-curve image — labelled data points every 10 °C (−30,−20,−10,0,10,20) showing the flow value on the curve. AT=0 already covered by the anchor cross; right-edge label kept inside the plot.

## 0.3.33
- fix: slope (1234) slider range now 0..3.5 (was 0..100 — raw DIGI5 range shown unscaled). Added RANGE_OVERRIDES in build_metadata; DIGI5 generic fallback corrected to displayed 0..10.

## 0.3.32
- feat: heating-curve image — add reference cross at design point (AT=0 → flow=offset), so it's clear the curve is anchored at 0 °C outside = offset flow. Dashed vertical (AT=0) + horizontal (offset) lines, labeled dot, and the AT=0 x-axis tick now reads "0°→37°".

## 0.3.31
- fix: heating-curve formula — reference point is AT = 0, not AT = 20. Correct formula `flow(AT) = offset - slope·AT` (offset = flow at 0 °C outside temp). Previous `offset + slope·(20-AT)` drew the line ~6 °C too high. Verified against reference points -30:46 … 20:31.

## 0.3.30
- fix: add `mdi:heat-pump` icon fallback on all entities (climate/sensor/number/select) so they render an icon even if `brand/` PNG is unavailable (manifest `icon` key stays removed — invalid in HA schema, breaks CI)

## 0.3.29
- fix: remove invalid `icon` key from manifest.json (HA manifest schema rejects it; CI "Invalid manifest" error). In-HA icon is served from `brand/`; HACS card icon remains a known HACS limitation (issue #5171)

## 0.3.28
- feat: offer "Enable expert mode" boolean during first integration setup (config flow) and carry it into entry options so advanced/dangerous parameters are exposed immediately; also available in Options

## 0.3.27
- fix: restore heating-curve controls on main device — 1234 (slope), 1235 (offset), 1236 (H36 fixed/AT-compensation) and R02/R10/R11 (target/min/max water temp) are now `safe` and not expert-gated, so they appear without enabling expert mode (regression from expert-gate added after 0.3.9)

## 0.3.26
- fix: HACS store icon — add `"icon": "mdi:heat-pump"` to manifest.json (HACS reads manifest icon for the repository card); remove ineffective `/foxair/brand` static-path registration (HA 2026.3 serves brand/ PNGs automatically via local brands API)

## 0.3.25
- fix: heating curve image now always draws a line — AT-compensation curve (blue, clamped to R10/R11) when H36=1, constant line at R02 (amber) when H36=0, faint curve preview in fixed mode; slope normalized and offset respected; standalone SVG view aligned

## 0.3.24
- fix: align register tab assignments with official app split (H/A/F/D/E/R/P/G/C/Z/O/S/T); added authoritative `modbus/tabs.txt` from official app docs; regenerated `foxair_metadata.json` so device pages and entity grouping match official UI

## 0.3.23
- fix: serve local brand assets from integration via `/foxair/brand` so device icon/logo load even if HACS frontend resource cache or CDN brand lookup fails

## 0.3.22
- fix: heating curve image renders as sharp SVG instead of raster PNG; redraws only when curve values change (slope/offset/mode/AT/fixed/after-comp/R10/R11) and shows a placeholder when data is missing

## 0.3.21
- fix: improve register grouping to match official app tab split (H/A/F/D/E/R/P/G/C/Z/O/S/T) — entities now organized by app tabs instead of legacy block-only grouping; metadata and device names updated accordingly

## 0.3.20
- fix: image curve now -30..+20 step 10° (was -20..+20), minor grid 5° retained. Curve drawn -30..+20 with 0.5° smoothness. Fixed R02 dashed now only when H36=0 (fixed mode); in curve mode (H36=1) only blue curve shows per user report 'you draw only fixed while mode = curve'.

## 0.3.19
- fix: revert 0.3.18 light theme — bad photo match. Restore dark #0f172a 1200×720 with muted blue 96,165,250, dark fill, dark label boxes. Keep larger size so device page shows not icon but bigger image near slope/offset (crisp when expanded).

## 0.3.18
- feat: light-theme 1200×720 heating curve image — white bg, grey major/minor grid, blue 4px curve with light-blue fill, orange dashed fixed R02, red live dot with halo+label box, larger fonts via DejaVuSans, crisp on device page near slope/offset controls.

## 0.3.17
- feat: fast write cycle — after FC16, 350ms single-register read-back on ephemeral client patches coordinator.data + async_update_listeners (≈0.8s UI update) instead of waiting 30s full poll. Background full refresh still scheduled.

## 0.3.16
- fix: slope write still reverting after FC16 — use ephemeral write client (poll client polluted by Elfin broadcast extra data) + 600ms post-write refresh. Live-tested 0.22s gap reduces but not eliminates desync; write isolation fixes persistence.

## 0.3.14
- fix: slope/offset writes not persisting — switch FC06 write_register to FC16 write_registers (FoxAir_Control core uses FC16 build_write_frame) + 120ms inter-block poll delay to fix Elfin EW11 transaction_id desync (read stale / pdu without request)

## 0.3.13
- feat: image.foxair_heating_curve on FoxAir Heat Pump device — live heating curve PNG via PIL (no YAML/Lovelace) — AT vs Flow, slope 1234 offset 1235 R10/R11 clamp, fixed R02, current AT dot from 2048/2014, auto-refresh on coordinator

## 0.3.12
- fix: icon 403 brands CDN fallback — rebuild local brand icons (icon.svg → brand/icon.png 256 + icon@2x 512 etc via cairosvg) per HA 2026.3 docs https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api — local /api/brands/integration/foxair/icon.png now serves icon on Integrations/devices pages (HACS dashboard still via data-v2.hacs.xyz until hacs/integration#5171 merges fallback)

## 0.3.11
- fix: AT Compensation Slope/Offset show unknown — poll 1126×125 truncated by Elfin bridge to 90 regs so 1234 sat at offset 108 outside reply; split POLL_BLOCKS to 60/65 (12 blocks) so 1234-1236 now via 1186×65
- fix: Offset 37.0 exceeded old -5..5 limit — widen 1235 to -30..70°C (live raw 370 → 37.0) so number shows value; slope 0.3 (raw 3, DIGI5/10) already in 0.1..3.0

## 0.3.10
- i18n: fix Timer (KG) German-only — 1256-1270 WP Ein/Aus Timer Startzeit/Stopzeit and Aktiv/Tage Bitmaske now HP On/Off Timer Start/End and Active/Days Bitmask in en (de keeps WP Ein/Aus), ru transliteration; sensor/select duplicate for TIMER_BITPAIR already hidden via sensor dedup

## 0.3.9
- ux: surface heating curve on Main Heat Pump — 1234 Slope (K) 0.1-3.0 and 1235 Offset (B) -5..5°C and 1236 Mode fixed/curve now on FoxAir Heat Pump device as normal controls (was hidden as AT Compensation under config)
- rename 1234/1235 to Heating Curve Slope/Offset and 1236 to Heating Curve Mode with fixed vs Weather compensation (was No/Yes), plus Heating Curve Target sensor name fix; 1236 select now fixed/curve slugs matching translations

## 0.3.8
- chore: remove versioned code comments added in 0.3.7 (no functional change, same per-block devices + dedup)

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
