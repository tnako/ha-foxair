#!/usr/bin/env python3
"""One-shot metadata overview: replaces 10 exploratory greps with one command.

Prints per-block/group visibility counts, risk + tier + hidden totals, and
optionally one addr's full metadata record:  tools/metadata_report.py 1234
"""
import json
import pathlib
import sys
import collections

MP = pathlib.Path(__file__).parent.parent / "custom_components/foxair/data/foxair_metadata.json"
m = json.loads(MP.read_text())

if len(sys.argv) > 1:
    for a in sys.argv[1:]:
        v = m.get(a)
        if v is None:
            print(f"{a}: NOT IN METADATA")
            continue
        vis = "HIDDEN" if v.get("hidden") else ("expert-only" if v.get("requires_expert") else "visible")
        print(f"{a} [{v.get('code') or '-'}] {v.get('group')} | {v.get('platform')} "
              f"edit={v.get('editable')} risk={v.get('risk')} poll={v.get('poll_tier')} "
              f"{vis} | {v.get('name', '')[:60]}")
    sys.exit(0)

by_vis = collections.Counter()
by_group = collections.Counter()
by_tier = collections.Counter()
for v in m.values():
    state = "hidden" if v.get("hidden") else ("expert" if v.get("requires_expert") else "normal")
    by_vis[state] += 1
    by_tier[v.get("poll_tier")] += 1
    if state != "hidden":
        by_group[(v.get("group") or "-", state)] += 1

print(f"{len(m)} registers — normal:{by_vis['normal']} expert-only:{by_vis['expert']} hidden:{by_vis['hidden']}")
print("poll tiers:", dict(by_tier))
print("\ngroup: normal+expert counts")
for (g, s), c in sorted(by_group.items()):
    print(f"  {g:24} {s:7} {c}")
