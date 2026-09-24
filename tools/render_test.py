"""Offline render test for the heating-curve SVG (image.py).

Stubs HA modules, builds a fake coordinator, renders the SVG for multiple
AT values and both H36 modes (curve/fixed), and asserts:

  - No text element overflows the 1200x720 canvas.
  - At least 6 X-axis tick dots (circles r=3 on the axis line).
  - All legend labels present.
  - No two text elements at the same y-level have overlapping x-ranges.
  - Works with EN, DE, and RU translations (wider Cyrillic glyphs).

Usage:
    cd /path/to/ha-foxair
    python3 tools/render_test.py
"""
import sys
import types
import os
import re
import importlib.util
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- stub HA modules (before importing anything from custom_components) ---
pkg = types.ModuleType("homeassistant")
pkg.__path__ = []
sys.modules["homeassistant"] = pkg

comp = types.ModuleType("homeassistant.components")
comp.__path__ = []
sys.modules["homeassistant.components"] = comp

img_mod = types.ModuleType("homeassistant.components.image")
class ImageEntity:
    _attr_content_type = None
    def __init__(self, hass=None): self.hass = hass
    def async_write_ha_state(self): pass
img_mod.ImageEntity = ImageEntity
sys.modules["homeassistant.components.image"] = img_mod

helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []
sys.modules["homeassistant.helpers"] = helpers

helpers_entity = types.ModuleType("homeassistant.helpers.entity")
class DeviceInfo:
    def __init__(self, *a, **k): pass
class Entity:
    def __init__(self, *a, **k): pass
helpers_entity.DeviceInfo = DeviceInfo
helpers_entity.Entity = Entity
sys.modules["homeassistant.helpers.entity"] = helpers_entity
helpers.entity = helpers_entity

upc = types.ModuleType("homeassistant.helpers.update_coordinator")
class CoordinatorEntity:
    def __init__(self, coordinator=None): self.coordinator = coordinator
    def _handle_coordinator_update(self): pass
upc.CoordinatorEntity = CoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"] = upc

tr = types.ModuleType("homeassistant.helpers.translation")
tr.async_get_translations = lambda *a, **k: {}
sys.modules["homeassistant.helpers.translation"] = tr

core = types.ModuleType("homeassistant.core")
class HomeAssistant:
    pass
core.HomeAssistant = HomeAssistant
sys.modules["homeassistant.core"] = core

ce = types.ModuleType("homeassistant.config_entries")
class ConfigEntry:
    pass
ce.ConfigEntry = ConfigEntry
sys.modules["homeassistant.config_entries"] = ce

dr = types.ModuleType("homeassistant.helpers.device_registry")
sys.modules["homeassistant.helpers.device_registry"] = dr

er = types.ModuleType("homeassistant.helpers.entity_registry")
er.async_get = lambda *a, **k: None
sys.modules["homeassistant.helpers.entity_registry"] = er

# --- namespace packages for custom_components ---
cc = types.ModuleType("custom_components")
cc.__path__ = [os.path.join(ROOT, "custom_components")]
sys.modules["custom_components"] = cc

foxair_pkg = types.ModuleType("custom_components.foxair")
foxair_pkg.__path__ = [os.path.join(ROOT, "custom_components", "foxair")]
sys.modules["custom_components.foxair"] = foxair_pkg

# --- now import the real const + heating_curve + image modules ---
const_spec = importlib.util.spec_from_file_location(
    "custom_components.foxair.const",
    os.path.join(ROOT, "custom_components", "foxair", "const.py"),
)
const_mod = importlib.util.module_from_spec(const_spec)
sys.modules["custom_components.foxair.const"] = const_mod
const_spec.loader.exec_module(const_mod)

hc_spec = importlib.util.spec_from_file_location(
    "custom_components.foxair.heating_curve",
    os.path.join(ROOT, "custom_components", "foxair", "heating_curve.py"),
)
hc_mod = importlib.util.module_from_spec(hc_spec)
sys.modules["custom_components.foxair.heating_curve"] = hc_mod
hc_spec.loader.exec_module(hc_mod)

