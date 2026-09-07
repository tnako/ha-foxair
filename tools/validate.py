#!/usr/bin/env python3
"""One-shot local validation. Prints only failures (or 'OK ...'). No noise.

Checks: VERSION==manifest.json, translations CODE: prefix sanity (no double
prefix; every tabs.txt code has a prefixed name in en/de/ru), python syntax,
full translation coverage (every visible register has en/de/ru entry,
ru != en, no unknown poll_tier), config.error keys for every errors[] key
used in config_flow.py.
Usage: tools/validate.py [--strict]
  --strict: also fail on hidden-or-reserved ru==en (default: only visible)
"""
import ast
import json
import re
import sys
import pathlib

R = pathlib.Path(__file__).resolve().parent.parent
CC = R / "custom_components/foxair"
errs = []
warns = []

ver = (R / "VERSION").read_text().strip()
man = json.loads((CC / "manifest.json").read_text())
if ver != man.get("version"):
    errs.append(f"VERSION={ver} manifest={man.get('version')}")

# README version badge must match VERSION (prevents stale public badge)
readme = (R / "README.md").read_text() if (R / "README.md").exists() else ""
m = re.search(r"badge/version-([0-9]+\.[0-9]+\.[0-9]+)", readme)
if not m:
    errs.append("README: version badge not found (expected ![Version](https://img.shields.io/badge/version-X.Y.Z-blue))")
elif m.group(1) != ver:
    errs.append(f"README badge v{m.group(1)} != VERSION v{ver} — update README.md badge")

# CHANGELOG.md must render as bullet lists on GitHub/HACS (release notes are
# shown as markdown). 2026-09: entries written as `|- ...` rendered as broken
# tables instead of lists (`|` opens a table row). Bullets are `- `.
_cl = (R / "CHANGELOG.md").read_text(encoding="utf-8-sig").splitlines() if (R / "CHANGELOG.md").exists() else []
for _ln, _line in enumerate(_cl, 1):
    if _line.startswith("|"):
        errs.append(f"CHANGELOG:{_ln}: line starts with '|' (renders as table on GitHub/HACS) — use '- ' bullets")
        break
_sections = [l for l in _cl if l.startswith("## ")]
if not _sections:
    errs.append("CHANGELOG: no '## X.Y.Z - YYYY-MM-DD' sections")
else:
    _top = re.match(r"## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})", _sections[0])
    if not _top:
        errs.append(f"CHANGELOG: top section malformed: '{_sections[0][:60]}' (want '## X.Y.Z - YYYY-MM-DD')")
    elif _top.group(1) != ver:
        errs.append(f"CHANGELOG top v{_top.group(1)} != VERSION v{ver}")
    # older sections keep their historical shape (some lack dates) — only the
    # top (current release) section is enforced

# tabs.txt codes (official tab order)
codes = set(re.findall(r"^\s*\*?\s*([A-Z]{1,2}\d{1,3}[a-z]?):", (R / "modbus/tabs.txt").read_text(), re.M))
strict = "--strict" in sys.argv

# load translations
translations = {}
for lang in ("en", "de", "ru"):
    f = CC / "translations" / f"{lang}.json"
    if not f.exists():
        errs.append(f"missing translations/{lang}.json")
        continue
    data = json.loads(f.read_text())
    names = {}
    # translations are grouped by platform: entity.<platform>.foxair_<addr>
    for platform, items in data.get("entity", {}).items():
        for k, v in items.items():
            if isinstance(v, dict) and "name" in v:
                # key is foxair_<addr> (e.g. foxair_1045)
                m = re.match(r"foxair_(\d+)", k)
                addr = int(m.group(1)) if m else None
                names[k] = v["name"]
                if addr is not None:
                    # also store by addr for coverage checks
                    pass
            else:
                errs.append(f"{lang}: malformed entry {k}")
    translations[lang] = {"raw": data, "names": names}
    # double prefix check
    for k, n in names.items():
        if re.match(r"^[A-Z]{1,2}\d{1,3}[a-z]?:\s*[A-Z]{1,2}\d{1,3}[a-z]?\s", n):
            errs.append(f"{lang}: double prefix: {k} -> {n[:60]}")
    prefixed = {m.group(1) for n in names.values() if (m := re.match(r"^([A-Z]{1,2}\d{1,3}[a-z]?):", n))}
    if miss := sorted(codes - prefixed):
        errs.append(f"{lang}: tabs.txt codes w/o prefixed name: {', '.join(miss)}")

