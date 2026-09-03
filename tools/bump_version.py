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

    print(f"\nBumped to v{version}. Commit + tag + push manually:")
    print(f"  git add VERSION custom_components/foxair/manifest.json README.md")
    print(f'  git commit -m "chore(release): v{version}"')
    print(f'  git tag v{version}')
    print(f"  git push && git push origin v{version}")


if __name__ == "__main__":
    main()
