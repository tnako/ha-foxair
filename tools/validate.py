#!/usr/bin/env python3
"""One-shot local validation. Prints only failures (or 'OK ...'). No noise.

Checks: VERSION==manifest.json, translations CODE: prefix sanity (no double
prefix; every tabs.txt code has a prefixed name in en/de/ru), python syntax,
and full translation coverage (every visible register has en/de/ru entry,
ru != en, no unknown poll_tier).
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
