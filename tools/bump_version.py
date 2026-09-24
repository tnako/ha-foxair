#!/usr/bin/env python3
"""Bump VERSION + manifest.json + README badge for a release.

Usage: python3 tools/bump_version.py <new_version>
       (called from: task bump version=X.Y.Z)

This script ONLY updates version fields — git commit/tag/push is done manually.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/bump_version.py <new_version>", file=sys.stderr)
        sys.exit(1)

    version = sys.argv[1].strip()
    # Validate semver-ish
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        print(f"Invalid version: {version} (expected X.Y.Z)", file=sys.stderr)
        sys.exit(1)

    # 0. CHANGELOG.md must already have the section for this version
    cl_path = ROOT / "CHANGELOG.md"
    m = re.search(r"^## (\d+\.\d+\.\d+) - ", cl_path.read_text(), re.M) if cl_path.exists() else None
    if not m or m.group(1) != version:
        top = m.group(1) if m else "none"
        print(f"CHANGELOG.md top section is {top}, expected {version}.", file=sys.stderr)
        print(f"Add '## {version} - YYYY-MM-DD' with bullets first, then re-run the bump.", file=sys.stderr)
        sys.exit(1)

    # 1. VERSION
    (ROOT / "VERSION").write_text(f"{version}\n")
    print(f"  VERSION: {version}")

    # 2. manifest.json
    man_path = ROOT / "custom_components/foxair/manifest.json"
    man = json.loads(man_path.read_text())
    man["version"] = version
    man_path.write_text(json.dumps(man, indent=2) + "\n")
    print(f"  manifest.json: {version}")

    # 3. README badge
    readme_path = ROOT / "README.md"
    readme = readme_path.read_text()
    readme = re.sub(
        r"badge/version-[0-9]+\.[0-9]+\.[0-9]+-blue",
        f"badge/version-{version}-blue",
        readme,
    )
    readme_path.write_text(readme)
    print(f"  README.md badge: {version}")

    print(f"\nBumped to v{version}. Commit + push to main; CI tags and releases:")
    print(f"  git add VERSION custom_components/foxair/manifest.json README.md CHANGELOG.md")
    print(f'  git commit -m "chore(release): v{version}"')
    print(f"  git push")
    print(f"Do NOT push the tag yourself: .github/workflows/release.yml tags v{version} and")
    print(f"publishes the release in one run (re-run it from the Actions tab if it failed).")


if __name__ == "__main__":
    main()
