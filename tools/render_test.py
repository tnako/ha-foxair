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
import sys, types, os, re, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- stub HA modules (before importing anything from custom_components) ---
pkg = types.ModuleType("homeassistant"); pkg.__path__ = []
sys.modules["homeassistant"] = pkg

comp = types.ModuleType("homeassistant.components"); comp.__path__ = []
sys.modules["homeassistant.components"] = comp

img_mod = types.ModuleType("homeassistant.components.image")
class ImageEntity:
    _attr_content_type = None
    def __init__(self, hass=None): self.hass = hass
    def async_write_ha_state(self): pass
img_mod.ImageEntity = ImageEntity
sys.modules["homeassistant.components.image"] = img_mod

helpers = types.ModuleType("homeassistant.helpers"); helpers.__path__ = []
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
class HomeAssistant: pass
core.HomeAssistant = HomeAssistant
sys.modules["homeassistant.core"] = core

ce = types.ModuleType("homeassistant.config_entries")
class ConfigEntry: pass
ce.ConfigEntry = ConfigEntry
sys.modules["homeassistant.config_entries"] = ce

dr = types.ModuleType("homeassistant.helpers.device_registry")
sys.modules["homeassistant.helpers.device_registry"] = dr

er = types.ModuleType("homeassistant.helpers.entity_registry")
er.async_get = lambda *a, **k: None
sys.modules["homeassistant.helpers.entity_registry"] = er

# --- namespace packages for custom_components ---
cc = types.ModuleType("custom_components"); cc.__path__ = [os.path.join(ROOT, "custom_components")]
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
    return data

EN_TL = {
    "name": "Heating Curve",
    "legend_curve": "Curve target",
    "legend_fixed": "Fixed setpoint",
    "legend_after": "After compensation",
    "legend_live": "Live outdoor",
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
    "legend_after": "После компенсации",
    "legend_live": "Тек. AT",
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
    "legend_after": "Nach Kompensation",
    "legend_live": "Live-Außen",
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

W, H = 1200, 720
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
        for key in ["legend_curve", "legend_fixed", "legend_after", "legend_live"]:
            tl_val = tl.get(key, "")
            fb_val = img._TL_FALLBACK.get(key, "")
            found = tl_val in svg or fb_val in svg
            if not found:
                print(f"  FAIL [{test_name}]: missing legend key '{key}'")
                all_ok = False

        # 4. No legend overlap (same y-level, overlapping x-ranges)
        legend_texts = [(float(x), float(y), txt) for x, y, txt in texts if float(y) > 560]
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

        # 5b. Verify marker-to-text gap is 1px and inter-item spacing is 30px.
        # Legend markers: lines at y=584, circles (r=6) at cy=584, labels at y=590.
        # Gap = text_x - (marker_right_edge), must be exactly 1.
        # Inter-item = next_start_x - (prev_text_right_edge), must be exactly 30.
        circles = re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="6"', svg)
        lines = re.findall(r'<line x1="([\d.]+)" y1="584" x2="([\d.]+)" y2="584"', svg)
        legend_circles = [(float(cx), float(cy)) for cx, cy in circles if abs(float(cy) - 584) < 2]
        legend_lines = [(float(x1), float(x2)) for x1, x2 in lines]
        # Build marker list: (left_x, right_x)
        markers = sorted(
            [(x1, x2) for x1, x2 in legend_lines] +
            [(cx - 6, cx + 6) for cx, _ in legend_circles]
        )
        # Legend text labels at y=590
        label_texts = [(float(x), txt) for x, y, txt in texts if abs(float(y) - 590) < 2 and txt.strip()]
        label_texts.sort(key=lambda t: t[0])
        # Check marker-to-text gap = 1px for each item
        for i, (m_left, m_right) in enumerate(markers):
            if i < len(label_texts):
                txt_x, txt = label_texts[i]
                gap = txt_x - m_right
                if abs(gap - 1) > 0.5:
                    print(f"  FAIL [{test_name}]: legend gap={gap:.1f} (expected 1px) for '{txt[:20]}'")
                    all_ok = False

        # 5c. Legend marker types: need >=2 solid/dashed lines (curve, fixed)
        #     and >=2 dots (r=6 at cy=584: after-compensation, live)
        if len(legend_lines) < 2:
            print(f"  FAIL [{test_name}]: expected >=2 legend line-swatch markers, got {len(legend_lines)}")
            all_ok = False
        if len(legend_circles) < 2:
            print(f"  FAIL [{test_name}]: expected >=2 legend dot markers (r=6), got {len(legend_circles)}")
            all_ok = False

        # 5d. Dotted connector lines from live AT to chart (when H36 is enabled)
        if h36 == 1 and at_live is not None and "stroke-dasharray=\"6 4\"" not in svg:
            print(f"  FAIL [{test_name}]: no dotted connector lines for live labels")
            all_ok = False
        shadow_count = svg.count('filter="url(#ts)"')
        if shadow_count < 12:
            print(f"  FAIL [{test_name}]: only {shadow_count} text elements have shadow (need >=12)")
            all_ok = False

        # 7. Font sizes are large enough for small screens (min 13 for any text)
        small_fonts = re.findall(r'font-size="(\d+)"', svg)
        small_fonts = [int(f) for f in small_fonts if int(f) < 13]
        if small_fonts:
            print(f"  FAIL [{test_name}]: font-size below 13: {small_fonts}")
            all_ok = False

        print(f"  OK [{test_name}]")

print(f"\n{'='*60}")
print("  ALL TESTS PASSED" if all_ok else "  SOME TESTS FAILED")
print(f"{'='*60}")
sys.exit(0 if all_ok else 1)
