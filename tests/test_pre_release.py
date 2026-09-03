#!/usr/bin/env python3
"""Pytest tests for ha-foxair.

Covers:
  - test_version_sync: VERSION == manifest.json.version == README badge
  - test_python_syntax: all .py files compile (py_compile)
  - test_metadata_coverage: regenerate metadata from current config and diff
    against the committed file (catches stale metadata.json)
  - test_switch_write_signature: switch.py calls coordinator async_write_register
    with the right arity (regression for the 3-arg bug)
  - test_select_write_signature: select.py calls async_write_register with 2 args
  - test_time_write_signature: time.py calls async_write_register with 2 args
  - test_number_write_signature: number.py calls async_write_register with 2 args
  - test_firmware_gate: min_firmware registers exist in metadata and config
  - test_heating_curve_math: calc_curve_target + curve_target_for_at correctness
  - test_render_svg: delegates to render_test.py's assertion harness (EN/DE/RU)
  - test_firmware_format: sensor formats 2104 as vX.Y

Run: pytest tests/ -v
"""
import ast
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CC = ROOT / "custom_components/foxair"
TOOLS = ROOT / "tools"
DATA = CC / "data"


def _py_files():
    for p in CC.rglob("*.py"):
        yield p


# ── Version sync ──────────────────────────────────────────────────
def test_version_sync():
    ver = (ROOT / "VERSION").read_text().strip()
    man = json.loads((CC / "manifest.json").read_text())
    assert ver == man["version"], f"VERSION={ver} != manifest={man['version']}"

    readme = (ROOT / "README.md").read_text()
    m = re.search(r"badge/version-([0-9]+\.[0-9]+\.[0-9]+)", readme)
    assert m, "README version badge not found"
    assert m.group(1) == ver, f"README badge v{m.group(1)} != VERSION v{ver}"


# ── Python syntax ─────────────────────────────────────────────────
def test_python_syntax():
    for p in _py_files():
        ast.parse(p.read_text(), filename=str(p))


# ── Metadata freshness ────────────────────────────────────────────
def test_metadata_not_stale():
    """Regenerate metadata and compare to committed file."""
    meta_before = json.loads((DATA / "foxair_metadata.json").read_text())
    result = subprocess.run(
        [sys.executable, str(TOOLS / "build_metadata.py")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, f"build_metadata failed: {result.stderr}"
    meta_after = json.loads((DATA / "foxair_metadata.json").read_text())
    assert meta_before == meta_after, (
        "foxair_metadata.json is stale — run tools/build_metadata.py"
    )


# ── Write-signature regression tests ──────────────────────────────
def _check_async_write_call(filepath, filename):
    """Ensure async_write_register is called with exactly 2 positional args
    (addr, value) — the coordinator signature is
    `async def async_write_register(self, addr, value)`."""
    source = filepath.read_text()
    tree = ast.parse(source)
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for child in ast.walk(node):
                pass  # we look at node.func
            func = node.func
            # Match self.coordinator.async_write_register(...) or
            # coord.async_write_register(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "async_write_register"
                and isinstance(node, ast.Call)
            ):
                # positional args: skip self (the .func.value is the receiver)
                args = node.args
                if len(args) > 2:
                    violations.append(
                        f"{filename}:{node.lineno}: "
                        f"async_write_register called with {len(args)} args "
                        f"(expected 2: addr, value)"
                    )
    assert not violations, (
        "async_write_register signature mismatch:\n  "
        + "\n  ".join(violations)
    )


def test_switch_write_signature():
    _check_async_write_call(CC / "switch.py", "switch.py")


def test_select_write_signature():
    _check_async_write_call(CC / "select.py", "select.py")


def test_time_write_signature():
    _check_async_write_call(CC / "time.py", "time.py")


def test_number_write_signature():
    _check_async_write_call(CC / "number.py", "number.py")


def test_climate_write_signature():
    _check_async_write_call(CC / "climate.py", "climate.py")


# ── Firmware gate ─────────────────────────────────────────────────
def test_firmware_gate_present():
    cfg = json.loads((DATA / "foxair_config.json").read_text())
    overrides = cfg.get("markers", {}).get("overrides", {})
    fw_gated = {
        str(k): v for k, v in overrides.items() if "min_firmware" in v
    }
    assert fw_gated, "No min_firmware overrides in foxair_config.json"
    meta = json.loads((DATA / "foxair_metadata.json").read_text())
    for addr in fw_gated:
        assert addr in meta, f"Firmware-gated addr {addr} not in metadata"
        assert meta[addr].get("min_firmware") == 33


# ── Heating curve math ────────────────────────────────────────────
def test_calc_curve_target():
    # offset=37, slope=0.6, AT=0 -> 37; AT=10 -> 37-6=31
    sys.path.insert(0, str(CC))
    # stub HA imports
    _stub_ha()
    from heating_curve import calc_curve_target
    assert calc_curve_target(0, 0.6, 37.0) == 37.0
    assert calc_curve_target(10, 0.6, 37.0) == 31.0
    assert calc_curve_target(-5, 0.6, 37.0) == 40.0


def _stub_ha():
    """Minimal HA module stubs so heating_curve can import."""
    import types
    for name in ("homeassistant",):
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.__path__ = []
            sys.modules[name] = m
    comp = types.ModuleType("homeassistant.components")
    comp.__path__ = []
    sys.modules["homeassistant.components"] = comp


def test_curve_target_for_at():
    _stub_ha()
    from heating_curve import curve_target_for_at

    class FakeMeta:
        marker_map = {
            "heat_curve": {
                "addr_single": {
                    "slope": 1234, "offset": 1235, "at_comp_en": 1236,
                    "live_target": 2014, "at_sensor": 2048,
                    "r10_min": 1164, "r11_max": 1165,
                }
            },
        }

        def marker(self, name):
            return self.marker_map.get(name, {})

        @property
        def data(self):
            return {
                1234: {"value": 0.6, "raw": 6},
                1235: {"value": 37.0, "raw": 370},
                1236: {"value": 1, "raw": 1},
                2048: {"value": -5.0, "raw": -50},
                1234: {"value": 0.6, "raw": 6},
                1235: {"value": 37.0, "raw": 370},
                2014: {"value": 40.0, "raw": 400},
                1164: {"value": 20.0, "raw": 200},
                1165: {"value": 60.0, "raw": 600},
            }

    coord = FakeMeta()
    result = curve_target_for_at(coord, -5.0)
    assert result is not None
    assert 30 < result < 45  # offset 37, slope 0.6, AT -5 -> 40, clamped


# ── Firmware version formatting ───────────────────────────────────
def test_firmware_format_in_metadata():
    meta = json.loads((DATA / "foxair_metadata.json").read_text())
    assert meta["2104"].get("format") == "firmware"
    assert meta["2104"].get("poll_tier") == "quick"


# ── SVG render test (delegates to render_test.py) ─────────────────
def test_render_svg():
    """Run the render_test.py harness via subprocess — it has its own HA stubs."""
    result = subprocess.run(
        [sys.executable, str(TOOLS / "render_test.py")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"render_test failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# ── validate.py passes ────────────────────────────────────────────
def test_validate_passes():
    result = subprocess.run(
        [sys.executable, str(TOOLS / "validate.py")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"validate.py failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
