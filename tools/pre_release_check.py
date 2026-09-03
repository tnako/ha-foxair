#!/usr/bin/env python3
"""Pre-release validation gate — run before bumping VERSION.

Orchestrates every check in order:
  1. validate.py         — version sync, i18n prefixes, syntax
  2. build_metadata.py    — regen metadata, confirm no diff (stale metadata catch)
  3. pytest tests/        — full test suite (write signatures, firmware gates,
                            heating curve math, SVG render, validate pass)
  4. check_regs.py        — if HASS_URL/HASS_TOKEN in .env, audit entities vs HA

If any step fails, exits non-zero with a clear message.

Usage: python3 tools/pre_release_check.py
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def run(label, cmd, cwd=None):
    cwd = cwd or ROOT
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    print(result.stdout, end="")
    if result.stderr:
        print("STDERR:", result.stderr, end="")
    if result.returncode != 0:
        print(f"\n  FAIL: {label} exited with code {result.returncode}")
        return False
    print(f"  OK: {label}")
    return True


def main():
    ok = True

    # 1. Local validation (version sync, i18n, syntax)
    ok &= run("validate.py — version + i18n + syntax", [
        sys.executable, str(TOOLS / "validate.py")
    ])

    # 2. Metadata regen check (stale metadata)
    ok &= run("metadata freshness — regen + diff", [
        sys.executable, str(TOOLS / "build_metadata.py")
    ])

    # Re-run validate after metadata regen (in case it changed)
    if not run("validate.py (post-regen)", [
        sys.executable, str(TOOLS / "validate.py")
    ]):
        ok = False

    # 3. Pytest suite
    ok &= run("pytest test suite", [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-v"
    ])

    # 4. Register audit (only if HA is reachable via .env)
    env_path = ROOT / ".env"
    ha_reachable = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "HASS_URL" and v.strip():
                    ha_reachable = True
                    break
    if ha_reachable:
        ok &= run("check_regs.py — register audit vs HA", [
            sys.executable, str(TOOLS / "check_regs.py")
        ])
    else:
        print(f"\n{'='*60}")
        print("  check_regs.py — SKIPPED (no HASS_URL in .env)")
        print("  To run register audit: set HASS_URL + HASS_TOKEN in .env")
        print(f"{'='*60}")

    print(f"\n{'='*60}")
    if ok:
        print("  ALL PRE-RELEASE CHECKS PASSED — safe to bump version")
        print(f"{'='*60}")
        sys.exit(0)
    else:
        print("  FAIL — fix issues before version bump")
        print(f"{'='*60}")
        sys.exit(1)


if __name__ == "__main__":
    main()
