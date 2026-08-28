# Security Review — ha-foxair v0.3.3

Scope: `coordinator.py` (`async_write_register`), `config_flow.py` (options/expert flow),
`number.py`, `select.py`, `climate.py`, `views.py`, metadata (`build_metadata.py` +
`foxair_metadata.json`). Focus: expert guard, input validation, min/max enforcement,
write protection, dangerous registers, injection risks, auth on HTTP views.

---

## Summary of findings

| # | Severity | Area | Issue |
|---|----------|------|-------|
| 1 | **High (functional + safety)** | `coordinator.py` × `build_metadata.py` | `parse_range("0-0FF/1-EIN")` returns `min=max=0.0`. Breaks ON writes and creates a degenerate guard. |
| 2 | **High (writes unbounded)** | `foxair_metadata.json` | 59 registers (7 dangerous + 52 advanced) have `min=None/max=None`. Once expert mode is on, `async_write_register` range-checks are skipped entirely → raw u16 values 0–65535 accepted. |
| 3 | **Medium** | `config_flow.py` | Expert gate is a one-time acknowledgement checkbox; no admin/owner restriction, and `requires_auth` is the only protection. Any HA user with config access can enable expert mode. |
| 4 | **Medium** | `climate.py` | `async_set_hvac_mode` writes 1011/1012 directly (not via user input, so not injectable) but the ON path is dead due to #1; also writes bypass the per-entity min/max UI affordances. |
| 5 | **Low** | `select.py` / `number.py` | `int(option)` / `float(value)` conversions can raise ungracefully if upstream sends unexpected data; errors are surfaced as `ValueError` to HA (acceptable) but not rate-limited. |
| 6 | **Low** | `views.py` | `requires_auth = True` is correct; views are read-only and build SVG/HTML from live float values (no user input) → **no injection vector**. `at` is interpolated into the `<img src=...?v={at}>` only as a stringified float; safe. |
| 7 | **Info / positive** | `coordinator.py` | Editable gate, expert gate, `asyncio.Lock` on writes, signed→u16 masking, and refresh-after-write are all present and correct. Dangerous registers are categorized `DIAGNOSTIC` + disabled-by-default. Diagnostics view contains no secrets. |

---

## Detail

### 1. Degenerate min/max from `parse_range` (HIGH)
`build_metadata.py:83` `parse_range` uses the regex
`(-?\d+...)\s*(?:bis|..|–|—|-)\s*(-?\d+...)` against the description string.
For register 1011 the knowledge description is `"0-0FF/1-EIN"`. The regex matches the
leading `0-0` (of `0FF`), producing `lo=0.0, hi=0.0`. Result in metadata:

```json
"1011": { "editable": true, "risk": "advanced", "requires_expert": true,
          "min": 0.0, "max": 0.0, "type": "DIGI1" }
```
`async_write_register` checks `lo - 1e-9 <= value <= hi + 1e-9` with `lo==hi==0`, so **only
value `0` passes**. Consequences:
- The climate entity's "turn ON" (`async_write_register(1011, 1)`) is **always rejected**.
  `async_set_hvac_mode(OFF)` works (writes 0); every other mode fails.
- Register 1031 (A35, `risk=dangerous`) also has `min=max=0.0` (description "Temperaturdifferenz …"),
  making it effectively read-only / broken too.
- A degenerate `min==max` range is also semantically wrong as a safety clamp.

Fix: anchor the regex (require digit boundaries, e.g. `^[\D]*(-?\d+...)...(-?\d+...)$`),
reject ranges where `lo==hi` unless the source truly is a single-value enum, and add a
post-parse sanity check (`if lo==hi and dtype not in enum: lo=fallback`). Better: source
ON/OFF limits from `value_map` keys (0,1) rather than free-text parsing.

### 2. Unbounded writes when expert mode enabled (HIGH)
`async_write_register` (coordinator.py:86) only enforces bounds when **both** `lo` and `hi`
are not `None`. 59 editable registers ship with null limits:
- **7 dangerous** (can damage/brick): 1061 (F27), 1343 (A39), 1348 (C13), 1349 (C14),
  1350 (C15), 1351 (E20), 1352 (E21).
- **52 advanced**, including RAW-typed installer registers (1015, 1017, 1022, 1026, 1036,
  1065, 1067, 1078, 1079, 1141, 1150, 1151, 1204, 1326–1333, 1348–1352 …).

Once `enable_expert` is on, the expert guard (`requires_expert`) passes and the range guard
is a no-op, so `async_write_register(addr, value)` will forward **any** float, which is then
`int(round(value)) & 0xFFFF` → full 0–65535 raw modbus write. The `build_metadata.py`
fallbacks (lines 155–163) intentionally only apply when `lo is None and editable`, but they
are *not* being applied for these addresses — they have explicit `lo/hi=None` in the JSON,
meaning the fallback branch is bypassed (the generator stores `null`, and the runtime has no
second-chance fallback). Net effect: a user who enabled expert mode (one checkbox) can write
arbitrary raw values to compressor/defrost/EVI registers.

