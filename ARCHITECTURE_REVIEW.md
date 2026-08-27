# Architecture Review — ha-foxair

**Scope:** `custom_components/foxair/` (12 Python files, 4 data JSON files, `tools/build_metadata.py`).  
**Data flow:** Modbus TCP → `FoxAirCoordinator` → HA entities (sensor/climate/number/select) + HTTP views.

---

## 1. Dependencies

| Concern | Finding |
|---|---|
| `manifest.json` `dependencies` | **Empty** — declares no HA-side dependencies, but implicitly needs `http` (views) and relies on `config_entries`. Works because HA loads `http` implicitly, but is fragile. |
| External | `pymodbus>=3.6.0` — declared correctly. |
| Internal modules | `heating_curve.py` is imported lazily (inside method bodies) by `views.py` and `sensor.py` to dodge circular imports. `const.py` is imported by `__init__.py`, `coordinator.py`, `sensor.py`, `number.py`, `select.py`, `config_flow.py`. `coordinator` imports only `const`. |

**Issue:** `heating_curve.py` reaches directly into coordinator internals (`coord.data`) instead of exposing a method on the coordinator. This inverts the dependency: the helper module (low level) depends on the coordinator's data shape (high level) rather than the coordinator depending on the helper.

---

## 2. PLATFORMS — declared vs. classified mismatch (BUG)

`__init__.py` declares:
```python
PLATFORMS = ["sensor", "climate", "number", "select"]
```

But `tools/build_metadata.py` `TYPE_TO_PLATFORM` classifies registers into **5** buckets. Verified against the generated `foxair_metadata.json` (573 entries):

| platform | metadata count | in PLATFORMS? |
|---|---|---|
| sensor | 243 | ✅ |
| number | 231 | ✅ |
| select | 75 | ✅ |
| **time** | **24** | ❌ **orphaned** |
| (climate) | 0 (hand-coded) | ✅ |

**The 24 `TIME_HHMM`-type registers are classified as `time` platform, which is never set up → those entities are silently never created.** `time` platform support (TimeEntity) is trivially addable, but the omission means 24 editable schedule/timer registers (e.g. H36 heating-curve enable is DIGI1/select — covered) but timer-mode registers typed `TIME_HHMM` are dropped entirely.

---

## 3. Data flow: Modbus → coordinator → entities → views

### 3.1 Modbus → Coordinator
`coordinator.py:_async_update_data()` polls `POLL_BLOCKS` (7 bulk read frames covering 1001–1540 & 2001–2149) via `client.read_holding_registers`. For each register it:
1. Looks up `self._regmap` (`foxair_phnix_registers.json`) for the record's `type`/`code`/`block`.
2. Calls `scaled(type, raw)` → stores `{"raw", "value", "info"}` in `self.data[addr]`.
3. Skips `BLOCK`-type registers.

This is correct and follows the HA `DataUpdateCoordinator` pattern — entities get push updates on each 30 s poll.

### 3.2 Coordinator → entities

There is an **asymmetric entity-creation strategy** across platforms:

| Platform | Source of truth for "which entities exist" | Filter |
|---|---|---|
| **sensor.py** | iterates **`coord.data`** (live-poll results) | skip `BLOCK` type, skip `risk==blocked` |
| **number.py** | iterates **`coord._metadata`** (the *full* metadata file) | `platform=="number"` + `editable` + expert gate |
| **select.py** | iterates **`coord._metadata`** (the metadata file) | `platform=="select"` + `editable` + expert gate |
| **climate.py** | hardcoded single entity | n/a |

**Problems this creates:**
- Registers outside the poll range (addresses not in 1001–1540 / 2001–2149) **never appear as sensors** even if they exist in metadata, because sensor creation iterates live `coord.data`, not metadata. Conversely, `number`/`select` iterate the *full* metadata, so an editable register that isn't polled will produce an entity whose `native_value` returns `None` forever (no live data ever arrives).
- sensor.py does **not** respect `requires_expert` — it creates *all* non-blocked sensor entities and relies solely on `EntityCategory`/`enabled_default` to hide them. number.py and select.py gate dangerous ones entirely behind the expert option. **Behavioral inconsistency**: dangerous sensors always exist (just disabled); dangerous numbers/selects are gated.

### 3.3 Sensor → views
The HTTP views (`views.py`) **do not go through entities at all**. Both `FoxAirCurveSvgView` and `FoxAirCurvePanelView` open `hass.data["foxair"]` → coordinator → reach into `coord.data.get(addr)` directly. This duplicates, verbatim or near-verbatim, the same address lookups that `FoxHeatingCurveTargetSensor` (in `sensor.py`) also performs:

