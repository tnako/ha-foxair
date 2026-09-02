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

from .const import main_device, get_device_prefix
from .heating_curve import calc_curve_target, curve_target_for_at

_LOGGER = logging.getLogger(__name__)

# AT range shown on the X axis
AT_MIN, AT_MAX = -30.0, 20.0

# English fallback so the image always renders even before translations load.
_TL_FALLBACK = {
    "name": "Heating Curve",
    "legend_curve": "Curve target",
    "legend_fixed": "Fixed setpoint",
    "legend_after": "After compensation",
    "legend_live": "Live outdoor",
    "legend_band": "Limit band",
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

    def __init__(self, coordinator, entry_id: str):
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._entry_id = entry_id
        prefix = get_device_prefix(coordinator.entry)
        self._attr_translation_key = f"{prefix}_heating_curve"
        self._attr_unique_id = f"{prefix}_heating_curve_image"
        self._attr_device_info = main_device(entry_id, prefix)
        self.entity_id = f"image.{prefix}_heating_curve"
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
            loaded_raw = {k[len(prefix):]: v for k, v in cat.items() if k.startswith(prefix)}
            # hassfest only allows custom strings under `state`, so strip that prefix
            # (keep `name` as-is, unwrap `state.<key>` -> `<key>`)
            loaded = {}
            for k, v in loaded_raw.items():
                if k == "name":
                    loaded[k] = v
                elif k.startswith("state."):
                    loaded[k[6:]] = v
                else:
                    loaded[k] = v  # fallback for direct keys (future compat)
            self._tl = {**_TL_FALLBACK, **loaded}
        except Exception as e:  # pragma: no cover - never fatal
            _LOGGER.debug("heating-curve translations unavailable: %s", e)
            self._tl = dict(_TL_FALLBACK)

    def _t(self, key: str) -> str:
        return self._tl.get(key, _TL_FALLBACK.get(key, key))

    # -- data helpers -------------------------------------------------
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

    # -- rendering ---------------------------------------------------
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

        # Heuristic: estimate rendered text width in SVG.
        # At font-size 15, latin chars ~8px, cyrillic ~10px.
        # We use 0.6 * font_size * len(label) as a conservative estimate.
        def _text_w(label, font_size=15):
            return len(label) * font_size * 0.62

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
            svg.append(
                '<defs><filter id="ts" x="-20%" y="-20%" width="140%" height="140%">'
                '<feDropShadow dx="0" dy="1" stdDeviation="2" '
                f'flood-color="{BG}" flood-opacity="0.9"/>'
                "</filter></defs>"
            )
            svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')
            svg.append(
                f'<rect x="0" y="0" width="{W}" height="{H}" fill="{LOADING_BG}" opacity="0.95"/>'
            )
            svg.append(
                f'<text x="{W // 2}" y="{H // 2 - 10}" text-anchor="middle" '
                f'fill="{TEXT_DARK}" font-size="26" filter="url(#ts)">{self._t("wait")}</text>'
            )
            svg.append(
                f'<text x="{W // 2}" y="{H // 2 + 30}" text-anchor="middle" '
                f'fill="{TEXT}" font-size="17" filter="url(#ts)">{self._t("wait_sub")}</text>'
            )
            svg.append("</svg>")
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
        svg.append(
            '<defs><filter id="ts" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy="1" stdDeviation="2" '
            f'flood-color="{BG}" flood-opacity="0.9"/>'
            "</filter></defs>"
        )
        svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')

        # ---- title ----
        svg.append(
            f'<text x="{W // 2}" y="34" text-anchor="middle" fill="{TEXT_DARK}" '
            f'font-size="26" font-weight="bold" filter="url(#ts)">{self._t("name")}</text>'
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
            svg.append(
                f'<circle cx="{x}" cy="{plot_bottom}" r="3" fill="{AXIS}"/>'
            )
            svg.append(
                f'<line x1="{x}" y1="{plot_bottom}" x2="{x}" y2="{plot_bottom + 6}" '
                f'stroke="{TEXT}" stroke-width="1"/>'
            )
            label = f"0C->{offset:.0f}C" if at_g == 0 else f"{at_g}C"
            svg.append(
                f'<text x="{x}" y="{plot_bottom + 20}" text-anchor="middle" '
                f'fill="{TEXT_DARK if at_g == 0 else TEXT}" font-size="16" '
                f'font-weight="bold" filter="url(#ts)">{label}</text>'
            )

        # ---- curve value labels at each AT tick (bold, above the curve) ----
        for at_g in (-30, -20, -10, 0, 10, 20):
            x = round(x_at(at_g), 1)
            cv = clamp(calc_curve_target(at_g, slope, offset, base=0.0), r10, r11)
            yv = round(y_flow(cv), 1)
            svg.append(
                f'<text x="{x}" y="{yv - 8}" text-anchor="middle" '
                f'fill="{TEXT_DARK}" font-size="15" font-weight="bold" filter="url(#ts)">'
                f'{cv:.0f}</text>'
            )

        # ---- Y axis ticks (tick marks + labels) ----
        for f in (10, 20, 30, 40, 50, 60, 70):
            y = round(y_flow(f), 1)
            svg.append(
                f'<circle cx="{pad_l}" cy="{y}" r="3" fill="{AXIS}"/>'
            )
            svg.append(
                f'<line x1="{pad_l - 6}" y1="{y}" x2="{pad_l}" y2="{y}" '
                f'stroke="{TEXT}" stroke-width="1"/>'
            )
            svg.append(
                f'<text x="{pad_l - 12}" y="{y + 5}" text-anchor="end" '
                f'fill="{TEXT}" font-size="16" filter="url(#ts)">{f}C</text>'
            )

        # ---- axis titles ----
        svg.append(
            f'<text x="{pad_l + plot_w // 2}" y="{plot_bottom + 38}" text-anchor="middle" '
            f'fill="{TEXT}" font-size="16" filter="url(#ts)">{self._t("axis_x")}</text>'
        )
        svg.append(
            f'<text x="26" y="{pad_t + plot_h // 2}" text-anchor="middle" fill="{TEXT}" '
            f'font-size="16" transform="rotate(-90 26, {pad_t + plot_h // 2})" filter="url(#ts)">'
            f'{self._t("axis_y")}</text>'
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

        # ---- live AT dot + label with background pill ----
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

            # ---- live AT label (green pill, placed above or below the dot) ----
            txt = f"AT {float(at_live):.1f}C -> {float(target_live):.1f}C"
            txt_len = max(len(txt), 12)
            txt_w = _text_w(txt, font_size=16)
            pill_pad = 8
            pill_h = 26  # taller for better vertical centering
            pill_w = txt_w + pill_pad * 2

            # Extended connector: 3-7x longer than before.
            # Vertical span = the gap between dot edge and pill, multiplied dynamically.
            dot_r = 7  # match the circle r above

            # Try placing above the dot first
            conn_min = 20  # min connector length
            conn_max = 60  # max connector length
            base_conn = max(conn_min, min(conn_max, txt_len * 4))  # 2-5x scale

            pill_y_above = dy - base_conn - pill_h / 2
            if pill_y_above < pad_t + 8:
                pill_y_above = None  # not enough room, place below

            if pill_y_above is not None:
                pill_y = round(pill_y_above, 1)
                # long dotted line from dot top up to pill bottom
                line_len = dy - dot_r - (pill_y + pill_h)
                if line_len < conn_min:
                    line_len = conn_min
                svg.append(
                    f'<line x1="{dx}" y1="{dy - dot_r}" x2="{dx}" y2="{pill_y + pill_h}" '
                    f'stroke="{DOT}" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.7"/>'
                )
            else:
                # place below the dot
                pill_y = round(dy + base_conn + dot_r, 1)
                line_len = pill_y - (dy + dot_r)
                svg.append(
                    f'<line x1="{dx}" y1="{dy + dot_r}" x2="{dx}" y2="{pill_y}" '
                    f'stroke="{DOT}" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.7"/>'
                )

            text_y = pill_y + 17  # vertically center text in pill (pill_h=26)

            # clamp pill x to plot bounds
            pill_x = max(pad_l + 4, min(plot_right - pill_w - 4, dx - pill_w / 2 - pill_pad))

            svg.append(
                f'<rect x="{pill_x}" y="{pill_y}" width="{pill_w}" '
                f'height="{pill_h}" rx="4" fill="{BG}" stroke="{DOT}" '
                f'stroke-width="1.5" opacity="0.9" filter="url(#ts)"/>'
            )
            svg.append(
                f'<text x="{pill_x + pill_w / 2}" y="{text_y}" '
                f'text-anchor="middle" fill="{DOT}" font-size="16" font-weight="bold" '
                f'filter="url(#ts)">{txt}</text>'
            )

            # ---- after-comp dot + label (violet, on the same AT but at its own height) ----
            if after_comp is not None:
                ay = round(y_flow(float(after_comp)), 1)
                ay = max(pad_t + 12, min(plot_bottom - 12, ay))
                # Don't let the violet dot overlap the green dot — if they're
                # too close vertically, offset the violet dot slightly right
                if abs(ay - dy) < 12:
                    svg.append(
                        f'<circle cx="{dx + 8}" cy="{ay}" r="5" fill="{AFTER_COL}" '
                        f'stroke="#fff" stroke-width="1.5"/>'
                    )
                    vdx = dx + 8
                else:
                    svg.append(
                        f'<circle cx="{dx}" cy="{ay}" r="5" fill="{AFTER_COL}" '
                        f'stroke="#fff" stroke-width="1.5"/>'
                    )
                    vdx = dx

                # after-comp label: placed to the right of the violet dot,
                # connected by a single long dotted line. Always below to
                # avoid the cyan curve.
                a_label = f"{self._t('legend_after')}: {float(after_comp):.1f}C"
                a_w = _text_w(a_label, font_size=14)
                pill_pad_a = 8
                pill_h_a = 24
                pill_w_a = a_w + pill_pad_a * 2

                # Extended connector — 2-5x longer than before.
                # Dynamic: pick the side with more room; connector length scales
                # with the label so it never overlaps the dot or other labels.
                conn_len = max(20, min(60, len(a_label) * 4))  # 2-5x scale
                a_dy = ay + conn_len  # well below the dot

                # place pill to the right if it fits, otherwise left
                if vdx + pill_pad_a + pill_w_a + 10 < plot_right - 6:
                    a_tx = vdx + pill_pad_a
                    # single long dotted line from dot edge to pill left edge
                    svg.append(
                        f'<line x1="{vdx}" y1="{ay + 5}" x2="{a_tx}" y2="{a_dy}" '
                        f'stroke="{AFTER_COL}" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.7"/>'
                    )
                else:
                    a_tx = max(pad_l + 6, vdx - pill_pad_a - pill_w_a)
                    svg.append(
                        f'<line x1="{vdx}" y1="{ay + 5}" x2="{a_tx + pill_w_a}" y2="{a_dy}" '
                        f'stroke="{AFTER_COL}" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.7"/>'
                    )

                svg.append(
                    f'<rect x="{a_tx}" y="{a_dy}" width="{pill_w_a}" '
                    f'height="{pill_h_a}" rx="4" fill="{BG}" stroke="{AFTER_COL}" '
                    f'stroke-width="1.5" opacity="0.9" filter="url(#ts)"/>'
                )
                svg.append(
                    f'<text x="{a_tx + pill_pad_a}" y="{a_dy + 17}" text-anchor="start" '
                    f'fill="{AFTER_COL}" font-size="14" font-weight="bold" filter="url(#ts)">'
                    f'{a_label}</text>'
                )

        # ---- legend strip (bottom) ----
        # Two-row layout:
        #   top row: 4 swatch+label pairs (flowing left-to-right)
        #   bottom row: compact summary (left-aligned)
        # If the 4th item would overflow the right edge, wrap it to a
        # second row within the legend box.
        ly_top = plot_bottom + 56
        ly_bot = plot_bottom + 88
        svg.append(
            f'<rect x="{pad_l}" y="{plot_bottom + 46}" width="{plot_w}" '
            f'height="{legend_h - 8}" fill="#020617" stroke="{AXIS}" rx="6"/>'
        )
        # Legend layout constants — used by _legend_item which draws both
        # the marker swatch and the text label, so callers never compute
        # text x-positions manually (prevents the off-by-N spacing bugs where
        # changing swatch_w/gap/item_gap broke every text offset).
        SWATCH_W = 26
        LEGEND_GAP = 1       # marker-to-text gap
        LEGEND_ITEM_GAP = 30  # inter-item spacing (after label)

        def _legend_item(x, color, label, active=False, is_line=True, dash=False, font_size=15, text_y=None, text_color=TEXT, font_weight="normal"):
            """Draws marker swatch + text label at horizontal position x on the
            legend row. Returns x_advance = x + SWATCH_W + LEGEND_GAP + label_w + LEGEND_ITEM_GAP
            so the next item starts at the right spot.
            """
            if text_y is None:
                text_y = ly_top + 6
            opacity = 1.0 if active else 0.5
            dash_frag = ' stroke-dasharray="6 4"' if dash else ''
            if is_line:
                svg.append(
                    f'<line x1="{x}" y1="{ly_top}" x2="{x + SWATCH_W}" y2="{ly_top}" '
                    f'stroke="{color}" stroke-width="4"{dash_frag} opacity="{opacity}"/>'
                )
            else:
                svg.append(
                    f'<circle cx="{x + SWATCH_W - 6}" cy="{ly_top}" r="6" fill="{color}" '
                    f'opacity="{1.0 if active else 0.6}"/>'
                )
            label_w = _text_w(label, font_size=font_size)
            text_x = x + SWATCH_W + LEGEND_GAP
            fw_part = f' font-weight="{font_weight}"' if font_weight != "normal" else ""
            svg.append(
                f'<text x="{text_x}" y="{text_y}" fill="{text_color}" '
                f'font-size="{font_size}"{fw_part} filter="url(#ts)">{label}</text>'
            )
            return x + SWATCH_W + LEGEND_GAP + label_w + LEGEND_ITEM_GAP

        # 1) curve target
        x = pad_l + 16
        label_c = self._t("legend_curve")
        x = _legend_item(x, CURVE, label_c, active=is_curve_mode, dash=not is_curve_mode,
                         text_color=TEXT_DARK if is_curve_mode else TEXT)

        # 2) fixed setpoint
        label_f = self._t("legend_fixed")
        x = _legend_item(x, FIXED_COL, label_f, active=not is_curve_mode, dash=is_curve_mode,
                         text_color=TEXT_DARK if not is_curve_mode else TEXT)

        # 3) after compensation (violet dot) — with separator bar
        label_a = self._t("legend_after")
        # thin separator between line-swatch group and dot-swatch group
        svg.append(
            f'<rect x="{x + 4}" y="{ly_top - 12}" width="2" height="24" '
            f'fill="{AXIS}" opacity="0.4" rx="1"/>'
        )
        x = _legend_item(x, AFTER_COL, label_a, is_line=False)

        # 4) live AT (green dot) — wrap to second row if overflowing
        live_label = self._t("legend_live")
        live_w = _text_w(live_label)
        if x + SWATCH_W + LEGEND_GAP + live_w > plot_right - 6:
            # wrap to second row
            ly_live_top = ly_top + 24
            svg.append(
                f'<rect x="{pad_l}" y="{plot_bottom + 46}" width="{plot_w}" '
                f'height="{legend_h - 8 + 24}" fill="#020617" stroke="{AXIS}" rx="6"/>'
            )
            x = pad_l + 16
            live_y = ly_live_top + 6
        else:
            live_y = ly_top + 6
        x = _legend_item(x, DOT, live_label, is_line=False,
                         text_y=live_y, text_color=TEXT_DARK, font_weight="bold")

        # ---- summary on bottom row ----
        summary = (
            f'slope {slope:.2f}  ·  offset {offset:.1f}C  ·  '
            f'{self._t("legend_band")}: {r10:.0f}–{r11:.0f}C  ·  '
            f'{self._t("mode_curve" if is_curve_mode else "mode_fixed")}'
        )
        svg.append(
            f'<text x="{pad_l + 8}" y="{ly_bot + 4}" fill="{TEXT}" '
            f'font-size="14" filter="url(#ts)">{summary}</text>'
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
