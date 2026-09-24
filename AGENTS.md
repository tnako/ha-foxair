# AGENTS.md — Working in ha-foxair

## Commands (one list, no alternatives)

```bash
task validate        # gate after EVERY edit: version sync + i18n + syntax + signatures
task test            # pytest suite
task pre_release     # full gate: validate -> regen metadata -> validate -> pytest -> check_regs
task bump version=X.Y.Z  # bump VERSION + manifest.json + README badge (fixed: CLI var passes through, no vars block)
task deploy          # rsync to HA + restart, reads HA_HOST from .env (needs SSH)
```

Gates run on any Python 3.9+ (CI matrix: 3.9, 3.13, 3.14). Tests stub HA, so
only `pytest` is needed. Every module using `X | None` annotations starts with
`from __future__ import annotations`; create asyncio primitives inside a
running loop (3.9 has no implicit loop). Pick an interpreter once per shell
with `export FOXAIR_PY=<venv>/bin/python3`; all tasks and git hooks honor it.

## Release flow — order is enforced
1. Write the `## X.Y.Z - YYYY-MM-DD` CHANGELOG.md section FIRST (bump_version.py refuses to run without it; validate.py gates top entry == VERSION).
2. `task bump version=X.Y.Z`
3. Commit and push to main — git hooks (`.githooks/`, enabled via `task hooks` / `git config core.hooksPath .githooks`) run validate on commit and validate+pytest on push. Never bypass with `--no-verify`; fix the gate instead.
4. Do NOT tag by hand. `.github/workflows/release.yml` runs on every push to main: gate (validate + pytest + render) -> tag `vX.Y.Z` -> publish the GitHub release (HACS update) in ONE run, idempotently. A tag pushed with GITHUB_TOKEN never triggers another workflow, so never split tag and release into separate workflows (v0.7.8 got a tag and no release that way). A bumped VERSION without its CHANGELOG section fails the run. Missing release: re-run the workflow or `gh workflow run Release`. After a release push, confirm with `gh release view vX.Y.Z`.
5. Never chain `git commit` after gates through pipes — `cmd | tail` masks the gate's exit code and the commit lands anyway. Run gates as their own command, check exit code, then commit.

## Session bootstrap — ONE call before any work

```bash
cd ha-foxair && git status --short && git log --oneline -3 && cat VERSION && python3 tools/validate.py 2>&1 | tail -2
```
The workspace snapshot in your context is stale on arrival — never trust it, re-check.

## Register questions — metadata one-shots, never exploratory greps