_cfgflow = (CC / "config_flow.py").read_text()
_form_error_keys = set(re.findall(r'errors\["\w+"\]\s*=\s*"(\w+)"', _cfgflow))
for lang in ["strings", "en", "de", "ru"]:
    _file = CC / "strings.json" if lang == "strings" else CC / "translations" / f"{lang}.json"
    _fdata = json.loads(_file.read_text())
    _cfg_err = _fdata.get("config", {}).get("error", {})
    for ek in sorted(_form_error_keys):
        if ek not in _cfg_err:
            errs.append(f"{lang}: config.error missing key '{ek}' used in config_flow.py errors[]")

# load metadata for coverage + poll_tier checks
meta_path = CC / "data/foxair_metadata.json"
if meta_path.exists():
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    # visible = hidden==False
    cyr = re.compile(r"[А-Яа-яЁё]")
    # German residue markers for en check (en should not contain these German words)
    german_markers = re.compile(r"Gehaeuse|Wannenheizung|Einschalt|Heizung|Kühl|Verdampfer|Lüfter|Mischventil", re.I)

    # build addr->name map per lang keyed by foxair_<addr>
    addr_to_meta = {int(k): v for k, v in meta.items() if k.isdigit()}
    for lang in ("en", "de", "ru"):
        if lang not in translations:
            continue
        names = translations[lang]["names"]

    # per-lang orphan check: translation key with no metadata
    meta_addrs = set(addr_to_meta.keys())
    for lang in ("en", "de", "ru"):
        if lang not in translations:
            continue
        t_keys = set()
        for k in translations[lang]["names"]:
            m = re.match(r"foxair_(\d+)", k)
            if m:
                t_keys.add(int(m.group(1)))
        orphan = sorted(t_keys - meta_addrs)
        if orphan:
            warns.append(f"{lang}: {len(orphan)} orphan translation keys not in metadata: {orphan[:10]}")

    # coverage: every non-hidden metadata entry must have translation in each lang
    for addr, rec in addr_to_meta.items():
        hidden = rec.get("hidden", False)
        if hidden and not strict:
            # hidden never shown; skip coverage/cyrillic but still check poll_tier
            pass
        else:
            code = rec.get("code", "")
            for lang in ("en", "de", "ru"):
                if lang not in translations:
                    continue
                key = f"foxair_{addr}"
                name = translations[lang]["names"].get(key)
                if name is None:
                    errs.append(f"{lang}: missing translation for {key} ({code or 'no-code'} addr {addr} hidden={hidden})")
                    continue
                if code:
                    if not name.startswith(f"{code}:"):
                        errs.append(f"{lang}: {key} name must start with '{code}:' got '{name[:40]}'")
                # ru: visible entries must be translated (Cyrillic) and not identical to en
                if lang == "ru" and not hidden and code:
                    # allow acronym-only values like COP, SG (no Cyrillic expected)
                    tail = name.split(":", 1)[1].strip() if ":" in name else name
                    if tail in ("COP", "SG", "SG Ready", "SGstatus"):
                        pass
                    elif not cyr.search(name):
                        errs.append(f"ru: {key} ({code}) not translated (no Cyrillic): '{name[:60]}'")
                # de: visible entries with code should differ from en if en is English? we only check en german residue
        # also check poll_tier
        tier = rec.get("poll_tier")
        if tier not in ("quick", "medium", "rare"):
            errs.append(f"metadata {addr} ({rec.get('code')}) poll_tier invalid: {tier}")

    # cross-lang identical check: ru == en for visible entries
    if "en" in translations and "ru" in translations:
        en_names = translations["en"]["names"]
        ru_names = translations["ru"]["names"]
        for addr, rec in addr_to_meta.items():
            if rec.get("hidden") and not strict:
                continue
            key = f"foxair_{addr}"
            en_n = en_names.get(key)
            ru_n = ru_names.get(key)
            if en_n and ru_n and en_n == ru_n:
                # allow identical for purely numeric/reserved names (e.g. "1355: Reserved" is same in all langs except de)
                # but for codes with meaningful name, identical means untranslated
                code = rec.get("code", "")
                if code:
                    tail = en_n.split(":", 1)[1].strip() if ":" in en_n else en_n
                    if tail in ("COP", "SG", "SG Ready") or "Reserved" in en_n and not strict:
                        warns.append(f"ru==en (allowed) {key}: '{en_n[:40]}'")
                    else:
                        errs.append(f"ru: {key} ({code}) identical to en (untranslated): '{en_n[:60]}'")

    # en german residue
    if "en" in translations:
        for k, n in translations["en"]["names"].items():
            # skip headers without code
            if german_markers.search(n):
                # allow "PHNIX" etc not matching; already filtered
                errs.append(f"en: {k} contains German residue: '{n[:60]}'")