Fix:
- In `build_metadata.py`, never emit `null` limits for editable registers — always fall back
  to per-type safe bounds, then re-run the generator.
- In `async_write_register`, add a hard safety clamp: if `lo/hi` is missing for an editable
  register, **reject** the write (fail closed) rather than skip the check, or apply
  `meta.get("type")`-based default bounds at runtime.
- For the 7 dangerous+null registers specifically, set explicit conservative limits or mark
  `editable:false` until bounds are known.

### 3. Expert gate is too weak (MEDIUM)
- `FoxAirOptionsFlow` requires `expert_ack=True` when enabling expert, but `expert_ack` is a
  boolean re-shown every time; there is no persistence of *who* acknowledged, no requirement
  that the user be `admin`/`owner`, and no second factor. Any HA user with "Configuration:
  Integrations" permission can enable expert mode and then write to 266 `requires_expert`
  registers.
- HA's `requires_auth=True` on the panel views does not protect writes — writes happen through
  entity services, which respect only HA's normal user permission model (not the integration's
  expert flag). So the expert flag is the *only* thing standing between a non-expert user and
  dangerous writes, and it is trivially toggleable.

Hardening:
- Gate `enable_expert` behind `hass.auth` admin/owner check (or document that it grants full
  installer access).
- Consider a persistent "dangerous mode armed" state + confirmation in the number/select
  entities themselves (e.g. re-affirm on each dangerous write), not just at the options step.
- Add a `logger` warning + persistent notification when expert mode is enabled.

### 4. Climate direct writes (LOW/MEDIUM)
`climate.py` writes 1011 (power), 1012 (mode), 1158/1159 (setpoints) via
`async_write_register`. Values are internally derived (`HVAC_REV` map, `RAW_MODE_TO_TARGET`),
so there is **no external injection path** here. However:
- The ON path is dead due to #1 (1011 min=max=0).
- 1012 (mode) has `min/max=None` + `type=MODE_0_4`; range check is skipped, but values are
  constrained by `HVAC_REV` (0–3) so impact is limited.
- `target_temperature` uses `_attr_min_temp/max_temp` from metadata (1158: -30..60) for the UI,
  but the actual write still runs through `async_write_register` bounds — consistent.

Recommendation: fix #1 so ON works; add an explicit allow-list of valid mode integers in
`async_set_hvac_mode` even though inputs are internal.

### 5. Input conversion robustness (LOW)
- `select.py:87` `int(raw_str)` / `number.py` `float(value)`: both can raise on malformed
  data. HA wraps entity service calls, so failures surface as errors (acceptable), but there is
  no rate limiting / debouncing on rapid writes. A UI slider drag could spam `write_register`
  calls (the `asyncio.Lock` serializes them, which is good, but each still hits the device).
- `number.py` `native_value` returns `float(v)`; if `v` is a non-numeric string it returns
  `None` — fine.

Recommendation: validate `value` is finite (`math.isfinite`) in `async_write_register` before
conversion; reject NaN/Inf.

### 6. HTTP views — no injection (INFO / PASS)
`views.py` both views set `requires_auth = True`. They read only from `coord.data` (floats) and
emit a fixed SVG/HTML template. The one interpolated dynamic value, `at`, is `str(at_v)` of a
float from the device — not attacker-controlled, not wrapped in HTML-escaping but it is a
number, so XSS is not reachable. No query params, no path traversal, no `host`/SSRF. **Pass.**
(Side note: the iframe panel uses `require_admin=False` — fine since it's read-only, but note
it means any authenticated HA user can view installer curve data.)

### 7. Positives (no action needed)
- `async_write_register` correctly: rejects non-editable, enforces expert gate, locks writes,
  masks signed→u16, requests refresh.
- Dangerous registers are `EntityCategory.DIAGNOSTIC` + `entity_registry_enabled_default=False`.
- `diagnostics.py` exposes only host/port/slave + raw sample values — no credentials/PDFs.
- `config_flow` user step validates connectivity before creating the entry.
- `RISK_OVERRIDES` correctly flags bus-bricking registers (1024 H10, 1020 H34, 1019 H33,
  1027 H27, 1054 A26, 1074 F10, 1059 F01) as `dangerous`.

---

## Prioritized hardening checklist
1. **Fix `parse_range`** so `1011`/`1031` get correct non-degenerate limits (use value_map /
   anchored regex / reject `lo==hi` for non-enums). [resolves #1]
2. **Eliminate null limits** for all editable registers in `foxair_metadata.json` (re-run
   `build_metadata.py` with mandatory fallback, or fail-closed in `async_write_register`).
   [resolves #2]
3. **Fail closed** in `async_write_register`: if an editable register has missing bounds,
   reject rather than skip the clamp. [defense-in-depth for #2]
4. **Validate finite** numeric input (`math.isfinite`) before modbus conversion. [#5]
5. **Strengthen expert gate**: admin/owner requirement + persistent notification + consider
   per-write re-affirmation for `risk=dangerous`. [#3]
6. **Allow-list** valid mode integers in `climate.async_set_hvac_mode`. [#4]

No code was modified in this review; all findings are read-only analysis.