img_spec = importlib.util.spec_from_file_location(
    "custom_components.foxair.image",
    os.path.join(ROOT, "custom_components", "foxair", "image.py"),
)
img = importlib.util.module_from_spec(img_spec)
sys.modules["custom_components.foxair.image"] = img
img_spec.loader.exec_module(img)

# ======================================================================
# Fake coordinator + test harness
# ======================================================================

MARKERS = json.load(open(os.path.join(ROOT, "custom_components", "foxair", "data", "foxair_config.json"), encoding="utf-8"))["markers"]
METADATA = json.load(open(os.path.join(ROOT, "custom_components", "foxair", "data", "foxair_metadata.json"), encoding="utf-8"))


class FHass:
    class config:
        language = "en"

class FakeCoord:
    def __init__(self, data):
        self.data = data
        self.hass = FHass()
        self._metadata = {}
        self.entry = type("E", (), {"entry_id": "test", "data": {"host": "test", "port": 8899, "slave": 1}, "options": {}})()
        self._entry_id = "test"
    def marker(self, name):
        return MARKERS.get(name, {})
    def get_metadata(self, addr):
        return METADATA.get(str(addr), {})

def make_data(at_live, after=None, h36=1, slope=0.6, offset=37.0):
    data = {}
    data[1234] = {"value": slope, "raw": int(slope * 10)}
    data[1235] = {"value": offset, "raw": int(offset * 10)}
    data[1236] = {"value": h36, "raw": h36}
    data[2048] = {"value": at_live}
    if after is not None:
        data[2014] = {"value": after}
    data[1164] = {"value": 20.0}
    data[1165] = {"value": 60.0}
    data[1158] = {"value": 35.0}
    data[1160] = {"value": 3.0}  # R04 start hysteresis
    data[1161] = {"value": 2.0}  # R05 stop hysteresis
    return data

EN_TL = {
    "name": "Heating Curve",
    "legend_curve": "Curve target",
    "legend_fixed": "Fixed setpoint",
    "legend_live": "Live outdoor",
    "legend_heat": "Heating range (R04-R05)",
    "legend_start": "Start heating",
    "legend_stop": "Stop heating",
    "legend_band": "Limit band (R10–R11)",
    "mode_curve": "AT compensation (curve)",
    "mode_fixed": "Constant (fixed)",
    "wait": "Waiting for data",
    "wait_sub": "First poll in progress (quick 30s)",
    "axis_x": "Outdoor temperature (AT)",
    "axis_y": "Flow temperature",
}

RU_TL = {
    "name": "Кривая отопления",
    "legend_curve": "Цель кривой",
    "legend_fixed": "Фикс. уставка",
    "legend_live": "Тек. AT",
    "legend_heat": "Зона нагрева (R04-R05)",
    "legend_start": "Старт нагрева",
    "legend_stop": "Стоп нагрева",
    "legend_band": "Диапазон (R10–R11)",
    "mode_curve": "AT-компенсация (кривая)",
    "mode_fixed": "Константа (фикс.)",
    "wait": "Ожидание данных",
    "wait_sub": "Первый опрос (quick 30 с)",
    "axis_x": "Температура на улице (AT)",
    "axis_y": "Температура подачи",
}

DE_TL = {
    "name": "Heizkurve",
    "legend_curve": "Kurvenziel",
    "legend_fixed": "Fester Sollwert",
    "legend_live": "Live-Außen",
    "legend_heat": "Heizbereich (R04-R05)",
    "legend_start": "Heizstart",
    "legend_stop": "Heizstopp",
    "legend_band": "Grenzband (R10–R11)",
    "mode_curve": "AT-Kompensation (Kurve)",
    "mode_fixed": "Konstant (fest)",
    "wait": "Warte auf Daten",
    "wait_sub": "Erster Abruf läuft (quick 30 s)",
    "axis_x": "Außentemperatur (AT)",
    "axis_y": "Vorlauftemperatur",
}