else:
    warns.append("metadata.json not found — skipping coverage checks")

for p in CC.rglob("*.py"):
    try:
        ast.parse(p.read_text())
    except SyntaxError as e:
        errs.append(f"syntax {p.name}:{e.lineno} {e.msg}")

# async_write_register must be called with exactly 2 positional args (addr, value).
# The coordinator signature is `async def async_write_register(self, addr, value)`.
# A third arg (e.g. self._meta) is a stale-call bug. (Checked via AST, like syntax.)
for p in CC.rglob("*.py"):
    tree = ast.parse(p.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "async_write_register"
        ):
            if len(node.args) > 2:
                errs.append(
                    f"async_write_register {p.name}:{node.lineno}: "
                    f"called with {len(node.args)} args (expected 2: addr, value)"
                )

# --- no absolute local paths / hardcoded hosts in tracked files ---  # secrets:allow
# Public repo: must not contain hardcoded user paths or hardcoded private IPs/hosts.
_abs_pat = re.compile(r"/Users/|/home/[a-z0-9_.-]+/(?:work|GIT|projects|Desktop|Documents)", re.I)  # secrets:allow
_hard_host_pat = re.compile(r"HA_HOST\s*=\s*[^\s#\"']+")
_ip_pat = re.compile(r"\b(?:192\.168\.|10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)\d{1,3}\.\d{1,3}")
try:
    import subprocess as _sp
    _tracked = _sp.check_output(["git", "ls-files", "-z"], cwd=str(R)).decode().split("\x00")
except Exception:
    _tracked = []
for _rel in _tracked:
    if not _rel or _rel.startswith("tests/") or _rel.startswith(".git/"):
        continue
    if _rel == ".env.example":
        _txt2 = (R / _rel).read_text(errors="ignore") if (R / _rel).exists() else ""
        for _ln, _line in enumerate(_txt2.splitlines(), 1):
            _stripped = _line.strip()
            if not _stripped or _stripped.startswith("#"):
                continue
            if _abs_pat.search(_line):
                errs.append(f"secrets: {_rel}:{_ln} contains absolute local path: {_line.strip()[:120]}")
            _m = _hard_host_pat.search(_line)
            if _m and "HA_HOST=" in _line:
                _val = _line.split("=", 1)[1].strip().split()[0].strip('"\'')
                if _val:
                    errs.append(f"secrets: {_rel}:{_ln} hardcoded HA_HOST value (must be empty, filled via .env): {_line.strip()[:120]}")
        continue
    _fp = R / _rel
    if not _fp.is_file():
        continue
    if _fp.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".gz", ".pyc"):
        continue
    try:
        _txt = _fp.read_text(errors="ignore")
    except Exception:
        continue
    for _ln, _line in enumerate(_txt.splitlines(), 1):
        if "secrets:allow" in _line:
            continue
        if "/Users/" in _line or _abs_pat.search(_line):  # secrets:allow
            errs.append(f"secrets: {_rel}:{_ln} contains absolute local path: {_line.strip()[:120]}")
        if _ip_pat.search(_line):
            errs.append(f"secrets: {_rel}:{_ln} contains private IP (use HA_HOST from .env): {_line.strip()[:120]}")
        if "root@" in _line and "$HA_HOST" not in _line and "${HA_HOST" not in _line:
            errs.append(f"secrets: {_rel}:{_ln} hardcoded root@host (use root@$HA_HOST from .env): {_line.strip()[:120]}")

