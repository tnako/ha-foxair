#!/usr/bin/env python3
"""HA lists a device's entities by name, so the 7 curve points carry an index
("Point 1: -20 °C" .. "Point 7: +20 °C") and sort -20 -> +20 in every language."""
import json
import pathlib

CC = pathlib.Path(__file__).resolve().parent.parent / "custom_components/foxair"
ORDER = ["foxair_1250", "foxair_1251", "foxair_1252", "foxair_1235_points", "foxair_1253", "foxair_1254", "foxair_1255"]


def test_points_sort_minus20_to_plus20():
    for f in ("strings.json", "translations/en.json", "translations/de.json", "translations/ru.json"):
        num = json.loads((CC / f).read_text(encoding="utf-8"))["entity"]["number"]
        names = [num[k]["name"] for k in ORDER]
        assert names == sorted(names), (f, names)
        assert all(n.split(":")[0].endswith(str(i)) for i, n in enumerate(names, 1)), (f, names)
