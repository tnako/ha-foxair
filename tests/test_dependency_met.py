#!/usr/bin/env python3
"""const.dependency_met: registry depends_on / depends_on_values availability gate.

H36 (1236) modes: 0 fixed, 1 linear, 2 7-point. Slope (1234) only in 1,
offset / 0 degC point (1235) in 1 and 2, the six extra points only in 2.
"""
import json
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import test_bitfield_expand  # noqa: E402  (loads const.py with the HA stubs)

const = test_bitfield_expand.const

META = json.loads((ROOT / "custom_components/foxair/data/foxair_metadata.json").read_text())


def _coord(h36):
    data = {} if h36 is None else {1236: {"raw": h36, "value": h36}}
    return types.SimpleNamespace(data=data)


@pytest.mark.parametrize("h36,slope,offset,point", [
    (0, False, False, False),
    (1, True, True, False),
    (2, False, True, True),
])
def test_h36_mode_gates(h36, slope, offset, point):
    c = _coord(h36)
    assert const.dependency_met(c, META["1234"]) is slope
    assert const.dependency_met(c, META["1235"]) is offset
    for addr in ("1250", "1251", "1252", "1253", "1254", "1255"):
        assert const.dependency_met(c, META[addr]) is point, addr


def test_missing_dependency_and_plain_truthy():
    assert const.dependency_met(_coord(None), META["1234"]) is False
    assert const.dependency_met(_coord(None), META["1234"], missing=True) is True
    assert const.dependency_met(_coord(None), {}) is True
    plain = {"depends_on": 1236}
    assert const.dependency_met(_coord(0), plain) is False
    assert const.dependency_met(_coord(2), plain) is True