# --- 2026-09-07 incident gates ---
# 1. Options/backend parity: every elec_source choice offered in config_flow
#    must be handled in computed.compute_electrical_power (an offered-but-
#    unimplemented source shows an unknown sensor with no error anywhere).
_m = re.search(r'"elec_source".*?vol\.In\(\[(.*?)\]\)', _cfgflow, re.S)
if _m:
    _offered = set(re.findall(r'"([^"]+)"', _m.group(1)))
    _comp_src = (CC / "computed.py").read_text()
    _handled = set(re.findall(r'source == "([^"]+)"', _comp_src))
    if _unhandled := sorted(_offered - _handled):
        errs.append(f"elec_source offered but unhandled in computed.py: {_unhandled}")
else:
    errs.append("elec_source vol.In not found in config_flow.py")

# 1b. Options parity (generalized): every key in the OptionsFlow schema must
#    be consumed outside config_flow.py (2026-09-07: v_gain/v_offset/i_gain/
#    i_offset were offered in Options for years but read nowhere — expert_ack
#    is the only intentional exception: ack-only checkbox, popped on save).
_opts_keys = set(re.findall(r'vol\.(?:Optional|Required)\("([^"]+)"', _cfgflow[_cfgflow.find("class FoxAirOptionsFlow"):]))
_ACK_ONLY = {"expert_ack"}
_other_src = "".join(
    (CC / f).read_text() for f in (
        "computed.py", "coordinator.py", "sensor.py", "climate.py",
        "number.py", "select.py", "switch.py", "time.py", "image.py",
        "views.py", "__init__.py", "heating_curve.py",
    ) if (CC / f).exists()
)
for _k in sorted(_opts_keys - _ACK_ONLY):
    if f'"{_k}"' not in _other_src and f"'{_k}'" not in _other_src:
        errs.append(f"options parity: '{_k}' offered in OptionsFlow but never read outside config_flow.py (remove or implement)")

