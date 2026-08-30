"""Image platform — heating curve on the device page (no YAML needed).

Renders image.foxair_heating_curve on the FoxAir Heat Pump device.
Pure SVG (no Pillow). Redraws only when a curve-affecting input changes,
otherwise keeps the last image (cheap caching) — so changing slope/offset
or the live outdoor temp updates the picture, but unrelated polls don't.

All user-visible text is pulled from HA translations (entity.image.
foxair_heating_curve.*) so it follows the UI language; English is the
fallback. The layout avoids in-plot floating labels (the historical overlap
source) and uses a single bottom legend strip with color swatches that
clearly separates the VARIABLE curve target from the CONSTANT fixed setpoint.

Mode (driven by H36 / register 1236):
  * H36 = 1  -> AT-compensation (curve) mode:
                target(AT) = offset - slope * AT, clamped to [R10, R11]
                drawn as the main cyan curve line.
  * H36 = 0  -> constant (fixed) mode:
                target = R02 (register 1158), drawn as amber line.
                Weather-compensation curve shown faintly as a preview.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.translation import async_get_translations

from .const import main_device
from .heating_curve import calc_curve_target, curve_target_for_at

_LOGGER = logging.getLogger(__name__)

# AT range shown on the X axis
AT_MIN, AT_MAX = -30.0, 20.0

# English fallback so the image always renders even before translations load.
_TL_FALLBACK = {
    "name": "Heating Curve",
    "legend_curve": "Curve target (AT compensation)",
    "legend_fixed": "Fixed setpoint (constant)",
    "legend_after": "After compensation (live)",
    "legend_live": "Live outdoor temperature",
    "legend_band": "Limit band (R10–R11)",
    "mode_curve": "AT compensation (curve)",
    "mode_fixed": "Constant (fixed)",
    "wait": "Waiting for data",
    "wait_sub": "First poll in progress (quick 30 s)",
    "axis_x": "Outdoor temperature (AT)",
    "axis_y": "Flow temperature",
}


def _norm_slope(v):
    """Normalise slope to a sane 0..3 range.

    Live value is already scaled (DIGI5 -> /10) so a typical value is 0.0..3.0.
    If something upstream left it raw (0..30 or 0..100) divide by 10, then clamp.
    """
    try:
        s = float(v)
    except (TypeError, ValueError):
        return 0.6
    if s > 3.0:
        s = s / 10.0
    if s < 0:
        s = 0.0
    return min(s, 3.0)


class FoxAirHeatingCurveImage(CoordinatorEntity, ImageEntity):
    _attr_has_entity_name = False
    _attr_name = "Heating Curve"
    _attr_icon = "mdi:chart-bell-curve"
    _attr_content_type = "image/svg+xml"
    _attr_translation_key = "foxair_heating_curve"

    def __init__(self, coordinator, entry_id: str):
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_heating_curve_image"
        self._attr_device_info = main_device(entry_id)
        self.entity_id = "image.foxair_heating_curve"
        self._image_bytes: bytes | None = None
        self._image_last_updated: datetime | None = None
        # Last inputs used to render; None until first attempt.
        self._last_inputs: dict | None = None
        # Translation catalog (flattened "component.foxair.entity.image.
        # foxair_heating_curve.*" -> value), English-fallback merged.
        self._tl: dict = {}
        # Draw the initial state (Waiting for data) so card isn't blank.
        self._render()

    @property
    def image_last_updated(self):
        return self._image_last_updated

    async def async_image(self) -> bytes | None:
        if self._image_bytes is None:
            self._render()
        return self._image_bytes

    async def async_load_translations(self) -> None:
        """Load the image's translation catalog for the current UI language."""
        try:
            lang = self.hass.config.language or "en"
            cat = await async_get_translations(
                self.hass, lang, category="entity", integrations=["foxair"]
            )
            prefix = "component.foxair.entity.image.foxair_heating_curve."
            loaded = {k[len(prefix):]: v for k, v in cat.items() if k.startswith(prefix)}
            self._tl = {**_TL_FALLBACK, **loaded}
        except Exception as e:  # pragma: no cover - never fatal
            _LOGGER.debug("heating-curve translations unavailable: %s", e)
            self._tl = dict(_TL_FALLBACK)

    def _t(self, key: str) -> str:
        return self._tl.get(key, _TL_FALLBACK.get(key, key))

    # ── data helpers ────────────────────────────────────────────
    def _read_inputs(self) -> dict:
        coord = self.coordinator
        d = getattr(coord, "data", None) or {}

        def val(addr, default=None):
            if not addr:
                return default
            rec = d.get(addr)
            if not rec:
                return default
            v = rec.get("value")
            return v if v is not None else default

        def raw(addr):
            if not addr:
                return None
            rec = d.get(addr)
            if not rec:
                return None
            return rec.get("raw")

        hc = (coord.marker("heat_curve") if hasattr(coord, "marker") else None) or {}
        hca = hc.get("addr_single", {}) or {}
        st = (coord.marker("setpoints") if hasattr(coord, "marker") else None) or {}
        sta = st.get("addr_single", {}) or {}

        slope = val(hca.get("slope"), None)
        offset = val(hca.get("offset"), None)
        fixed = val(sta.get("heating_target"), None)
        h36 = raw(hca.get("at_comp_en"))
        at_live = val(hca.get("at_sensor"), None)
        after = val(hca.get("live_target"), None)
        r10 = val(hca.get("r10_min"), None)
        r11 = val(hca.get("r11_max"), None)

        ready = (slope is not None) and (offset is not None) and (fixed is not None)
        return {
            "slope": slope, "offset": offset, "fixed": fixed,
            "h36": h36, "at_live": at_live, "after": after,
            "r10": r10, "r11": r11, "ready": ready,
        }

    def _handle_coordinator_update(self) -> None:
        new = self._read_inputs()
        if new != self._last_inputs:
            self._last_inputs = new
            self._render()
            self.async_write_ha_state()
        super()._handle_coordinator_update()

    # ── rendering ──────────────────────────────────────────────
    def _render(self):
        W, H = 1200, 720
        pad_l, pad_r, pad_t, pad_b = 90, 50, 64, 96
        legend_h = 96
        plot_w = W - pad_l - pad_r
        plot_h = H - pad_t - pad_b - legend_h
        plot_right = W - pad_r
        plot_bottom = H - pad_b - legend_h

        def x_at(v: float) -> float:
            return pad_l + (v - AT_MIN) / (AT_MAX - AT_MIN) * plot_w

        def y_flow(v: float) -> float:
            lo_f, hi_f = 10.0, 70.0
            return pad_t + (hi_f - v) / (hi_f - lo_f) * plot_h

        def clamp(v, lo, hi):
            if lo is None:
                lo = 20.0
            if hi is None:
                hi = 60.0
            return max(lo, min(hi, v))

        inp = self._last_inputs or self._read_inputs()
        ready = inp.get("ready", False)

        def _f(key, default):
            v = inp.get(key)
            if v is None:
                return float(default)
            try:
                return float(v)
            except (TypeError, ValueError):
                return float(default)

        slope = _norm_slope(_f("slope", 0.6))
        offset = _f("offset", 0.0)
        fixed = _f("fixed", 35.0)
        r10 = _f("r10", 20.0)
        r11 = _f("r11", 60.0)
        at_live = inp.get("at_live")
        after_comp = inp.get("after")
        h36_raw = inp.get("h36")
        is_curve_mode = h36_raw != 0

        BG = "#0f172a"
        GRID = "#1e293b"
        GRID_MINOR = "#172033"
        AXIS = "#334155"
        TEXT = "#94a3b8"
        TEXT_DARK = "#e2e8f0"
        CURVE = "#38bdf8"
        CURVE_FILL = "rgba(14,165,233,0.08)"
        FIXED_COL = "#fbbf24"
        DOT = "#22c55e"
        AFTER_COL = "#a78bfa"
        LOADING_BG = "#020617"

        svg = []

        # ---- loading overlay (only while essential data is missing) ----
        if not ready:
            svg.append(
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
                f'viewBox="0 0 {W} {H}" font-family="sans-serif">'
            )
            svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')
            svg.append(
                f'<rect x="0" y="0" width="{W}" height="{H}" fill="{LOADING_BG}" opacity="0.95"/>'
            )
            svg.append(
                f'<text x="{W // 2}" y="{H // 2 - 10}" text-anchor="middle" '
                f'fill="{TEXT_DARK}" font-size="24">{self._t("wait")}</text>'
            )
            svg.append(
                f'<text x="{W // 2}" y="{H // 2 + 20}" text-anchor="middle" '
                f'fill="{TEXT}" font-size="14">{self._t("wait_sub")}</text>'
            )
            svg.append('</svg>')
            self._image_bytes = "".join(svg).encode("utf-8")
            self._image_last_updated = datetime.now(timezone.utc)
            return

        # ---- live computed target (for the moving dot) ----
        target_live = None
        if at_live is not None and self.coordinator is not None:
            try:
                target_live = curve_target_for_at(self.coordinator, float(at_live))
            except Exception as e:
                _LOGGER.debug("curve target calc failed %s", e)
                target_live = None

        svg.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="sans-serif">'
        )
        svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')

        # ---- title (short, translated) ----
        svg.append(
            f'<text x="{W // 2}" y="34" text-anchor="middle" fill="{TEXT_DARK}" '
            f'font-size="22" font-weight="bold">{self._t("name")}</text>'
        )

        # ---- grid ----
        for at_g in range(-30, 21, 5):
            x = round(x_at(at_g), 1)
            stroke = GRID if at_g % 10 == 0 else GRID_MINOR
            sw = "1.5" if at_g % 10 == 0 else "1"
            svg.append(
                f'<line x1="{x}" y1="{pad_t}" x2="{x}" y2="{plot_bottom}" '
                f'stroke="{stroke}" stroke-width="{sw}"/>'
            )
        for f in range(10, 71, 5):
            y = round(y_flow(f), 1)
            stroke = GRID if f % 10 == 0 else GRID_MINOR
            sw = "1.5" if f % 10 == 0 else "1"
            svg.append(
                f'<line x1="{pad_l}" y1="{y}" x2="{plot_right}" y2="{y}" '
                f'stroke="{stroke}" stroke-width="{sw}"/>'
            )

        # ---- axes ----
        svg.append(
            f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{plot_bottom}" '
            f'stroke="{AXIS}" stroke-width="2"/>'
        )
        svg.append(
            f'<line x1="{pad_l}" y1="{plot_bottom}" x2="{plot_right}" '
            f'y2="{plot_bottom}" stroke="{AXIS}" stroke-width="2"/>'
        )

        # ---- reference cross at design point (AT=0 -> flow=offset) ----
        try:
            x0 = round(x_at(0.0), 1)
            y0 = round(y_flow(offset), 1)
            svg.append(
                f'<line x1="{x0}" y1="{pad_t}" x2="{x0}" y2="{plot_bottom}" '
                f'stroke="#e2e8f0" stroke-width="1.5" stroke-dasharray="3 5" opacity="0.4"/>'
            )
            svg.append(
                f'<line x1="{pad_l}" y1="{y0}" x2="{plot_right}" y2="{y0}" '
                f'stroke="#e2e8f0" stroke-width="1.5" stroke-dasharray="3 5" opacity="0.4"/>'
            )
            svg.append(
                f'<circle cx="{x0}" cy="{y0}" r="6" fill="#e2e8f0" '
                f'stroke="{BG}" stroke-width="2"/>'
            )
        except Exception:
            pass

        # ---- X axis ticks (tick marks + dots + labels) ----
        for at_g in (-30, -20, -10, 0, 10, 20):
            x = round(x_at(at_g), 1)
            # small dot on the axis line itself
            svg.append(
                f'<circle cx="{x}" cy="{plot_bottom}" r="3" fill="{AXIS}"/>'
            )
            # tick mark extending downward from axis
            svg.append(
                f'<line x1="{x}" y1="{plot_bottom}" x2="{x}" y2="{plot_bottom + 6}" '
                f'stroke="{TEXT}" stroke-width="1"/>'
            )
            label = f"0C->{offset:.0f}C" if at_g == 0 else f"{at_g}C"
            svg.append(
                f'<text x="{x}" y="{plot_bottom + 20}" text-anchor="middle" '
                f'fill="{TEXT_DARK if at_g == 0 else TEXT}" font-size="14" '
                f'font-weight="bold">{label}</text>'
            )

        # ---- Y axis ticks (tick marks + labels) ----
        for f in (10, 20, 30, 40, 50, 60, 70):
            y = round(y_flow(f), 1)
            # small dot on the axis line itself
            svg.append(
                f'<circle cx="{pad_l}" cy="{y}" r="3" fill="{AXIS}"/>'
            )
            # tick mark extending left from axis
            svg.append(
                f'<line x1="{pad_l - 6}" y1="{y}" x2="{pad_l}" y2="{y}" '
                f'stroke="{TEXT}" stroke-width="1"/>'
            )
            svg.append(
                f'<text x="{pad_l - 12}" y="{y + 5}" text-anchor="end" '
                f'fill="{TEXT}" font-size="14">{f}C</text>'
            )

        # ---- axis titles ----
        svg.append(
            f'<text x="{pad_l + plot_w // 2}" y="{plot_bottom + 38}" text-anchor="middle" '
            f'fill="{TEXT}" font-size="14">{self._t("axis_x")}</text>'
        )
        svg.append(
            f'<text x="26" y="{pad_t + plot_h // 2}" text-anchor="middle" fill="{TEXT}" '
            f'font-size="14" transform="rotate(-90 26, {pad_t + plot_h // 2})">{self._t("axis_y")}</text>'
        )

        # ---- min/max band ----
        band_top = round(y_flow(r11), 1)
        band_bot = round(y_flow(r10), 1)
        band_h = max(band_bot - band_top, 1)
        svg.append(
            f'<rect x="{pad_l}" y="{band_top}" width="{plot_w}" '
            f'height="{band_h}" fill="{CURVE_FILL}"/>'
        )

        # ---- curve polyline ----
        curve_pts = []
        for i in range(int(AT_MIN * 2), int(AT_MAX * 2) + 1):
            at_step = i / 2.0
            raw_val = calc_curve_target(at_step, slope, offset, base=0.0)
            c = clamp(raw_val, r10, r11)
            curve_pts.append((round(x_at(at_step), 1), round(y_flow(c), 1)))
        poly_pts = " ".join(f"{x},{y}" for x, y in curve_pts)
        poly_fill = " ".join(
            f"{x},{y}"
            for x, y in curve_pts
            + [(curve_pts[-1][0], plot_bottom), (curve_pts[0][0], plot_bottom)]
        )

        # ---- main line + preview ----
        if is_curve_mode:
            svg.append(f'<polygon points="{poly_fill}" fill="{CURVE_FILL}"/>')
            svg.append(
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="4" '
                f'stroke-linejoin="round" points="{poly_pts}"/>'
            )
            fixed_y = round(y_flow(clamp(fixed, r10, r11)), 1)
            svg.append(
                f'<line x1="{pad_l}" y1="{fixed_y}" x2="{plot_right}" y2="{fixed_y}" '
                f'stroke="{FIXED_COL}" stroke-width="2" stroke-dasharray="8 6" opacity="0.45"/>'
            )
        else:
            fixed_y = round(y_flow(clamp(fixed, r10, r11)), 1)
            svg.append(
                f'<line x1="{pad_l}" y1="{fixed_y}" x2="{plot_right}" y2="{fixed_y}" '
                f'stroke="{FIXED_COL}" stroke-width="4"/>'
            )
            svg.append(
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="2" '
                f'stroke-dasharray="8 6" opacity="0.4" points="{poly_pts}"/>'
            )

        # ---- live AT dot + clamped label ----
        if at_live is not None and target_live is not None:
            dx = round(x_at(float(at_live)), 1)
            dy = round(y_flow(float(target_live)), 1)
            # keep the dot inside the plot
            dx = max(pad_l + 14, min(plot_right - 14, dx))
            dy = max(pad_t + 14, min(plot_bottom - 14, dy))
            svg.append(
                f'<circle cx="{dx}" cy="{dy}" r="9" fill="#fff" opacity="0.9"/>'
            )
            svg.append(
                f'<circle cx="{dx}" cy="{dy}" r="7" fill="{DOT}" stroke="#fff" '
                f'stroke-width="2"/>'
            )
            # label always to the LEFT of the dot, clamped so it never
            # overlaps the reference cross at AT=0 or runs off-canvas
            label_w = len(f"AT {float(at_live):.1f}C -> {float(target_live):.1f}C") * 7
            tx = max(pad_l + 6, dx - 12 - label_w)
            ty = max(pad_t + 16, min(plot_bottom - 6, dy - 12))
            txt = f"AT {float(at_live):.1f}C -> {float(target_live):.1f}C"
            svg.append(
                f'<text x="{tx}" y="{ty}" text-anchor="end" '
                f'fill="{DOT}" font-size="14" font-weight="bold">{txt}</text>'
            )
            if after_comp is not None:
                ay = round(y_flow(float(after_comp)), 1)
                ay = max(pad_t + 12, min(plot_bottom - 12, ay))
                svg.append(
                    f'<circle cx="{dx}" cy="{ay}" r="5" fill="{AFTER_COL}" '
                    f'stroke="#fff" stroke-width="1.5"/>'
                )
                # after-comp label below the dot; place left or right to stay on-canvas
                a_label = f"{self._t('legend_after')}: {float(after_comp):.1f}C"
                a_w = len(a_label) * 6.2
                if dx + 10 + a_w > plot_right - 6:
                    # place to the left of the dot
                    a_tx = max(pad_l + 6, dx - 10 - a_w)
                    a_anchor = "end"
                else:
                    a_tx = dx + 10
                    a_anchor = "start"
                a_ty = min(plot_bottom - 6, ay + 16)
                svg.append(
                    f'<text x="{a_tx}" y="{a_ty}" text-anchor="{a_anchor}" '
                    f'fill="{AFTER_COL}" font-size="12">{a_label}</text>'
                )

        # ── legend strip (bottom) ──
        # Two-row layout: top row = 4 swatch+label pairs (flowing left);
        # bottom row = compact summary (left-aligned). This avoids any
        # right-edge collision between long legend labels and the summary.
        # Gap the legend below the X axis title (at plot_bottom + 38).
        ly_top = plot_bottom + 56
        ly_bot = plot_bottom + 88
        svg.append(
            f'<rect x="{pad_l}" y="{plot_bottom + 46}" width="{plot_w}" '
            f'height="{legend_h - 8}" fill="#020617" stroke="{AXIS}" rx="6"/>'
        )
        # swatch helper: draws swatch at x, then text label; returns x after swatch
        def _legend_item(x, color, label, active=False, is_line=True, dash=False):
            dash_frag = ' stroke-dasharray="6 4"' if dash else ""
            opacity = 1.0 if active else 0.5
            if is_line:
                svg.append(
                    f'<line x1="{x}" y1="{ly_top}" x2="{x + 22}" y2="{ly_top}" '
                    f'stroke="{color}" stroke-width="4"{dash_frag} opacity="{opacity}"/>'
                )
            else:
                svg.append(
                    f'<circle cx="{x + 11}" cy="{ly_top}" r="6" fill="{color}" '
                    f'opacity="{1.0 if active else 0.6}"/>'
                )
            return x + 30

        # Helper: measure text width for SVG (approx using char count * factor).
        # At font-size 13, average char width ~6.8px for latin, ~8.5 for cyrillic.
        # We use a generous factor and measure the label string length.
        def _text_w(label, font_size=13):
            # heuristic: 0.6 * font_size per char (works for latin + cyrillic)
            return len(label) * font_size * 0.62

        # 1) curve target — emphasized when in curve mode
        x = pad_l + 16
        x = _legend_item(x, CURVE, self._t("legend_curve"), active=is_curve_mode, dash=not is_curve_mode)
        _op = "" if is_curve_mode else ' opacity="0.6"'
        svg.append(
            f'<text x="{x}" y="{ly_top + 5}" fill="{TEXT_DARK if is_curve_mode else TEXT}" '
            f'font-size="13"{_op}>{self._t("legend_curve")}</text>'
        )
        x += _text_w(self._t("legend_curve")) + 38
        # 2) fixed setpoint — emphasized when in fixed mode
        x = _legend_item(x, FIXED_COL, self._t("legend_fixed"), active=not is_curve_mode, dash=is_curve_mode)
        _op2 = "" if not is_curve_mode else ' opacity="0.6"'
        svg.append(
            f'<text x="{x}" y="{ly_top + 5}" fill="{TEXT_DARK if not is_curve_mode else TEXT}" '
            f'font-size="13"{_op2}>{self._t("legend_fixed")}</text>'
        )
        x += _text_w(self._t("legend_fixed")) + 38
        # 3) after compensation (violet dot)
        x = _legend_item(x, AFTER_COL, self._t("legend_after"), is_line=False)
        svg.append(
            f'<text x="{x}" y="{ly_top + 5}" fill="{TEXT}" font-size="13">'
            f'{self._t("legend_after")}</text>'
        )
        x += _text_w(self._t("legend_after")) + 38
        # 4) live AT (green dot)
        x = _legend_item(x, DOT, self._t("legend_live"), is_line=False)
        svg.append(
            f'<text x="{x}" y="{ly_top + 5}" fill="{TEXT}" font-size="13">'
            f'{self._t("legend_live")}</text>'
        )

        # compact summary on the bottom row, left-aligned (never conflicts)
        summary = (
            f'slope {slope:.2f}  ·  offset {offset:.1f}C  ·  '
            f'{self._t("legend_band")}: {r10:.0f}–{r11:.0f}C  ·  '
            f'{self._t("mode_curve" if is_curve_mode else "mode_fixed")}'
        )
        svg.append(
            f'<text x="{pad_l + 8}" y="{ly_bot + 4}" fill="{TEXT}" '
            f'font-size="12">{summary}</text>'
        )

        svg.append("</svg>")
        self._image_bytes = "".join(svg).encode("utf-8")
        self._image_last_updated = datetime.now(timezone.utc)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if not coord:
        return
    entity = FoxAirHeatingCurveImage(coord, entry.entry_id)
    await entity.async_load_translations()
    async_add_entities([entity])
