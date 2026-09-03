#!/usr/bin/env bash
# Pre-release validation gate — run before bumping VERSION.
# Orchestrates: validate -> metadata regen -> pytest -> check_regs (if HA available)
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/pre_release_check.py