# 1c. bit_split format (foxair_config.json -> metadata): every format==
#    bit_split entry needs valid bits (kind button|switch, unique slugs,
#    mask covering exactly the bits), must be editable + polled (hidden
#    addrs are never polled, so split bits would be dead), and every slug
#    needs a translation key foxair_<addr>_<slug> in strings + en/de/ru.
if meta_path.exists():
    _meta_all = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    _str_names = set()
    for _f in [CC / "strings.json"] + [CC / "translations" / f"{_l}.json" for _l in ("en", "de", "ru")]:
        try:
            _d = json.loads(_f.read_text(encoding="utf-8-sig"))
            for _plat, _items in _d.get("entity", {}).items():
                for _k, _v in _items.items():
                    if isinstance(_v, dict) and "name" in _v:
                        _str_names.add((_f.name, _k))
        except (OSError, json.JSONDecodeError):
            pass
    for _addr, _rec in _meta_all.items():
        if not _addr.isdigit() or _rec.get("format") != "bit_split":
            continue
        _bits = _rec.get("bits") or {}
        if not _bits:
            errs.append(f"bit_split {_addr}: empty bits")
            continue
        if bad_kinds := sorted({b.get("kind") for b in _bits.values()} - {"button", "switch", "status"}):
            errs.append(f"bit_split {_addr}: bad kinds {bad_kinds} (want button|switch|status)")
        _slugs = [b.get("slug") for b in _bits.values()]
        if not all(_slugs) or len(set(_slugs)) != len(_slugs):
            errs.append(f"bit_split {_addr}: slugs must be unique non-empty")
        _keys = [b.get("key") for b in _bits.values()]
        if not all(_keys) or len(set(_keys)) != len(_keys):
            errs.append(f"bit_split {_addr}: keys must be unique non-empty")
        _covered = 0
        for _b in _bits:
            _covered |= 1 << int(_b)
        if _rec.get("mask") != _covered:
            errs.append(f"bit_split {_addr}: mask {_rec.get('mask')} != bits-covered {_covered}")
        if not _rec.get("editable"):
            errs.append(f"bit_split {_addr}: must be editable (R/W word)")
        if _rec.get("hidden"):
            errs.append(f"bit_split {_addr}: must not be hidden (hidden addrs are never polled)")
        for _spec in _bits.values():
            _key = f"foxair_{_spec.get('key')}"
            for _fn in ("strings.json", "en.json", "de.json", "ru.json"):
                if (_fn, _key) not in _str_names:
                    errs.append(f"bit_split {_addr}: translation key '{_key}' missing in {_fn}")
        _alias = _rec.get("alias_switch")
        if _alias:
            if not _alias.get("key") or not isinstance(_alias.get("on"), int) or not isinstance(_alias.get("off"), int):
                errs.append(f"alias_switch {_addr}: need key + int on/off")
            if not _rec.get("editable"):
                errs.append(f"alias_switch {_addr}: target must be editable")
            if _rec.get("hidden"):
                errs.append(f"alias_switch {_addr}: target must not be hidden (never polled)")
            _akey = f"foxair_{_alias.get('key')}"
            for _fn in ("strings.json", "en.json", "de.json", "ru.json"):
                if (_fn, _akey) not in _str_names:
                    errs.append(f"alias_switch {_addr}: translation key '{_akey}' missing in {_fn}")

# 1d. HA forward-compat: deprecated registry/device APIs fail the build.
# (2026-09: via_device -> via_device_id, removal 2027.8; registry .devices /
# .entities mapping access, removal 2027.9. Both warn via helpers/frame.)
for _p in CC.rglob("*.py"):
    _src = _p.read_text()
    if ".devices.values()" in _src or ".entities.values()" in _src:
        errs.append(f"ha-deprecated {_p.name}: registry mapping access (.devices/.entities.values()) — use async_entries_for_config_entry")
    if _p.name != "const.py" and ".async_get_device(" in _src:
        errs.append(f"ha-deprecated {_p.name}: registry.async_get_device() (use async_get_device_by_identifier)")
for _p in CC.rglob("*.py"):
    if _p.name == "const.py":
        continue
    if re.search(r"via_device\s*=", _p.read_text()):
        errs.append(f"ha-deprecated {_p.name}: via_device= parameter (use const.bind_device_info -> via_device_id)")

# 1e. Device routing: every non-empty metadata block/tab must have a label
# in foxair_config.json blocks.labels — otherwise device_for_block silently
# falls through to the main device (2026-09: S01 contacts landed on main).
_cfg_labels = set(json.loads((CC / "data/foxair_config.json").read_text(encoding="utf-8-sig")).get("blocks", {}).get("labels", {}))
if meta_path.exists():
    _meta_all2 = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    _blocks_used = set()
    for _addr2, _rec2 in _meta_all2.items():
        if not _addr2.isdigit():
            continue
        for _fld in ("block", "tab"):
            _b = _rec2.get(_fld) or ""
            if _b and _b != _rec2.get("code"):
                _blocks_used.add(_b)
    if _unlabeled := sorted(_blocks_used - _cfg_labels):
        errs.append(f"device routing: blocks/tabs without label (fall through to main device): {_unlabeled}")
