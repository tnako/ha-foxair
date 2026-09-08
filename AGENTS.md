# AGENTS.md — Working in ha-foxair

## Commands (one list, no alternatives)

```bash
task validate        # gate after EVERY edit: version sync + i18n + syntax + signatures
task test            # pytest suite
task pre_release     # full gate: validate -> regen metadata -> validate -> pytest -> check_regs
task bump version=X.Y.Z  # bump VERSION + manifest.json + README badge (fixed: CLI var passes through, no vars block)
task deploy          # rsync to HA + restart, reads HA_HOST from .env (needs SSH)
```

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

- `ha_list_entities()` dumps ~1400 rows: pull ONCE, save to disk, filter locally. Entity names are code-suffix based (`..._a_antifreeze_temp_a04`), not `foxair_<addr>`. For register audits use `tools/check_regs.py` (`--codes H01,P02` filters, `--direct` reads the device raw).
- EW11 allows ONE TCP client: exactly one `AsyncModbusTcpClient(` lifetime, all I/O under `coordinator._lock`. A second connect anywhere = frame corruption.
- `check_regs` UNAVAILABLE is not always a regression — check the `depends_on` chain first (e.g. G01–G04 go unavailable by design when G05 legionella enable = off). Don't block a release on by-design unavailability.
- HA host runs the deployed tree (deploy = `task deploy` + entry reload). Uncommitted local edits are NOT on the host.

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

## DO NOT

- Skip validate after edits. Change `entity_id` (only friendly names reorder). Commit generated vendor code without validate. Commit paths/IPs/credentials. Add Lovelace/YAML/HACS-config steps — everything ships via integration install only.
