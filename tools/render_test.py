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
        if name == "heat_curve":
            return {"addr_single": {
                "slope": 1234, "offset": 1235, "at_comp_en": 1236,
                "at_sensor": 2048, "live_target": 2014,
                "r10_min": 1164, "r11_max": 1165,
            }}
        if name == "setpoints":
            return {"addr_single": {"heating_target": 1158}}
        return {}

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

        # 3. All legend labels present
        for key in ["legend_curve", "legend_fixed", "legend_heat", "legend_live"]:
            tl_val = tl.get(key, "")
            fb_val = img._TL_FALLBACK.get(key, "")
            found = tl_val in svg or fb_val in svg
            if not found:
                print(f"  FAIL [{test_name}]: missing legend key '{key}'")
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

        # 4. No legend overlap (same y-level, overlapping x-ranges).
        # Only the legend box counts (y>590): in-plot pills live above it.
        legend_texts = [(float(x), float(y), txt) for x, y, txt in texts if float(y) > 590]
        rows = {}
        for x, y, txt in legend_texts:
            yr = round(y)
            tw = len(txt) * 9.4  # ~0.62 * 15px font-size (latin + cyrillic)
            rows.setdefault(yr, []).append((x, x + tw, txt))
        for yr, items in sorted(rows.items()):
            items.sort(key=lambda t: t[0])
            for i in range(len(items) - 1):
                a, b = items[i], items[i + 1]
                if a[1] > b[0]:
                    print(f"  FAIL [{test_name}]: legend overlap at y={yr}: '{a[2][:40]}' vs '{b[2][:20]}'")
                    all_ok = False

        # 5. Polyline present
        if '<polyline' not in svg:
            print(f"  FAIL [{test_name}]: no polyline")
            all_ok = False

        # 5. Polyline present
        if '<polyline' not in svg:
            print(f"  FAIL [{test_name}]: no polyline")
            all_ok = False

        # 5b. Legend grid geometry: fixed 2x2 columns.
        # pad_l=90 -> col1=106, plot_w=1060 -> col2=636; labels start at
        # col+SWATCH_W(26)+GAP(8) = 140 / 670. Any other label x = drift bug.
        full_texts = re.findall(r'<text[^>]*x="([\d.]+)"[^>]*y="([\d.]+)"[^>]*font-size="(\d+)"[^>]*>([^<]*)</text>', svg)
        for x, y, fs, txt in full_texts:
            # legend item rows only (622/650); the summary line (676) is free
            if 590 < float(y) < 665 and fs == "15" and txt.strip():
                if min(abs(float(x) - 140), abs(float(x) - 670)) > 1.5:
                    print(f"  FAIL [{test_name}]: legend label off-grid x={x} '{txt[:20]}'")
                    all_ok = False

        # 5c. Legend marker types: >=2 line swatches (curve, fixed),
        #     1 live dot (r=6, solid) + 2 band-swatch rects (26x7, dashed edge).
        legend_lines = re.findall(r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"[^>]*stroke-width="4"', svg)
        legend_lines = [(float(x1), float(y1)) for x1, y1, x2, y2 in legend_lines if float(y1) > 590]
        legend_dots = []
        for m in re.findall(r'<circle[^>]*>', svg):
            if 'r="6"' in m and 'stroke-dasharray' not in m:
                _cy = re.search(r'cy="([\d.]+)"', m)
                if _cy and float(_cy.group(1)) > 590:
                    legend_dots.append(m)
        band_rects = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="26" height="7"', svg)

        # (marker counts already collected in 5b/5c above)
        if len(legend_lines) < 2:
            print(f"  FAIL [{test_name}]: expected >=2 legend line-swatch markers, got {len(legend_lines)}")
            all_ok = False
        if len(legend_dots) < 1:
            print(f"  FAIL [{test_name}]: expected >=1 legend dot marker (r=6), got {len(legend_dots)}")
            all_ok = False
        if len(band_rects) < 2:
            print(f"  FAIL [{test_name}]: expected 2 band-swatch rects (26x7), got {len(band_rects)}")
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

print(f"\n{'='*60}")
print("  ALL TESTS PASSED" if all_ok else "  SOME TESTS FAILED")
print(f"{'='*60}")
sys.exit(0 if all_ok else 1)
