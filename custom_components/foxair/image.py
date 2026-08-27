"""Image platform — heating curve on device page without YAML.

Renders image.foxair_heating_curve on the FoxAir Heat Pump device.
Sharp SVG, no Pillow needed. Updates only when curve-relevant values change.

Mode behaviour (driven by H36 / register 1236):
  * H36 = 1  -> AT-compensation (curve) mode:
                target(AT) = offset + slope * (20 - AT), clamped to [R10, R11]
                Drawn as the main blue curve line.
  * H36 = 0  -> constant (fixed) mode:
                target = R02 (register 1158), drawn as the main amber line.
                The weather-compensation curve is shown faintly as a preview.
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
            rec = d.get(addr)
            if not rec:
                return default
            v = rec.get("value")
            return v if v is not None else default

        slope = val(1234, 0.6)
        offset = val(1235, 0.0)
        h36 = d.get(1236, {}).get("raw") if d.get(1236) else None
        at_live = val(2048)
        fixed = val(1158)
        after = val(2014)
        r10 = val(1164, 20.0)
        r11 = val(1165, 60.0)
        return (slope, offset, h36, at_live, fixed, after, r10, r11)

    def _handle_coordinator_update(self) -> None:
        key = self._curve_inputs()
        if key != self._curve_params:
            self._curve_params = key
            self._render()
        super()._handle_coordinator_update()

    def _render(self):
        W, H = 1200, 720
        pad_l, pad_r, pad_t, pad_b = 90, 40, 70, 80
        plot_w = W - pad_l - pad_r
        plot_h = H - pad_t - pad_b

        def x_at(v: float) -> float:
            return pad_l + (v - AT_MIN) / (AT_MAX - AT_MIN) * plot_w

        def y_flow(v: float) -> float:
            # flow axis 10..70 °C mapped top->bottom
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

        params = self._curve_params
        if params:
            slope, offset, h36_raw, at_live, fixed, after_comp, r10, r11 = params
            if slope is None:
                slope = 0.6
            if offset is None:
                offset = 0.0
            if fixed is None:
                fixed = 35.0
            is_curve_mode = h36_raw != 0

        slope = _norm_slope(slope)
        r10 = float(r10 if r10 is not None else 20.0)
        r11 = float(r11 if r11 is not None else 60.0)

        # live computed target (uses full envelope logic from helper)
        if at_live is not None and coord is not None:
            try:
                target_live = curve_target_for_at(coord, float(at_live))
            except Exception as e:  # pragma: no cover
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

        # ---- grid ----
        grid_lines = ""
        for at_g in range(-30, 21, 5):
            x = round(x_at(at_g), 1)
            stroke = GRID if at_g % 10 == 0 else GRID_MINOR
            grid_lines += (
                f'<line x1="{x}" y1="{pad_t}" x2="{x}" y2="{H - pad_b}" '
                f'stroke="{stroke}" stroke-width="1"/>\n'
            )
        for f in range(10, 71, 5):
            y = round(y_flow(f), 1)
            stroke = GRID if f % 10 == 0 else GRID_MINOR
            grid_lines += (
                f'<line x1="{pad_l}" y1="{y}" x2="{W - pad_r}" y2="{y}" '
                f'stroke="{stroke}" stroke-width="1"/>\n'
            )

        # ---- ticks ----
        ticks = ""
        for at_g in (-30, -20, -10, 0, 10, 20):
            x = round(x_at(at_g), 1)
            ticks += (
                f'<text x="{x}" y="{H - pad_b + 18}" text-anchor="middle" '
                f'fill="{TEXT}" font-family="sans-serif" font-size="14">{at_g}°</text>\n'
            )
        for f in (10, 20, 30, 40, 50, 60, 70):
            y = round(y_flow(f), 1)
            ticks += (
                f'<text x="{pad_l - 12}" y="{y + 5}" text-anchor="end" '
                f'fill="{TEXT}" font-family="sans-serif" font-size="14">{f}°</text>\n'
            )

        # ---- weather-compensation curve points (always computed) ----
        curve_pts = []
        for i in range(int(AT_MIN * 2), int(AT_MAX * 2) + 1):
            at_step = i / 2.0
            raw = calc_curve_target(at_step, slope, offset, base=0.0)
            c = clamp(raw, r10, r11)
            curve_pts.append((round(x_at(at_step), 1), round(y_flow(c), 1)))

        # ---- fixed (constant) point ----
        fixed_y = round(y_flow(clamp(fixed, r10, r11)), 1)

        # ---- min/max band ----
        band_top = round(y_flow(r11), 1)
        band_bot = round(y_flow(r10), 1)
        band_h = max(band_bot - band_top, 1)

        # ---- build mode-specific line ----
        # main line: curve mode -> blue curve ; fixed mode -> amber constant
        main_line = ""
        preview = ""
        if is_curve_mode:
            poly_pts = " ".join(f"{x},{y}" for x, y in curve_pts)
            poly_fill = " ".join(
                f"{x},{y}"
                for x, y in curve_pts
                + [(curve_pts[-1][0], H - pad_b), (curve_pts[0][0], H - pad_b)]
            )
            main_line = (
                f'<polygon points="{poly_fill}" fill="{CURVE_FILL}"/>\n'
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="4" '
                f'stroke-linejoin="round" points="{poly_pts}"/>\n'
            )
        else:
            # fixed mode: prominent constant line + faint curve preview
            main_line = (
                f'<line x1="{pad_l}" y1="{fixed_y}" x2="{W - pad_r}" y2="{fixed_y}" '
                f'stroke="{FIXED_COL}" stroke-width="4"/>\n'
            )
            poly_pts = " ".join(f"{x},{y}" for x, y in curve_pts)
            preview = (
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="2" '
                f'stroke-dasharray="6 6" opacity="0.45" points="{poly_pts}"/>\n'
            )

        # ---- mode hint banner ----
        mode_text = "AT Compensation (curve)" if is_curve_mode else "Constant (fixed) R02"
        banner = (
            f'<rect x="{W // 2 - 230}" y="{H - 38}" width="460" height="24" rx="8" '
            f'fill="#0ea5e9" opacity="0.12" stroke="{CURVE}"/>\n'
            f'<text x="{W // 2}" y="{H - 21}" text-anchor="middle" fill="{TEXT_DARK}" '
            f'font-family="sans-serif" font-size="13">Mode: {mode_text}</text>\n'
        )

        # ---- live AT dot ----
        dot_svg = ""
        if at_live is not None and target_live is not None:
            dx = round(x_at(float(at_live)), 1)
            dy = round(y_flow(float(target_live)), 1)
            if pad_l <= dx <= W - pad_r and pad_t <= dy <= H - pad_b:
                dot_svg = (
                    f'<circle cx="{dx}" cy="{dy}" r="10" fill="#fff" opacity="0.9"/>\n'
                    f'<circle cx="{dx}" cy="{dy}" r="8" fill="{DOT}" stroke="#fff" '
                    f'stroke-width="2"/>\n'
                )
                txt = f"AT {float(at_live):.1f}° → {float(target_live):.1f}°C"
                dot_svg += (
                    f'<text x="{dx + 18}" y="{dy - 12}" fill="{DOT}" '
                    f'font-family="sans-serif" font-size="14">{txt}</text>\n'
                )
                if after_comp is not None:
                    ay = round(y_flow(float(after_comp)), 1)
                    dot_svg += (
                        f'<circle cx="{dx}" cy="{ay}" r="5" fill="{AFTER_COL}" '
                        f'stroke="#fff" stroke-width="1.5"/>\n'
                        f'<text x="{dx + 18}" y="{ay + 16}" fill="{AFTER_COL}" '
                        f'font-family="sans-serif" font-size="12">'
                        f'after 2014 {float(after_comp):.1f}°</text>\n'
                    )
        elif at_live is None:
            dot_svg = (
                f'<text x="{W // 2}" y="{H // 2 + 10}" text-anchor="middle" '
                f'fill="{TEXT}" font-family="sans-serif" font-size="16">'
                f'Waiting for AT (2048) …</text>\n'
            )

        # ---- title ----
        subtitle = (
            f"Heating Curve — slope {slope:.2f} · offset {float(offset):.1f}°C · "
            f"{mode_text} · R10 {r10:.0f}° … R11 {r11:.0f}°"
        )

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<rect width="100%" height="100%" fill="{BG}"/>
<text x="{W // 2}" y="28" text-anchor="middle" fill="{TEXT_DARK}" font-family="sans-serif" font-size="22">{subtitle}</text>
<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{H - pad_b}" stroke="{AXIS}" stroke-width="2"/>
<line x1="{pad_l}" y1="{H - pad_b}" x2="{W - pad_r}" y2="{H - pad_b}" stroke="{AXIS}" stroke-width="2"/>
{grid_lines}{ticks}<rect x="{pad_l}" y="{band_top}" width="{plot_w}" height="{band_h}" fill="{CURVE_FILL}"/>
<text x="{W - pad_r - 6}" y="{band_top + 14}" text-anchor="end" fill="{CURVE}" font-family="sans-serif" font-size="12">R10 {r10:.0f} — R11 {r11:.0f}</text>
{main_line}{preview}{banner}{dot_svg}<text x="{pad_l + plot_w // 2}" y="{H - 10}" text-anchor="middle" fill="{TEXT_DARK}" font-family="sans-serif" font-size="13">Outdoor temperature AT  [°C]</text>
<text x="18" y="{pad_t + plot_h // 2}" text-anchor="middle" fill="{TEXT_DARK}" font-family="sans-serif" font-size="14" transform="rotate(-90 18,{pad_t + plot_h // 2})">Flow °C</text>
</svg>"""

        self._image_bytes = svg.encode("utf-8")
        self._image_last_updated = datetime.now(timezone.utc)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if not coord:
        return
    async_add_entities([FoxAirHeatingCurveImage(coord, entry.entry_id)])
