#!/usr/bin/env python3
"""Print the CHANGELOG.md section for a version (GitHub release body).

Usage: tools/release_notes.py X.Y.Z
Exits non-zero when the section is missing, so CI never publishes a release
with placeholder notes. Used by .github/workflows/release.yml and tests.
"""
import pathlib
import re
import sys

CHANGELOG = pathlib.Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(version: str, text: str) -> str:
    m = re.search(rf"^## {re.escape(version)}(?![\w.]).*?(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise LookupError(f"CHANGELOG.md has no '## {version}' section")
    return m.group(0).strip() + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        sys.stdout.write(section(sys.argv[1], CHANGELOG.read_text(encoding="utf-8")))
    except LookupError as e:
        sys.exit(f"::error::{e}")
