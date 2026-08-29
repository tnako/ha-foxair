#!/usr/bin/env python3
"""One-shot local validation. Prints only failures (or 'OK ...'). No noise.

Checks: VERSION==manifest.json, translations CODE: prefix sanity (no double
prefix; every tabs.txt code has a prefixed name in en/de/ru), python syntax.
Usage: tools/validate.py
"""
import ast, json, re, sys, pathlib

R = pathlib.Path(__file__).resolve().parent.parent
CC = R / "custom_components/foxair"
errs = []

ver = (R / "VERSION").read_text().strip()
man = json.loads((CC / "manifest.json").read_text())
if ver != man.get("version"):
    errs.append(f"VERSION={ver} manifest={man.get('version')}")

codes = set(re.findall(r"^\s*\*?\s*([A-Z]{1,2}\d{1,3}[a-z]?):", (R / "modbus/tabs.txt").read_text(), re.M))
for lang in ("en", "de", "ru"):
    f = CC / "translations" / f"{lang}.json"
    if not f.exists():
        errs.append(f"missing translations/{lang}.json")
        continue
    names = {k: v["name"] for p, items in json.loads(f.read_text()).get("entity", {}).items()
             for k, v in items.items() if isinstance(v, dict) and "name" in v}
    for k, n in names.items():
        if re.match(r"^[A-Z]{1,2}\d{1,3}[a-z]?:\s*[A-Z]{1,2}\d{1,3}[a-z]?\s", n):
            errs.append(f"{lang}: double prefix: {n[:50]}")
    prefixed = {m.group(1) for n in names.values() if (m := re.match(r"^([A-Z]{1,2}\d{1,3}[a-z]?):", n))}
    if miss := sorted(codes - prefixed):
        errs.append(f"{lang}: tabs.txt codes w/o prefixed name: {', '.join(miss)}")

for p in CC.rglob("*.py"):
    try:
        ast.parse(p.read_text())
    except SyntaxError as e:
        errs.append(f"syntax {p.name}:{e.lineno} {e.msg}")

if errs:
    print("\n".join(errs[:30]))
    sys.exit(1)
print(f"OK v{ver} — {len(codes)} tab codes, en/de/ru prefixes + syntax clean")