| address | meaning | used in |
|---|---|---|
| 2048 | AT (outdoor temp) | views.py ×2, sensor.py, heating_curve.py |
| 1234 | slope | views.py ×2, sensor.py, heating_curve.py |
| 1235 | offset | views.py ×2, sensor.py, heating_curve.py |
| 1236 | H36 enable | views.py×1, sensor.py |
| 1158 | fixed R02 | views.py ×2, sensor.py, climate.py |
| 2014 | after-comp target | views.py ×2, sensor.py |
| 1164/1165/1169/1172 | R10/R11/R31/R34 limits | views.py ×2 |

**The heating-curve data-access logic is triplicated** across two views, the sensor entity, and the helper. There is no single source for "what registers define the heating curve."

---

## 4. Coupling analysis

| Boundary | Coupling | Notes |
|---|---|---|
| `views.py ↔ coordinator` | **Tight (data-shape)** | Views read `coord.data[addr]["value"]` directly, knowing the internal dict structure (`{"value", "raw", "info"}`). |
| `sensor.py ↔ coordinator` | **Tight (data-shape)** | Same direct dict access via `rec["value"]`, `rec["raw"]`, `info.get("type")`. The `FoxSensor` constructor even reaches into `rec.get("info", {})` from `coord.data`. |
| `heating_curve.py ↔ coordinator` | **Tight (data-shape)** | Helper functions take `coord` and poke `coord.data.get(addr).get("value")`. Inverted dependency — low-level math knows the high-level object layout. |
| `coordinator ↔ const` | Clean | Only imports `POLL_BLOCKS`. (Does *not* use `POPULAR_ADDRS`, `BLOCK_SHORT`.) |
| entities ↔ `const` | Loose | sensor.py uses `POPULAR_ADDRS`; others don't. |
| `__init__.py ↔ views/coordinator/const` | Clean (constructor-style) | Good: registers views, builds coordinator, forwards platforms. |

**Verdict:** The lower layers (views, helpers, entities) reach *upward* into the coordinator's raw dict, rather than the coordinator exposing a stable query API. This makes the `data` dict shape a de-facto public interface with no encapsulation guard.

---

## 5. Single-responsibility violations