TEST_CASES = [
    ("curve AT=-5", -5.0, 28.0, 1),
    ("curve AT=0", 0.0, 37.0, 1),
    ("curve AT=10", 10.0, 34.0, 1),
    ("curve AT=20 (edge)", 20.0, 31.0, 1),
    ("fixed AT=-10", -10.0, 43.0, 0),
    ("fixed AT=20", 20.0, 35.0, 0),
]

LANGS = [("ENGLISH", EN_TL), ("RUSSIAN", RU_TL), ("GERMAN", DE_TL)]

W, H = 1200, 760
all_ok = True

for lang_name, tl in LANGS:
    print(f"\n{'='*60}")
    print(f"  LANGUAGE: {lang_name}")
    print(f"{'='*60}")
    for test_name, at_live, after, h36 in TEST_CASES:
        coord = FakeCoord(make_data(at_live, after, h36))
        obj = img.FoxAirHeatingCurveImage(coord, "test")
        obj.hass = FHass()
        obj._tl = {**img._TL_FALLBACK, **tl}
        obj._render()
        svg = obj._image_bytes.decode("utf-8")

        # 1. No text overflow
        texts = re.findall(r'<text[^>]*x="([\d.]+)"[^>]*y="([\d.]+)"[^>]*>([^<]*)</text>', svg)
        overflow = [(float(x), txt) for x, y, txt in texts if float(x) > W or float(x) < 0]
        if overflow:
            print(f"  FAIL [{test_name}]: text overflow: {overflow}")
            all_ok = False
            continue

        # 2. X-axis tick dots
        x_dots = re.findall(r'<circle[^>]*cx="([\d.]+)"[^>]*cy="([\d.]+)"[^>]*r="3"', svg)
        x_axis_dots = [cx for cx, cy in x_dots if float(cy) > 500]
        if len(x_axis_dots) < 6:
            print(f"  FAIL [{test_name}]: only {len(x_axis_dots)} X-axis tick dots")
            all_ok = False
            continue

        # 3. Mode badge names the active line; inactive line is not drawn
        mode_key = "mode_curve" if h36 else "mode_fixed"
        if tl.get(mode_key, "") not in svg and img._TL_FALLBACK[mode_key] not in svg:
            print(f"  FAIL [{test_name}]: missing mode badge '{mode_key}'")
            all_ok = False
        if h36:
            if 'stroke="#fbbf24" stroke-width="4"' in svg:
                print(f"  FAIL [{test_name}]: fixed line drawn in curve mode")
                all_ok = False
        else:
            if 'stroke="#38bdf8" stroke-width="4"' in svg:
                print(f"  FAIL [{test_name}]: curve line drawn in fixed mode")
                all_ok = False
            if re.search(r'>\d\d</text>', svg):
                print(f"  FAIL [{test_name}]: curve tick values present in fixed mode")
                all_ok = False

        # 3b. Violet after-comp dot is gone (single-dot design)
        if "#a78bfa" in svg:
            print(f"  FAIL [{test_name}]: violet after-comp color still present")
            all_ok = False
        live_dots = re.findall(r'<circle[^>]*r="7"[^>]*>', svg)
        if len(live_dots) != 1:
            print(f"  FAIL [{test_name}]: expected exactly 1 live dot (r=7), got {len(live_dots)}")
            all_ok = False
        # 3c. Hysteresis band: 2 sub-band polygons + 2 dashed boundaries
        if svg.count("<polygon") < 2:
            print(f"  FAIL [{test_name}]: expected >=2 hysteresis band polygons")
            all_ok = False
        if 'stroke-dasharray="7 5"' not in svg:
            print(f"  FAIL [{test_name}]: no dashed hysteresis boundaries")
            all_ok = False
        # 3d. Threshold markers: dotted-outline circles + start/stop temps
        thr_markers = re.findall(r'<circle[^>]*stroke-dasharray="3 3"[^>]*>', svg)
        if len(thr_markers) != 2:
            print(f"  FAIL [{test_name}]: expected 2 dotted threshold markers, got {len(thr_markers)}")
            all_ok = False
        for key in ["legend_start", "legend_stop"]:
            if tl.get(key, "") not in svg:
                print(f"  FAIL [{test_name}]: missing threshold label '{key}'")
                all_ok = False

        # 4. No text overlap anywhere (same y-level, overlapping x-ranges).
        rows = {}
        for x, y, txt in texts:
            if not txt.strip():
                continue
            yr = round(float(y) / 12)
            tw = len(txt) * 9.4
            rows.setdefault(yr, []).append((float(x), float(x) + tw, txt))
        for yr, items in sorted(rows.items()):
            items.sort(key=lambda t: t[0])
            for i in range(len(items) - 1):
                a, b = items[i], items[i + 1]
                if a[1] > b[0]:
                    print(f"  FAIL [{test_name}]: overlap y~{yr*12}: '{a[2][:40]}' vs '{b[2][:20]}'")
                    all_ok = False

        # 5. Polyline present
        if '<polyline' not in svg:
            print(f"  FAIL [{test_name}]: no polyline")
            all_ok = False

        # 5b. Stat footer: caption cells present (uppercase captions, fs 12)
        caps = re.findall(r'font-size="13"[^>]*>([^<]+)</text>', svg)
        if len(caps) < 4:
            print(f"  FAIL [{test_name}]: stat footer captions missing, got {caps}")
            all_ok = False
        # 5c. Line labels sit inside the canvas right edge (skip end/middle-anchored)
        anchored = re.findall(r'<text[^>]*text-anchor="(?:end|middle)"[^>]*>([^<]*)</text>', svg)
        for x, y, txt in texts:
            if txt.strip() and txt not in anchored and float(x) + len(txt) * 9.4 > 1200:
                print(f"  FAIL [{test_name}]: label past right edge: '{txt[:30]}'")
                all_ok = False

        # 5d. Dotted connector lines from live AT to chart (when H36 is enabled)
        if h36 == 1 and at_live is not None and "stroke-dasharray=\"6 4\"" not in svg:
            print(f"  FAIL [{test_name}]: no dotted connector lines for live labels")
            all_ok = False
        # vector-crisp: no raster filters (they blur on phone GPUs when the
        # image scales down); floating labels use a paint-order halo instead
        if "feDropShadow" in svg or "url(#ts)" in svg:
            print(f"  FAIL [{test_name}]: raster drop-shadow filter present (blurs on mobile)")
            all_ok = False
        if "paint-order" not in svg:
            print(f"  FAIL [{test_name}]: no paint-order halo on floating labels")
            all_ok = False

        # 7. Font sizes are large enough for small screens (min 13 for any text)
        small_fonts = re.findall(r'font-size="(\d+)"', svg)
        small_fonts = [int(f) for f in small_fonts if int(f) < 13]
        if small_fonts:
            print(f"  FAIL [{test_name}]: font-size below 13: {small_fonts}")
            all_ok = False

        # 8. Full-canvas text overlap across hysteresis extremes (R04/R05 shape
        #    the band + threshold pills; tight/wide/asymmetric combos must never
        #    collide and nothing may leave the 1200x760 canvas). Rotated axis
        #    titles are excluded (their visual box is vertical, not horizontal).
        for r04v, r05v in [(0.5, 0.5), (0.2, 4.0), (10.0, 10.0)]:
            coord_v = FakeCoord(make_data(at_live, after, h36))
            coord_v.data[1160] = {"value": r04v}
            coord_v.data[1161] = {"value": r05v}
            obj_v = img.FoxAirHeatingCurveImage(coord_v, "test")
            obj_v.hass = FHass()
            obj_v._tl = {**img._TL_FALLBACK, **tl}
            obj_v._render()
            svg_v = obj_v._image_bytes.decode("utf-8")
            vtags = [t for t in re.findall(r'(<text[^>]*>[^<]*</text>)', svg_v)
                     if 'rotate' not in t]
            vboxes = []
            for vtag in vtags:
                vm = re.search(r'x="([\d.]+)".*?y="([\d.]+)".*?font-size="(\d+)"', vtag)
                vtm = re.search(r'>([^<]*)</text>', vtag)
                if vm is None or vtm is None:
                    continue
                vt = vtm.group(1)
                # same script-aware width as image.py _text_w (cyrillic wider)
                _vfac = 0.72 if any("Ѐ" <= _c <= "џ" for _c in vt) else 0.62
                vx, vy, vfs = float(vm.group(1)), float(vm.group(2)), int(vm.group(3))
                if vx < -50 or vx > 1250 or vy < -20 or vy > 780:
                    print(f"  FAIL [{test_name} R04={r04v} R05={r05v}]: out-of-window '{vt}' at {vx},{vy}")
                    all_ok = False
                vboxes.append((vx, vy, len(vt) * vfs * _vfac, vt, vtag))
            for vi in range(len(vboxes)):
                for vj in range(vi + 1, len(vboxes)):
                    vx1, vy1, vw1, vt1, va1 = vboxes[vi]
                    vx2, vy2, vw2, vt2, va2 = vboxes[vj]
                    if abs(vy1 - vy2) > 12:
                        continue

                    def _span(wx, ww, wtag):
                        if 'text-anchor="middle"' in wtag:
                            return (wx - ww / 2, wx + ww / 2)
                        if 'text-anchor="end"' in wtag:
                            return (wx - ww, wx)
                        return (wx, wx + ww)

                    vl1, vr1 = _span(vx1, vw1, va1)
                    vl2, vr2 = _span(vx2, vw2, va2)
                    if vl1 < vr2 - 2 and vl2 < vr1 - 2:
                        print(f"  FAIL [{test_name} R04={r04v} R05={r05v}]: overlap '{vt1}' vs '{vt2}'")
                        all_ok = False

        print(f"  OK [{test_name}]")

