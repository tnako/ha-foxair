#!/usr/bin/env python3
"""foxair_factory_defaults.json stays consistent with the register metadata.

Run: pytest tests/test_factory_defaults.py -v
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "custom_components/foxair/data"
DEFAULTS = json.loads((DATA / "foxair_factory_defaults.json").read_text(encoding="utf-8"))
META = json.loads((DATA / "foxair_metadata.json").read_text(encoding="utf-8"))
BY_CODE = {v["code"]: (a, v) for a, v in META.items() if a.isdigit() and v.get("code")}


def test_every_code_exists_and_value_fits_the_register_range():
    for model, block in DEFAULTS["models"].items():
        for code, rec in block["values"].items():
            assert code in BY_CODE, f"{model}: {code} not in metadata"
            addr, meta = BY_CODE[code]
            v = float(rec["value"])
            lo, hi = meta.get("min"), meta.get("max")
            if meta.get("has_value_map") or meta.get("platform") == "select":
                continue
            if lo is not None:
                assert v >= float(lo) - 1e-9, f"{model}: {code} ({addr}) {rec['value']} below {lo}"
            if hi is not None:
                assert v <= float(hi) + 1e-9, f"{model}: {code} ({addr}) {rec['value']} above {hi}"


def test_every_value_names_a_known_source():
    for model, block in DEFAULTS["models"].items():
        assert block["sources"] and block["match"]
        for code, rec in block["values"].items():
            assert rec["source"] in block["sources"], f"{model}: {code} source {rec['source']}"
            for alt in rec.get("alt", {}):
                assert alt in block["sources"], f"{model}: {code} alt source {alt}"


def test_doc_page_lists_the_json():
    doc = (ROOT / "docs/FACTORY_DEFAULTS.md").read_text(encoding="utf-8")
    assert "foxair_factory_defaults.json" in doc
    for model in DEFAULTS["models"]:
        assert model in doc