# non_expert_addrs + popular_addrs (foxair_config.json) must reference real metadata addrs
_cfg_extra = json.loads((CC / "data/foxair_config.json").read_text(encoding="utf-8-sig"))
if meta_path.exists():
    _meta_all3 = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    for _a in _cfg_extra.get("non_expert_addrs", []):
        if str(_a) not in _meta_all3:
            errs.append(f"non_expert_addrs: {_a} not in metadata")
    for _a in _cfg_extra.get("popular_addrs", []):
        if str(_a) not in _meta_all3:
            errs.append(f"popular_addrs: {_a} not in metadata")

# 2. Thread safety: async_write_ha_state must never run inside a lambda —
#    HA dispatches plain-function event callbacks in an executor thread
#    (2026-09-07: lambda in async_track_state_change_event spammed
#    "calls async_write_ha_state from a thread other than the event loop").
#    Use `async def` handlers, which HA runs in the event loop.
for p in CC.rglob("*.py"):
    try:
        _tree = ast.parse(p.read_text())
    except SyntaxError:
        continue
    for node in ast.walk(_tree):
        if isinstance(node, ast.Lambda):
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and ((isinstance(sub.func, ast.Attribute) and sub.func.attr == "async_write_ha_state")
                         or (isinstance(sub.func, ast.Name) and sub.func.id == "async_write_ha_state"))
                ):
                    errs.append(f"thread-safety {p.name}:{node.lineno}: async_write_ha_state inside lambda (use async def handler)")
                    break
        if (
            isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Attribute) and node.func.attr == "async_track_state_change_event")
                 or (isinstance(node.func, ast.Name) and node.func.id == "async_track_state_change_event"))
            and any(isinstance(a, ast.Lambda) for a in node.args)
        ):
            errs.append(f"thread-safety {p.name}:{node.lineno}: lambda passed to async_track_state_change_event (use async def handler)")

# 3. First-poll coverage: async_setup_entry creates entities from coord.data
#    exactly once, so any tier excluded from the first poll never gets entities
#    (2026-09-07: quick-only first poll hid all 28 medium addrs incl. compressor
#    freq 2071-2076 — no error, entities just never appeared).
try:
    _ctree = ast.parse((CC / "coordinator.py").read_text())
    _found_first = False
    for node in ast.walk(_ctree):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "is_first"
        ):
            _found_first = True
            _assigns = {}
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                    _assigns[sub.targets[0].id] = sub.value
            _dm = _assigns.get("do_medium")
            if not (isinstance(_dm, ast.Constant) and _dm.value is True):
                errs.append("first-poll: do_medium must be True in `if is_first` (else medium-tier entities are never created)")
            _dr = _assigns.get("do_rare")
            _rare_ok = isinstance(_dr, ast.Constant) and _dr.value is True
            if not _rare_ok and isinstance(_dr, ast.UnaryOp) and isinstance(_dr.op, ast.Not):
                _rare_ok = True  # `do_rare = not enable_expert` — cheap safe-rare only
            if not _rare_ok:
                errs.append("first-poll: do_rare must be True (or `not enable_expert`) in `if is_first` (else rare-tier entities are never created)")
            break
    if not _found_first:
        errs.append("first-poll: `if is_first` block not found in coordinator.py")
except SyntaxError:
    pass

if warns:
    print("WARN:")

    for w in warns[:30]:
        print(f"  {w}")
if errs:
    print("FAIL:")
    for e in errs[:60]:
        print(f"  {e}")
    sys.exit(1)
print(f"OK v{ver} — {len(codes)} tab codes, en/de/ru prefixes + syntax clean")
if meta_path.exists():
    print(f"  coverage: {len([v for v in addr_to_meta.values() if not v.get('hidden')])} visible addrs translated, tiers ok")