# Switch gating: the card always shows the heating water side. H36 draws the
# curve only while heating from a water source; the y-axis names the H25 sensor.
_mv = MARKERS["status"]["mode_values"]
_mode_addr = MARKERS["status"]["addr_single"]["mode"]
_cs = MARKERS["control_source"]
_sel = _cs["addr_single"]["selector"]
_code = METADATA[str(_sel)]["code"].lower()
_src_tl = {f"source.{k}": f"AXIS {k}" for k in (e["key"] for e in _cs["by_value"].values())}
for h25, src in sorted(_cs["by_value"].items()):
    for label, mode in (("heating", _mv["heating"]), ("cooling", _mv["cooling"])):
        d = make_data(0.0, 37.0, 1)
        d[_mode_addr] = {"raw": mode, "value": mode}
        d[_sel] = {"raw": int(h25), "value": int(h25)}
        obj = img.FoxAirHeatingCurveImage(FakeCoord(d), "test")
        obj.hass = FHass()
        obj._tl = {**img._TL_FALLBACK, **EN_TL, **_src_tl}
        obj._last_inputs = obj._read_inputs()
        obj._render()
        svg = obj._image_bytes.decode("utf-8")
        want = "mode_curve" if label == "heating" and not src.get("target") else "mode_fixed"
        axis = EN_TL["axis_y"] if src.get("target") else f"AXIS {src['key']}"
        name = f"switch gating H25={h25}/{src['key']} {label}"
        problems = [p for p, ok in ((EN_TL[want], EN_TL[want] in svg), (axis, axis in svg)) if not ok]
        if problems:
            print(f"  FAIL [{name}]: missing {problems}")
            all_ok = False
        else:
            print(f"  OK [{name}]")

print(f"\n{'='*60}")
print("  ALL TESTS PASSED" if all_ok else "  SOME TESTS FAILED")
print(f"{'='*60}")
sys.exit(0 if all_ok else 1)
