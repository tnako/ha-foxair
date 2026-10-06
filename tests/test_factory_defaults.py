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


def _fits(meta, v):
    if meta.get("has_value_map") or meta.get("platform") == "select":
        return True
    lo, hi = meta.get("min"), meta.get("max")
    return (lo is None or v >= float(lo) - 1e-9) and (hi is None or v <= float(hi) + 1e-9)


def test_every_code_exists_and_every_candidate_fits_the_register_range():
    for model, block in DEFAULTS["models"].items():
        for code, rec in block["values"].items():
            assert code in BY_CODE, f"{model}: {code} not in metadata"
            addr, meta = BY_CODE[code]
            for v in [rec["value"], *rec.get("candidates", {}).values()]:
                if v is not None:
                    assert _fits(meta, float(v)), f"{model}: {code} ({addr}) {v} outside {meta.get('min')}..{meta.get('max')}"


def test_confidence_matches_the_sources():
    for model, block in DEFAULTS["models"].items():
        levels = block["confidence_levels"]
        for code, rec in block["values"].items():
            assert rec["confidence"] in levels, f"{model}: {code} unknown confidence {rec['confidence']}"
            for s in [*rec["sources"], *rec.get("candidates", {})]:
                assert s in block["sources"], f"{model}: {code} unknown source {s}"
            if rec["confidence"] == "conflict":
                assert rec["value"] is None and len(rec["candidates"]) >= 2, f"{model}: {code} conflict needs null + candidates"
            else:
                assert rec["value"] is not None and rec["sources"], f"{model}: {code} needs a value and a source"
            if rec["confidence"] == "two_units":
                assert len(rec["sources"]) >= 2


def test_doc_page_lists_the_json_and_every_model():
    doc = (ROOT / "docs/FACTORY_DEFAULTS.md").read_text(encoding="utf-8")
    assert "foxair_factory_defaults.json" in doc
    for model, block in DEFAULTS["models"].items():
        assert model in doc
        for level in block["confidence_levels"]:
            assert f"`{level}`" in doc