- `foxair_metadata.json` is runtime truth (platform, risk, requires_expert, hidden, poll_tier, group, min/max). Do NOT re-read the 5000-line register JSON or grep 3000-line translation files for register questions.
- Single addr: `python3 -c "import json; print(json.load(open('custom_components/foxair/data/foxair_metadata.json'))['<ADDR>'])"`
- Whole picture: `python3 tools/metadata_report.py` (extend it, don't re-derive).
- Visibility bugs: check `requires_expert` + `hidden` + `risk` first — platform code only filters on those; don't hunt sensor.py/number.py/select.py unless a filter is broken.
- This snippet mirrors `coordinator._tier_addrs` + `_batches_for_addrs` — trust it over re-reading coordinator.py:
```python
import json
meta = json.load(open('custom_components/foxair/data/foxair_metadata.json'))
cfg  = json.load(open('custom_components/foxair/data/foxair_config.json'))
dead = {a for lo, hi in cfg['dead_ranges'] for a in range(lo, hi + 1)}
def tier(t, expert=False):
    return {int(k) for k, v in meta.items() if v.get('poll_tier') == t and k.isdigit()
            and v.get('risk') != 'blocked' and not v.get('hidden')
            and int(k) not in dead and int(k) < 50000
            and (expert or not v.get('requires_expert'))}
```
- Budget: ≤10 tool calls per "why is entity X shown/broken" diagnosis — more means you're grepping blind.

## Editing rules

- Edit `foxair_config.json` (hidden/dead_ranges/overrides/tiers) or `foxair_phnix_registers.json` (names/types), then `python3 tools/build_metadata.py`, then `task validate`. NEVER hand-edit `foxair_metadata.json` (regen clobbers it). New tab code also goes in `modbus/tabs.txt` first.
- New translations need `CODE: Name` prefix in en/de/ru (validate fails on missing or double prefix).
- Use the `patch` TOOL, never heredoc patches in terminal. For mechanical multi-spot JSON edits a small python rewrite is fine — then `git diff --stat` must stay minimal (full-file reindent = clobbered formatting → `git checkout` + redo with string replace).
- Batch independent reads into one turn; one terminal call per read-only recon.
- `task validate` after EVERY edit. It also blocks absolute paths / hardcoded hosts — use `HA_HOST` from `.env` (`.env.example` committed, `.env` ignored).

## Live HA — one batched pull, know the traps

- `ha_list_entities()` dumps ~1400 rows: pull ONCE, save to disk, filter locally. Entity_ids are code-based (`sensor.foxair_t04`, `number.foxair_r02`); unique_ids = `prefix_<slugified code or addr>`; legacy midfix uids (`_num_/_switch_/_sel_/_time_/_bin_`) are cleaned up on startup. For register audits use `tools/check_regs.py` (`--codes H01,P02` filters, `--direct` reads the device raw).
- EW11 allows ONE TCP client: exactly one `AsyncModbusTcpClient(` lifetime, all I/O under `coordinator._lock`. A second connect anywhere = frame corruption.
- `check_regs` UNAVAILABLE is not always a regression — check the `depends_on` chain first (e.g. G01–G04 go unavailable by design when G05 legionella enable = off). Don't block a release on by-design unavailability.
- HA host runs the deployed tree (deploy = `task deploy` + entry reload). Uncommitted local edits are NOT on the host.

## Control-source switches (H25/H36/mode) — read before touching climate/image

Bug class this prevents: a device register that changes what OTHER entities
mean gets exposed as a plain select, and nothing downstream reads it. 2026-09:
H25 switched to inlet, the climate kept showing outlet (sensor hardcoded to
2046, target picked by mode only, H25 polled every 5 min).

- `heating_curve.active_control(coord)` is the ONLY resolver of what the unit
  regulates: sensor, setpoint, curve on/off, limits and start/stop registers,
  from H25 (1035, `markers.control_source`), 1012 (`markers.status.mode_values`)
  and H36 (1236). Entity code never reads `outlet_water_temp`, R02/R03 or raw
  mode numbers directly; `validate.py` fails on marker register literals in
  climate.py/image.py.
- The H36 curve (2014) drives the target only while heating from a water
  source; cooling uses R03 (+R08/R09, R06/R07); a source with its own `target`
  (room: R70, R71-R74) uses its own registers.
- The curve card always draws the heating water side (curve or R02); its y-axis
  names the H25 sensor via the H25 select translations.

Adding or changing a switch (new selector register, new H25 value, new mode):
1. Map it in `foxair_config.json` markers (never in Python). A register that
   changes another entity's meaning is a marker, not just a select.
2. Resolve it in `active_control()`; consumers read the returned dict.
3. `task validate` enforces: every marker register exists, is quick-polled and
   non-expert (a stale switch = a stale entity); `control_source.by_value`
   covers the selector's full value_map; keys are the selector's option slugs in
   strings + en/de/ru; all `mode_values` keys exist.
4. Extend `tests/test_climate_control_source.py` (matrix: every by_value x H36 x
   heat/cool) and the render harness switch-gating cases. Run the new test
   against HEAD's code once: it must fail there.
5. Live: `tools/check_regs.py` emits `CLIMATE:*` rows comparing the climate's
   `control_source`/`current_addr`/`target_addr` attributes with the H25 select
   and register entities. Flip the switch on the unit, rerun, expect all OK.

Before building on an ad-hoc dict/logic in one entity, grep for siblings that
derive the same thing (climate + image both did "which target is active" and
drifted). Shared meaning goes into `heating_curve.py`.

## Platform-specific gates (run the named tool, don't eyeball)

- `image.py` (AT curve) → `python3 tools/render_test.py` after EVERY edit. It enforces: zero text overlaps, nothing outside the 1200×760 canvas, legend labels on grid, no raster filters (vector `paint-order` halo only), EN/DE/RU. Dump a sample to /tmp for a visual check when layout changes.
- Curve UX (locked Sep 2026, don't re-litigate): single live dot on the active target, two-tone heating/idle band with dashed R04/R05 bounds, start/stop pills above/below the central number-only pill.
- `number.py`: entities stay uniform SLIDERS (box-stepper experiment reverted — mixed rows look inconsistent). Exact phone input goes through `number.set_value` / Assist, not widget changes.

## Release (autonomous end-to-end, no prompt needed)

1. `task pre_release` (all green; triage check_regs UNAVAILABLE per above, don't chase by-design ones)
2. `task bump version=X.Y.Z`
3. CHANGELOG entry on top: `## X.Y.Z - YYYY-MM-DD`, bullets start with `- ` never `|-` (validate enforces this + top-section == VERSION)
4. `task validate` + `task test`
5. `git commit` + `git tag vX.Y.Z` + `git push` + `git push origin vX.Y.Z` (push triggers release CI; CI has no HA access)

## Invariants (all enforced by validate.py — triggers, not docs)

- `VERSION` == manifest.json == README badge.
- i18n `CODE:` prefix in all 3 languages, no double prefix, python syntax clean, metadata freshly regenerated, `async_write_register(addr, value)` 2-arg everywhere, min_firmware in config + metadata.
- `config_flow.py` error keys need `config.error` entries (not `config.abort`) in strings.json + all translations.
- Every Options `elec_source` handled in computed.py. State-writing event callbacks are `async def`, never `lambda`. First poll includes medium + cheap non-expert rare tiers (entities are created once from first-poll data).
- Multi-bit R/W words: `bit_split` in config + read-modify-write (never raw select); retired selects in `RETIRED_UID_SUFFIXES`. Plain-register normal-mode switches: `alias_switch`. Read-only BITFIELD + bit_map → auto binary_sensors; raw decimals skipped/retired. Every non-empty block/tab needs a `blocks.labels` entry.
- No deprecated HA APIs: `via_device_id` via `const.bind_device_info` (never `via_device` param); `async_entries_for_config_entry` (never `.devices`/`.entities.values()`).
- Poll resilience (validate gates 6-7): tier-ordered batches (quick first, `tier_groups`), reconnect-and-continue (`consec_conn_fail`, abort only after 3 in a row), 0.35s read pacing (never 0.22s). Diagnostics live-fetches `KEY_ADDRS` via `coord._fetch_addrs`, reports `key_fetch`, never caps the dump.

## DO NOT

- Skip validate after edits. Change `entity_id` (only friendly names reorder). Commit paths/IPs/credentials. Add Lovelace/YAML/HACS-config steps — everything ships via integration install only.
