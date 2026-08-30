"""Image platform — heating curve on device page without YAML.

Renders image.foxair_heating_curve on the FoxAir Heat Pump device.
Sharp SVG, no Pillow needed. Updates only when curve-relevant values change.

Mode behaviour (driven by H36 / register 1236):
  * H36 = 1  -> AT-compensation (curve) mode:
                target(AT) = offset - slope * AT, clamped to [R10, R11]
                Drawn as the main blue curve line.
  * H36 = 0  -> constant (fixed) mode:
                target = R02 (register 1158), drawn as amber line.
                Weather-compensation curve shown faintly as a preview.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import main_device
from .heating_curve import calc_curve_target, curve_target_for_at

_LOGGER = logging.getLogger(__name__)

# AT range shown on the X axis
AT_MIN, AT_MAX = -30.0, 20.0


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
        self._attr_unique_id = f"{entry_id}_heating_curve_image"
        self._attr_device_info = main_device(entry_id)
        self.entity_id = "image.foxair_heating_curve"
        self._image_bytes: bytes | None = None
        self._image_last_updated: datetime | None = None
        self._curve_params: tuple | None = None
        self._render()

    @property
    def image_last_updated(self):
        return self._image_last_updated

    async def async_image(self) -> bytes | None:
        if self._image_bytes is None:
            self._render()
        return self._image_bytes

    def _curve_inputs(self):
        coord = self.coordinator
        if not coord or not getattr(coord, "data", None):
            return None
        d = coord.data

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

        hc = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
        hc_a = hc.get("addr_single", {}) if isinstance(hc, dict) else {}
        st = coord.marker("setpoints") if hasattr(coord, "marker") else {}
        st_a = st.get("addr_single", {}) if isinstance(st, dict) else {}
        slope = val(hc_a.get("slope"), 0.6)
        offset = val(hc_a.get("offset"), 0.0)
        h36 = raw(hc_a.get("at_comp_en"))
        at_live = val(hc_a.get("at_sensor"))
        fixed = val(st_a.get("heating_target"))
        after = val(hc_a.get("live_target"))
        r10 = val(hc_a.get("r10_min"), 20.0)
        r11 = val(hc_a.get("r11_max"), 60.0)
        return (slope, offset, h36, at_live, fixed, after, r10, r11)

    def _handle_coordinator_update(self) -> None:
        key = self._curve_inputs()
        if key != self._curve_params:
            self._curve_params = key
            self._render()
            self.async_write_ha_state()
        super()._handle_coordinator_update()

    def _render(self):
        """Render the heating curve SVG.

        Layout (1200x720):
        - Title bar: top, centered (y=28)
        - Plot area: x=[pad_l..W-pad_r], y=[pad_t..H-pad_b-legend_h]
        - All text labels and annotations: LEFT of the curve, never right
        - Legend strip: bottom 80px with dark background
        - Gridlines: every 5°C, major every 10°C
        - Axis labels: outside the plot, left and bottom
        """
        W, H = 1200, 720
        pad_l, pad_r, pad_t, pad_b = 90, 50, 70, 80
        legend_h = 80
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

        coord = self.coordinator
        # defaults so a line always renders, even before first poll
        slope = 0.6
        offset = 0.0
        r10, r11 = 20.0, 60.0
        fixed = 35.0
        at_live = None
        target_live = None
        after_comp = None
        h36_raw = None
        is_curve_mode = True
        data_ready = True

        params = self._curve_params
        if params:
            slope, offset, h36_raw, at_live, fixed, after_comp, r10, r11 = params
            if slope is None:
                slope = 0.6
                data_ready = False
            if offset is None:
                offset = 0.0
                data_ready = False
            if fixed is None:
                fixed = 35.0
                data_ready = False
            if at_live is None:
                data_ready = False
            is_curve_mode = h36_raw != 0

        slope = _norm_slope(slope)
        r10 = float(r10 if r10 is not None else 20.0)
        r11 = float(r11 if r11 is not None else 60.0)

        # live computed target
        if at_live is not None and coord is not None:
            try:
                target_live = curve_target_for_at(coord, float(at_live))
            except Exception as e:
                _LOGGER.debug("curve target calc failed %s", e)
                target_live = None

        # ---- colours ----
        BG = "#0f172a"
        GRID = "#1e293b"
        GRID_MINOR = "#172033"
        AXIS = "#334155"
        TEXT = "#94a3b8"
        TEXT_DARK = "#e2e8f0"
        CURVE = "#38bdf8"
        CURVE_FILL = "rgba(14,165,233,0.08)"
        FIXED_COL = "#fbbf24"
        DOT = "#f87171"
        AFTER_COL = "#a78bfa"
        LOADING_BG = "#020617"

        svg_parts = []

        # ---- background ----
        svg_parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="sans-serif">'
        )
        svg_parts.append(
            f'<rect width="100%" height="100%" fill="{BG}"/>'
        )

        # ---- title ----
        mode_text = "AT Compensation (curve)" if is_curve_mode else "Constant (fixed) R02"
        subtitle = (
            f"Heating Curve  slope {slope:.2f}  offset {float(offset):.1f}C  "
            f"{mode_text}  R10 {r10:.0f}C .. R11 {r11:.0f}C"
        )
        svg_parts.append(
            f'<text x="{W // 2}" y="28" text-anchor="middle" fill="{TEXT_DARK}" '
            f'font-size="22" font-weight="bold">{subtitle}</text>'
        )

        # ---- loading overlay ----
        if not data_ready:
            svg_parts.append(
                f'<rect x="0" y="0" width="{W}" height="{H}" fill="{LOADING_BG}" opacity="0.95"/>'
            )
            svg_parts.append(
                f'<text x="{W // 2}" y="{H // 2 - 10}" text-anchor="middle" '
                f'fill="{TEXT_DARK}" font-size="24">Waiting for data</text>'
            )
            svg_parts.append(
                f'<text x="{W // 2}" y="{H // 2 + 20}" text-anchor="middle" '
                f'fill="{TEXT}" font-size="14">First poll in progress (quick 30s)</text>'
            )
            svg_parts.append('</svg>')
            self._image_bytes = "".join(svg_parts).encode("utf-8")
            self._image_last_updated = datetime.now(timezone.utc)
            return

        # ---- grid ----
        for at_g in range(-30, 21, 5):
            x = round(x_at(at_g), 1)
            stroke = GRID if at_g % 10 == 0 else GRID_MINOR
            sw = "1.5" if at_g % 10 == 0 else "1"
            svg_parts.append(
                f'<line x1="{x}" y1="{pad_t}" x2="{x}" y2="{plot_bottom}" '
                f'stroke="{stroke}" stroke-width="{sw}"/>'
            )
        for f in range(10, 71, 5):
            y = round(y_flow(f), 1)
            stroke = GRID if f % 10 == 0 else GRID_MINOR
            sw = "1.5" if f % 10 == 0 else "1"
            svg_parts.append(
                f'<line x1="{pad_l}" y1="{y}" x2="{plot_right}" y2="{y}" '
                f'stroke="{stroke}" stroke-width="{sw}"/>'
            )

        # ---- axes ----
        svg_parts.append(
            f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{plot_bottom}" '
            f'stroke="{AXIS}" stroke-width="2"/>'
        )
        svg_parts.append(
            f'<line x1="{pad_l}" y1="{plot_bottom}" x2="{plot_right}" '
            f'y2="{plot_bottom}" stroke="{AXIS}" stroke-width="2"/>'
        )

        # ---- reference cross at design point (AT=0 -> flow=offset) ----
        ref_cross = ""
        try:
            x0 = round(x_at(0.0), 1)
            y0 = round(y_flow(float(offset)), 1)
            ref_cross += (
                f'<line x1="{x0}" y1="{pad_t}" x2="{x0}" y2="{plot_bottom}" '
                f'stroke="#e2e8f0" stroke-width="1.5" stroke-dasharray="3 5" opacity="0.5"/>'
            )
            ref_cross += (
                f'<line x1="{pad_l}" y1="{y0}" x2="{plot_right}" y2="{y0}" '
                f'stroke="#e2e8f0" stroke-width="1.5" stroke-dasharray="3 5" opacity="0.5"/>'
            )
            ref_cross += (
                f'<circle cx="{x0}" cy="{y0}" r="6" fill="#e2e8f0" '
                f'stroke="{BG}" stroke-width="2"/>'
            )
        except Exception:
            ref_cross = ""
        svg_parts.append(ref_cross)

        # ---- X axis ticks (labels at bottom, left-aligned to their tick) ----
        for at_g in (-30, -20, -10, 0, 10, 20):
            x = round(x_at(at_g), 1)
            label = f"0C->{float(offset):.0f}C" if at_g == 0 else f"{at_g}C"
            svg_parts.append(
                f'<text x="{x}" y="{plot_bottom + 20}" text-anchor="middle" '
                f'fill="{TEXT_DARK if at_g == 0 else TEXT}" font-size="14" '
                f'font-weight="bold">{label}</text>'
            )

        # ---- Y axis ticks (labels at left) ----
        for f in (10, 20, 30, 40, 50, 60, 70):
            y = round(y_flow(f), 1)
            svg_parts.append(
                f'<text x="{pad_l - 12}" y="{y + 5}" text-anchor="end" '
                f'fill="{TEXT}" font-size="14">{f}C</text>'
            )

        # ---- axis titles ----
        svg_parts.append(
            f'<text x="{pad_l + plot_w // 2}" y="{plot_bottom + 42}" text-anchor="middle" '
            f'fill="{TEXT}" font-size="14">Outdoor temperature (AT)</text>'
        )
        svg_parts.append(
            f'<text x="25" y="{pad_t + plot_h // 2}" text-anchor="middle" fill="{TEXT}" '
            f'font-size="14" transform="rotate(-90 25, {pad_t + plot_h // 2})">Flow</text>'
        )

        # ---- min/max band ----
        band_top = round(y_flow(r11), 1)
        band_bot = round(y_flow(r10), 1)
        band_h = max(band_bot - band_top, 1)
        svg_parts.append(
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
            # curve mode: blue curve is the main line
            svg_parts.append(f'<polygon points="{poly_fill}" fill="{CURVE_FILL}"/>')
            svg_parts.append(
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="4" '
                f'stroke-linejoin="round" points="{poly_pts}"/>'
            )
            # fixed value as faint amber horizontal line (for reference)
            fixed_y = round(y_flow(clamp(fixed, r10, r11)), 1)
            svg_parts.append(
                f'<line x1="{pad_l}" y1="{fixed_y}" x2="{plot_right}" y2="{fixed_y}" '
                f'stroke="{FIXED_COL}" stroke-width="2" stroke-dasharray="8 6" opacity="0.5"/>'
            )
        else:
            # fixed mode: prominent amber constant line + faint curve preview
            fixed_y = round(y_flow(clamp(fixed, r10, r11)), 1)
            svg_parts.append(
                f'<line x1="{pad_l}" y1="{fixed_y}" x2="{plot_right}" y2="{fixed_y}" '
                f'stroke="{FIXED_COL}" stroke-width="4"/>'
            )
            svg_parts.append(
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="2" '
                f'stroke-dasharray="8 6" opacity="0.45" points="{poly_pts}"/>'
            )

        # ---- data point labels at -20, -10, 0, 10, 20 (left side of point) ----
        for at_g in (-20, -10, 0, 10, 20):
            try:
                raw_val = calc_curve_target(float(at_g), slope, offset, base=0.0)
                c = clamp(raw_val, r10, r11)
                px = round(x_at(float(at_g)), 1)
                py = round(y_flow(c), 1)
                # label to the left of each point, never to the right
                svg_parts.append(
                    f'<text x="{px - 8}" y="{py - 8}" text-anchor="end" '
                    f'fill="{TEXT_DARK}" font-size="12" font-weight="bold">'
                    f'{float(c):.1f}C</text>'
                )
            except Exception:
                continue

        # ---- R10/R11 band label (top-left of band, on left side) ----
        svg_parts.append(
            f'<text x="{pad_l + 8}" y="{band_top + 16}" fill="{CURVE}" '
            f'font-size="12">R10 {r10:.0f}C .. R11 {r11:.0f}C</text>'
        )

        # ---- live AT dot + label (label always to the LEFT of the dot) ----
        if at_live is not None and target_live is not None:
            dx = round(x_at(float(at_live)), 1)
            dy = round(y_flow(float(target_live)), 1)
            # clamp dx to plot area
            dx = max(pad_l + 15, min(plot_right - 15, dx))
            if pad_t <= dy <= plot_bottom:
                svg_parts.append(
                    f'<circle cx="{dx}" cy="{dy}" r="10" fill="#fff" opacity="0.9"/>'
                )
                svg_parts.append(
                    f'<circle cx="{dx}" cy="{dy}" r="8" fill="{DOT}" stroke="#fff" '
                    f'stroke-width="2"/>'
                )
                txt = f"AT {float(at_live):.1f}C -> {float(target_live):.1f}C"
                svg_parts.append(
                    f'<text x="{dx - 12}" y="{dy - 14}" text-anchor="end" '
                    f'fill="{DOT}" font-size="14" font-weight="bold">{txt}</text>'
                )
            if after_comp is not None:
                ay = round(y_flow(float(after_comp)), 1)
                ay = max(pad_t + 10, min(plot_bottom - 10, ay))
                svg_parts.append(
                    f'<circle cx="{dx}" cy="{ay}" r="5" fill="{AFTER_COL}" '
                    f'stroke="#fff" stroke-width="1.5"/>'
                )
                svg_parts.append(
                    f'<text x="{dx - 12}" y="{ay + 18}" text-anchor="end" '
                    f'fill="{AFTER_COL}" font-size="12">after {float(after_comp):.1f}C</text>'
                )

        # ---- legend strip (bottom band with bg) ----
        legend_y = plot_bottom + 30
        svg_parts.append(
            f'<rect x="{pad_l}" y="{plot_bottom + 4}" width="{plot_w}" '
            f'height="{legend_h - 8}" fill="#020617" stroke="{AXIS}" rx="6"/>'
        )
        svg_parts.append(
            f'<text x="{pad_l + 12}" y="{legend_y}" fill="{CURVE}" font-size="13">'
            f'Curve target (AT-compensation)</text>'
        )
        svg_parts.append(
            f'<text x="{pad_l + 230}" y="{legend_y}" fill="{FIXED_COL}" font-size="13">'
            f'Fixed R02 (H36=0)</text>'
        )
        svg_parts.append(
            f'<text x="{pad_l + 440}" y="{legend_y}" fill="{AFTER_COL}" font-size="13">'
            f'After compensation</text>'
        )
        svg_parts.append(
            f'<text x="{plot_right}" y="{legend_y}" text-anchor="end" fill="{TEXT}" '
            f'font-size="13">H36: {mode_text}</text>'
        )

        svg_parts.append("</svg>")

        self._image_bytes = "".join(svg_parts).encode("utf-8")
        self._image_last_updated = datetime.now(timezone.utc)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if not coord:
        return
    async_add_entities([FoxAirHeatingCurveImage(coord, entry.entry_id)])