### coordinator.py
Mixes three responsibilities in one class:
1. **Polling** (`_async_update_data`: modbus reads, stats).
2. **Decoding/scaling** (module-level `scaled()`, `s16()` — pure functions that don't belong on the coordinator, but at least are module-level).
3. **Write validation + execution** (`async_write_register`: min/max, expert guard, dtype→raw conversion, actual modbus write).

`async_write_register` re-implements the inverse of `scaled()` in a separate giant if/elif chain — same dtype list, opposite direction. This is the same conversion logic living in two places with no shared table.

### views.py
Mixes four responsibilities: HTTP view scaffolding, coordinator lookup, heating-curve computation, and SVG/HTML string rendering (the SVG is ~80 lines of inline f-string). The slope-normalization heuristic (`if slope > 5: slope = slope/10`) appears here *and* in `heating_curve.curve_target_for_at` — duplicated business rule.

### number.py / select.py (each)
Their `async_setup_entry` mixes entity-discovery (metadata iteration + filtering) with entity construction. The metadata-guard (`if not getattr(coord, "_metadata", None): await coord._load_map()`) appears in **three** files (sensor, number, select).

### _cleanup_orphaned_devices (__init__.py)
A version-migration concern fired via `hass.async_create_task` (fire-and-forget, swallowed exceptions — line 20-21 `except: pass`). Fine as a one-off, but the silent swallow means migration failures are invisible.

---

## 6. DRY violations (concrete)

1. **`DEVICE` DeviceInfo** — identical 1-line dict copy-pasted in `sensor.py`, `number.py`, `select.py` (verified: 3 hits). Could live in `const.py`.
2. **Metadata-load guard** — `if not getattr(coord, "_metadata", None): await coord._load_map()` in sensor.py:49, number.py:24, select.py:25.
3. **Entity-discovery loop** — number.py:27-37 and select.py:27-37 are near-verbatim (iterate metadata, parse addr, filter platform+editable+expert).
4. **Risk → EntityCategory mapping** — reimplemented independently in all 3 platforms with subtly different thresholds:
   - sensor.py: `blocked`→DIAGNOSTIC+disabled; `dangerous`→DIAGNOSTIC+(enabled if in POPULAR); `advanced`→CONFIG; else→enabled.
   - number.py: `dangerous`→CONFIG+disabled; `advanced`→CONFIG; else→enabled. ⚠️ **sensor marks `dangerous` as DIAGNOSTIC, number marks it as CONFIG** — inconsistency.
   - select.py: same as number.py.
5. **Dtype ↔ scale factor** — `scaled()` (coordinator, ~15 dtype entries) vs the inverse in `async_write_register()` (~13 dtype entries, not kept in sync).
6. **Heating-curve address lookups** — the 2048/1234/1235/1236/1158/2014/1164-1172 set is duplicated across views.py (2 places), sensor.py, heating_curve.py.
7. **`BLOCK_SHORT`** dict — defined identically in `const.py` (lines 3-18) AND `tools/build_metadata.py` (lines 14-29). The build tool should import from `const` but doesn't.
8. **Slope normalization** — `if slope > 5: slope = slope / 10` in both `views.py:37` and `heating_curve.py:37`.

---

## 7. Other structural issues

- **Bare `except:` clauses** (16 occurrences) — found in `__init__.py:20,28,62`; `coordinator.py` none but `config_flow.py:16`; `views.py:50,133`; `select.py:21,30,81,88`; `number.py:30,78`; `heating_curve.py:15,49`; `sensor.py:86,115,137,150`. These swallow errors silently — a read failure or JSON parse problem becomes invisible in production. Should be `except Exception:` at minimum, with logging.
- **Dead data file**: `data/foxair_phnix_display_registers.json` is copied into the package but **never imported** by any Python (confirmed: only referenced in `data/README.md`). 33 KB of dead weight.
- **`hasattr(coord, "get_metadata")` guards** — in sensor.py:56,58,85 and climate.py:31,32 — defensive checks for a method that always exists on the coordinator. They obscure real AttributeError bugs.
- **Magic address numbers** — climate.py hardcodes 1011/1012/1158/1159/2046/2072 as bare integers. views.py/heating_curve.py hardcode 2048/1234/1235/1236/1158/2014/1164/1165/1169/1172. None of these live in `const.py` as named constants. A single `ADDRESSES` table in const would eliminate ~30 magic numbers.
- **`s16()` signedness** — handles 16-bit but the signed→unsigned write conversion (coordinator:116-118) manually masks with `& 0xFFFF`. Consistent but could share a single `to_u16`/`from_u16` helper.
- **`scaled()` falls through** — dtype values not in any explicit branch silently return `float(sv)` (the catch-all on line 48). Low risk but unlogged.

---

## 8. Architectural strengths (positive)

1. **Correct HA integration pattern**: `DataUpdateCoordinator` + `CoordinatorEntity` — entities auto-update on each poll, no manual subscription spaghetti.
2. **Metadata-driven entity generation**: `build_metadata.py` produces a rich metadata file (editable, min/max, risk, platform, group, icon, value_map presence) consumed by number/select. Data-driven, not hardcoded.
3. **Thoughtful risk-tiering system**: `safe / advanced / dangerous / blocked` with per-address overrides (e.g. 1024 "bricks bus") — genuinely valuable for a heat-pump Modbus integration where wrong writes are destructive.
4. **Expert-mode gating** via config options flow with a required acknowledgment checkbox — good safety UX.
5. **Lazy imports** of `heating_curve` inside methods avoid circular imports cleanly.
6. **Self-registering sidebar panel** (iframe) — zero Lovelace config required by the user.

---

## 9. Prioritized recommendations

| Priority | Recommendation | Effort |
|---|---|---|
| **P1** | **Add `"time"` to `PLATFORMS`** — or reclassify the 24 `TIME_HHMM` registers into `select`/`number` if TimeEntity isn't desired. As-is they're dead. | S |
| **P1** | **Extract heating-curve registers into named constants** in `const.py` (AT_ADDR, SLOPE_ADDR, OFFSET_ADDR, etc.) and use them in all 3 call sites. | S |
| **P1** | **Move `DEVICE` to `const.py`** and import. | S |
| **P2** | **Unify the metadata-load guard + entity-discovery loop** into one helper (e.g. `_iter_editable_entities(coord, entry, platform)`) shared by number.py/select.py. | M |
| **P2** | **Add a coordinator query API** (e.g. `coord.get_value(addr)`, `coord.get_raw(addr)`) so views/helpers/entities don't reach into `data[addr]["value"]` dict internals. | M |
| **P2** | **Fix the risk→category inconsistency**: sensor marks `dangerous` as DIAGNOSTIC, number/select mark it as CONFIG. Pick one. | S |
| **P2** | **Replace bare `except:` with `except Exception:` + logging** across all files. | S |
| **P3** | **Unify dtype↔scale table** — one `SCALING` dict of (dtype → divisor) consumed by both `scaled()` and `async_write_register()`. | M |
| **P3** | **Unify the heating-curve computation** — have `heating_curve.curve_target_for_at` own the slope normalization, and have both views and the sensor entity call it (views already do for the SVG target, but the slope-normalization duplicate and the panel view's inline reimplementation remain). | M |
| **P3** | **Make `tools/build_metadata.py` import `BLOCK_SHORT` from `const`** instead of duplicating it. | S |
| **P3** | **Remove or use `foxair_phnix_display_registers.json`** — currently dead. | S |
| **P3** | **Make `_cleanup_orphaned_devices` observable** — don't swallow its exceptions silently (or at least log). | S |
