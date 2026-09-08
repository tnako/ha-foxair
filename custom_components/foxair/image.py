"""Image platform — heating curve on the device page (no YAML needed).

Renders image.foxair_heating_curve on the FoxAir Heat Pump device.
Pure SVG (no Pillow). Redraws only when a curve-affecting input changes,
otherwise keeps the last image (cheap caching) — so changing slope/offset
or the live outdoor temp updates the picture, but unrelated polls don't.

All user-visible text is pulled from HA translations (entity.image.
foxair_heating_curve.*) so it follows the UI language; English is the
fallback. A single live dot sits exactly on the active target (no duplicate
device/computed dots). Around the target a two-tone hysteresis band shows
the R04 start-heating side (green tint, dashed lower boundary) and the R05
idle/stop side (slate tint, dashed upper boundary); at the live outdoor
temperature dotted-outline markers give both threshold temps. The bottom
legend is a fixed 2x2 grid (no flowing layout, no overlaps).

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

from .const import main_device, get_device_prefix, get_slave_id, bind_device_info
from .heating_curve import calc_curve_target, curve_target_for_at

_LOGGER = logging.getLogger(__name__)

# AT range shown on the X axis
AT_MIN, AT_MAX = -30.0, 20.0

# English fallback so the image always renders even before translations load.
_TL_FALLBACK = {
    "name": "Heating Curve",
    "legend_curve": "Curve target",
    "legend_fixed": "Fixed setpoint",
    "legend_live": "Live outdoor",
    "legend_band": "Limit band",
    "legend_heat": "Heating range (R04-R05)",
    "legend_start": "Start heating",
    "legend_stop": "Stop heating",
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
    _attr_has_entity_name = True
    _attr_icon = "mdi:chart-bell-curve"
    _attr_content_type = "image/svg+xml"

    def __init__(self, coordinator, entry_id: str):
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._entry_id = entry_id
        prefix = get_device_prefix(coordinator.entry)
        self._prefix = prefix
        # translation_key must stay stable - translations only exist under
        # foxair_heating_curve (not phnix_heating_curve). Entity id/uniqueness
        # still uses the user-chosen prefix.
        self._attr_translation_key = "foxair_heating_curve"
        self._attr_unique_id = f"{prefix}_heating_curve_image"
        slave_id = get_slave_id(coordinator.entry)
        host = coordinator.entry.data.get("host")
        port = coordinator.entry.data.get("port")
        self._attr_device_info = bind_device_info(getattr(coordinator, "hass", None), entry_id, main_device(entry_id, prefix, slave_id, host, port))
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

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.async_load_translations()
        self._render()
        try:
            self.async_write_ha_state()
        except Exception:
            pass
        # Re-load when HA language changes (Settings -> System -> Language)
        try:
            from homeassistant.core import EVENT_CORE_CONFIG_UPDATE
            self.async_on_remove(
                self.hass.bus.async_listen(
                    EVENT_CORE_CONFIG_UPDATE, self._handle_language_change
                )
            )
        except Exception:
            pass

    async def _handle_language_change(self, _event=None) -> None:
        await self.async_load_translations()
        self._render()
        try:
            self.async_write_ha_state()
        except Exception:
            pass

    async def async_load_translations(self) -> None:
        """Load the image's translation catalog for the current UI language."""
        try:
            lang = getattr(self.hass.config, "language", None) or "en"
            cat = await async_get_translations(
                self.hass, lang, category="entity", integrations=["foxair"]
            )
            # Stable key: foxair_heating_curve (translations only exist there,
            # not under phnix_*/custom prefixes). Try prefixed variant first
            # for forward-compat, then fall back to canonical.
            pref = getattr(self, "_prefix", "foxair")
            keys_to_try = []
            if pref != "foxair":
                keys_to_try.append(f"component.foxair.entity.image.{pref}_heating_curve.")
            keys_to_try.append("component.foxair.entity.image.foxair_heating_curve.")
            loaded_raw: dict = {}
            for pfx in keys_to_try:
                hit = {k[len(pfx):]: v for k, v in cat.items() if k.startswith(pfx)}
                if hit:
                    loaded_raw = hit
                    break
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
            if loaded_raw:
                self._render()
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
        r10 = val(hca.get("r10_min"), None)
        r11 = val(hca.get("r11_max"), None)
        # Heating hysteresis (R04 start / R05 stop); marker keys are optional,
        # fall back to the fixed register addrs so the band works regardless.
        r04 = val(hca.get("r04_start") or 1160, None)
        r05 = val(hca.get("r05_stop") or 1161, None)

        ready = (slope is not None) and (offset is not None) and (fixed is not None)
        return {
            "slope": slope, "offset": offset, "fixed": fixed,
            "h36": h36, "at_live": at_live,
            "r10": r10, "r11": r11, "r04": r04, "r05": r05, "ready": ready,
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
        W, H = 1200, 760
        pad_l, pad_r, pad_t, pad_b = 90, 50, 64, 96
        legend_h = 120
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
        # Cyrillic glyphs run visibly wider — measure them with a larger
        # factor, otherwise RU labels overflow their pill backgrounds.
        def _text_w(label, font_size=15):
            if any("\u0400" <= c <= "\u04ff" for c in label):
                return len(label) * font_size * 0.72
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
        r04 = _f("r04", 2.0)
        r05 = _f("r05", 2.0)
        if r04 < 0:
            r04 = 0.0
        if r05 < 0:
            r05 = 0.0
        at_live = inp.get("at_live")
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
        START_COL = "#4ade80"
        STOP_COL = "#cbd5e1"
        BAND_LO_FILL = "rgba(34,197,94,0.10)"
        BAND_HI_FILL = "rgba(148,163,184,0.10)"
        LOADING_BG = "#020617"
        # Floating value labels get a vector halo (paint-order stroke) instead
        # of the old feDropShadow raster filter: crisp at any scale, and much
        # cheaper for phone GPUs (filters force rasterization → blur).
        HALO = (
            f'paint-order="stroke" stroke="{BG}" '
            f'stroke-width="3" stroke-linejoin="round"'
        )

        svg = []

        # ---- loading overlay (only while essential data is missing) ----
        if not ready:
            svg.append(
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
                f'viewBox="0 0 {W} {H}" font-family="system-ui,-apple-system,sans-serif">'
            )
            svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')
            svg.append(
                f'<rect x="0" y="0" width="{W}" height="{H}" fill="{LOADING_BG}" opacity="0.95"/>'
            )
            svg.append(
                f'<text x="{W // 2}" y="{H // 2 - 10}" text-anchor="middle" '
                f'fill="{TEXT_DARK}" font-size="26">{self._t("wait")}</text>'
            )
            svg.append(
                f'<text x="{W // 2}" y="{H // 2 + 30}" text-anchor="middle" '
                f'fill="{TEXT}" font-size="17">{self._t("wait_sub")}</text>'
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
            f'viewBox="0 0 {W} {H}" font-family="system-ui,-apple-system,sans-serif">'
        )
        svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')

        # ---- title ----
        svg.append(
            f'<text x="{W // 2}" y="34" text-anchor="middle" fill="{TEXT_DARK}" '
            f'font-size="26" font-weight="bold">{self._t("name")}</text>'
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
            label = f"{at_g}C"
            svg.append(
                f'<text x="{x}" y="{plot_bottom + 20}" text-anchor="middle" '
                f'fill="{TEXT_DARK if at_g == 0 else TEXT}" font-size="16" '
                f'font-weight="bold">{label}</text>'
            )

        # ---- curve value labels at each AT tick (bold, above the curve) ----
        # Skip labels near the live dot: the live + threshold pills show exact
        # temps there (central pill reaches ~240px/85px), a tick label under
        # them collides.
        try:
            _at_skip = float(at_live) if at_live is not None else None
        except (TypeError, ValueError):
            _at_skip = None
        _dx_e = _dy_e = None
        if _at_skip is not None:
            _raw_e = target_live if is_curve_mode else fixed
            if _raw_e is not None:
                try:
                    _tgt_e = float(_raw_e)
                    _dx_e = max(pad_l + 14, min(plot_right - 14, round(x_at(_at_skip), 1)))
                    _dy_e = max(pad_t + 14, min(plot_bottom - 14, round(y_flow(_tgt_e), 1)))
                except (TypeError, ValueError):
                    _dx_e = _dy_e = None
        for at_g in (-30, -20, -10, 0, 10, 20):
            x = round(x_at(at_g), 1)
            cv = clamp(calc_curve_target(at_g, slope, offset, base=0.0), r10, r11)
            yv = round(y_flow(cv), 1)
            if (_dx_e is not None and _dy_e is not None
                    and abs(x - _dx_e) < 240 and abs(yv - 8 - _dy_e) < 85):
                continue
            svg.append(
                f'<text x="{x}" y="{yv - 8}" text-anchor="middle" {HALO} '
                f'fill="{TEXT_DARK}" font-size="15" font-weight="bold">'
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
                f'fill="{TEXT}" font-size="16">{f}C</text>'
            )

        # ---- axis titles ----
        svg.append(
            f'<text x="{pad_l + plot_w // 2}" y="{plot_bottom + 38}" text-anchor="middle" '
            f'fill="{TEXT}" font-size="16">{self._t("axis_x")}</text>'
        )
        svg.append(
            f'<text x="26" y="{pad_t + plot_h // 2}" text-anchor="middle" fill="{TEXT}" '
            f'font-size="16" transform="rotate(-90 26, {pad_t + plot_h // 2})">'
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

        # ---- heating hysteresis band (R04 start below, R05 idle above) ----
        # Per-step center follows the ACTIVE target (curve or fixed setpoint);
        # lower sub-band (green) = heating-demand side, upper (slate) = idle side.
        curve_pts = []
        lo_pts = []
        hi_pts = []
        for i in range(int(AT_MIN * 2), int(AT_MAX * 2) + 1):
            at_step = i / 2.0
            if is_curve_mode:
                raw_val = calc_curve_target(at_step, slope, offset, base=0.0)
            else:
                raw_val = fixed
            c = clamp(raw_val, r10, r11)
            lo = clamp(c - r04, r10, r11)
            hi = clamp(c + r05, r10, r11)
            curve_pts.append((round(x_at(at_step), 1), round(y_flow(c), 1)))
            lo_pts.append((round(x_at(at_step), 1), round(y_flow(lo), 1)))
            hi_pts.append((round(x_at(at_step), 1), round(y_flow(hi), 1)))
        poly_pts = " ".join(f"{x},{y}" for x, y in curve_pts)
        poly_fill = " ".join(
            f"{x},{y}"
            for x, y in curve_pts
            + [(curve_pts[-1][0], plot_bottom), (curve_pts[0][0], plot_bottom)]
        )
        # lower sub-band: curve -> start boundary
        lo_fill = " ".join(f"{x},{y}" for x, y in curve_pts + lo_pts[::-1])
        # upper sub-band: curve -> stop boundary
        hi_fill = " ".join(f"{x},{y}" for x, y in curve_pts + hi_pts[::-1])
        lo_line = " ".join(f"{x},{y}" for x, y in lo_pts)
        hi_line = " ".join(f"{x},{y}" for x, y in hi_pts)

        # ---- hysteresis band fills + dashed boundaries (under the main line) ----
        svg.append(f'<polygon points="{lo_fill}" fill="{BAND_LO_FILL}"/>')
        svg.append(f'<polygon points="{hi_fill}" fill="{BAND_HI_FILL}"/>')
        svg.append(
            f'<polyline fill="none" stroke="{START_COL}" stroke-width="2" '
            f'stroke-dasharray="7 5" opacity="0.85" points="{lo_line}"/>'
        )
        svg.append(
            f'<polyline fill="none" stroke="{STOP_COL}" stroke-width="2" '
            f'stroke-dasharray="7 5" opacity="0.85" points="{hi_line}"/>'
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

        # ---- live dot (single) on the ACTIVE target ----
        # Curve target in curve mode (= device live_target, hence the old
        # violet duplicate is gone), fixed setpoint otherwise.
        active_target = target_live if is_curve_mode else fixed
        if at_live is not None and active_target is not None:
            dx = round(x_at(float(at_live)), 1)
            dy = round(y_flow(float(active_target)), 1)
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

            # ---- live cluster: target number at the dot, start/stop apart ----
            # The target may drive inlet, outlet or room temp (H25) — so the
            # central pill shows ONLY the number, no words that could be wrong.
            # Stop pill rides above its marker, start pill below; the central
            # number sits at dot height in the middle. Threshold pills yield
            # (move further out) if they would touch the central one.
            try:
                _tgt_f = float(active_target)
            except (TypeError, ValueError):
                _tgt_f = None
            _thr = None
            _box_hi = None
            _box_lo = None
            _hy = _ly = 0.0
            _show_lo = _show_hi = False
            _lo_label = _hi_label = ""
            _lx_lo = _lx_hi = 0.0
            _ly_hi_p = _ly_lo_p = 0.0
            _lw_lo = _lw_hi = 0.0
            if _tgt_f is not None:
                _c_live = clamp(_tgt_f, r10, r11)
                _lo_live = clamp(_c_live - r04, r10, r11)
                _hi_live = clamp(_c_live + r05, r10, r11)
                _ly = round(y_flow(_lo_live), 1)
                _hy = round(y_flow(_hi_live), 1)
                _show_lo = abs(_lo_live - _c_live) >= 0.3
                _show_hi = abs(_hi_live - _c_live) >= 0.3
                _lo_label = f"{self._t('legend_start')} {_lo_live:.1f}C"
                _hi_label = f"{self._t('legend_stop')} {_hi_live:.1f}C"
                _lw_lo = _text_w(_lo_label, font_size=15) + 16
                _lw_hi = _text_w(_hi_label, font_size=15) + 16

                def _pill_side(mx, lw, prefer_right):
                    if prefer_right:
                        lx = mx + 14
                        if lx + lw > plot_right - 4:
                            lx = mx - 14 - lw
                    else:
                        lx = mx - 14 - lw
                        if lx < pad_l + 4:
                            lx = mx + 14
                    return lx

                def _pill_top(my, anchor, lh=24):
                    if anchor == "above":
                        ly_p = my - lh - 8
                    elif anchor == "below":
                        ly_p = my + 8
                    else:
                        ly_p = my - lh / 2
                    return max(pad_t + 4, min(plot_bottom - lh - 4, ly_p))

                _lx_lo = _pill_side(dx, _lw_lo, False)
                _lx_hi = _pill_side(dx, _lw_hi, True)
                _ly_hi_p = _pill_top(_hy, "above")
                _ly_lo_p = _pill_top(_ly, "below")
                _thr = True

            def _x_overlap(b1, b2, margin=2):
                return (b1 is not None and b2 is not None
                        and b1[0] < b2[2] + margin and b2[0] < b1[2] + margin)

            # ---- central pill: just the target number, at dot height ----
            txt = f"{float(active_target):.1f}C"
            txt_w = _text_w(txt, font_size=16)
            pill_pad = 8
            pill_h = 26
            pill_w = txt_w + pill_pad * 2
            dot_r = 7  # match the circle r above
            if dx + 14 + pill_w <= plot_right - 4:
                pill_x = dx + 14
            else:
                pill_x = dx - 14 - pill_w
            pill_y = round(dy - pill_h / 2, 1)
            pill_y = max(pad_t + 4, min(plot_bottom - pill_h - 4, pill_y))
            box_c = (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h)

            # thresholds yield to the central pill: move further out as needed
            if _thr:
                if _show_hi:
                    _box_hi = (_lx_hi, _ly_hi_p, _lx_hi + _lw_hi, _ly_hi_p + 24)
                    if _x_overlap(box_c, _box_hi) and _box_hi[3] > box_c[1] - 6:
                        _ly_hi_p = max(pad_t + 4, box_c[1] - 6 - 24)
                        _box_hi = (_lx_hi, _ly_hi_p, _lx_hi + _lw_hi, _ly_hi_p + 24)
                if _show_lo:
                    _box_lo = (_lx_lo, _ly_lo_p, _lx_lo + _lw_lo, _ly_lo_p + 24)
                    if _x_overlap(box_c, _box_lo) and _box_lo[1] < box_c[3] + 6:
                        _ly_lo_p = min(plot_bottom - 28, box_c[3] + 6)
                        _box_lo = (_lx_lo, _ly_lo_p, _lx_lo + _lw_lo, _ly_lo_p + 24)

            # short horizontal connector from dot edge to the number pill
            if pill_x > dx:
                svg.append(
                    f'<line x1="{dx + dot_r}" y1="{dy}" x2="{pill_x}" y2="{dy}" '
                    f'stroke="{DOT}" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.7"/>'
                )
            else:
                svg.append(
                    f'<line x1="{dx - dot_r}" y1="{dy}" x2="{pill_x + pill_w}" y2="{dy}" '
                    f'stroke="{DOT}" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.7"/>'
                )
            svg.append(
                f'<rect x="{pill_x}" y="{pill_y}" width="{pill_w}" '
                f'height="{pill_h}" rx="4" fill="{BG}" stroke="{DOT}" '
                f'stroke-width="1.5" opacity="0.9"/>'
            )
            svg.append(
                f'<text x="{pill_x + pill_w / 2}" y="{pill_y + 17}" '
                f'text-anchor="middle" fill="{DOT}" font-size="16" font-weight="bold">'
                f'{txt}</text>'
            )

            # ---- hysteresis thresholds at live AT (dotted-outline markers) ----
            if _thr:
                # thin dotted range line through the dot
                svg.append(
                    f'<line x1="{dx}" y1="{_hy}" x2="{dx}" y2="{_ly}" '
                    f'stroke="{DOT}" stroke-width="2" stroke-dasharray="2 4" opacity="0.55"/>'
                )

                def _side_pill(mx, my, label, color, lx, ly_p, font_size=15):
                    lw = _text_w(label, font_size=font_size) + 16
                    lh = 24
                    anchor = "start" if lx > mx else "end"
                    ex = lx if anchor == "start" else lx + lw
                    svg.append(
                        f'<line x1="{mx}" y1="{my}" x2="{ex}" y2="{ly_p + lh / 2}" '
                        f'stroke="{color}" stroke-width="1.5" stroke-dasharray="3 4" opacity="0.8"/>'
                    )
                    svg.append(
                        f'<rect x="{lx}" y="{ly_p}" width="{lw}" '
                        f'height="{lh}" rx="4" fill="{BG}" stroke="{color}" '
                        f'stroke-width="1.5" opacity="0.95"/>'
                    )
                    tx = lx + 8 if anchor == "start" else lx + lw - 8
                    svg.append(
                        f'<text x="{tx}" y="{ly_p + 17}" text-anchor="{anchor}" '
                        f'fill="{color}" font-size="{font_size}" font-weight="bold">'
                        f'{label}</text>'
                    )

                if _show_lo:
                    svg.append(
                        f'<circle cx="{dx}" cy="{_ly}" r="6" fill="{BG}" '
                        f'stroke="{START_COL}" stroke-width="2" stroke-dasharray="3 3"/>'
                    )
                    _side_pill(dx, _ly, _lo_label, START_COL, _lx_lo, _ly_lo_p)
                if _show_hi:
                    svg.append(
                        f'<circle cx="{dx}" cy="{_hy}" r="6" fill="{BG}" '
                        f'stroke="{STOP_COL}" stroke-width="2" stroke-dasharray="3 3"/>'
                    )
                    _side_pill(dx, _hy, _hi_label, STOP_COL, _lx_hi, _ly_hi_p)

        # ---- legend (fixed 2x2 grid + summary; column x-positions are fixed
        # so labels can never drift into each other in any language) ----
        ly1 = plot_bottom + 72
        ly2 = plot_bottom + 100
        ly_sum = plot_bottom + 128
        svg.append(
            f'<rect x="{pad_l}" y="{plot_bottom + 46}" width="{plot_w}" '
            f'height="{legend_h - 8}" fill="#020617" stroke="{AXIS}" rx="6"/>'
        )
        col1 = pad_l + 16
        col2 = pad_l + 16 + plot_w // 2
        SWATCH_W = 26
        LEGEND_GAP = 8  # marker-to-text gap (breathing room, overlap-proof)

        def _legend_line(x, y, color, label, active, dash=False,
                         text_color=None, font_weight="normal"):
            opacity = 1.0 if active else 0.45
            dash_frag = ' stroke-dasharray="6 4"' if dash else ""
            svg.append(
                f'<line x1="{x}" y1="{y}" x2="{x + SWATCH_W}" y2="{y}" '
                f'stroke="{color}" stroke-width="4"{dash_frag} opacity="{opacity}"/>'
            )
            fw = f' font-weight="{font_weight}"' if font_weight != "normal" else ""
            svg.append(
                f'<text x="{x + SWATCH_W + LEGEND_GAP}" y="{y + 6}" fill="{text_color}" '
                f'font-size="15"{fw}>{label}</text>'
            )

        def _legend_dot(x, y, color, label, text_color, font_weight="normal"):
            svg.append(
                f'<circle cx="{x + SWATCH_W - 6}" cy="{y}" r="6" fill="{color}"/>'
            )
            fw = f' font-weight="{font_weight}"' if font_weight != "normal" else ""
            svg.append(
                f'<text x="{x + SWATCH_W + LEGEND_GAP}" y="{y + 6}" fill="{text_color}" '
                f'font-size="15"{fw}>{label}</text>'
            )

        def _legend_band(x, y, label):
            # mini preview of the two-tone hysteresis band with dashed edges
            svg.append(
                f'<rect x="{x}" y="{y - 7}" width="{SWATCH_W}" height="7" '
                f'fill="{BAND_HI_FILL}" stroke="{STOP_COL}" stroke-width="1" '
                f'stroke-dasharray="3 2"/>'
            )
            svg.append(
                f'<rect x="{x}" y="{y}" width="{SWATCH_W}" height="7" '
                f'fill="{BAND_LO_FILL}" stroke="{START_COL}" stroke-width="1" '
                f'stroke-dasharray="3 2"/>'
            )
            svg.append(
                f'<line x1="{x}" y1="{y}" x2="{x + SWATCH_W}" y2="{y}" '
                f'stroke="{CURVE}" stroke-width="2"/>'
            )
            svg.append(
                f'<text x="{x + SWATCH_W + LEGEND_GAP}" y="{y + 6}" fill="{TEXT}" '
                f'font-size="15">{label}</text>'
            )

        # row 1: active target line vs inactive line
        _legend_line(col1, ly1, CURVE, self._t("legend_curve"),
                     active=is_curve_mode, dash=not is_curve_mode,
                     text_color=TEXT_DARK if is_curve_mode else TEXT,
                     font_weight="bold" if is_curve_mode else "normal")
        _legend_line(col2, ly1, FIXED_COL, self._t("legend_fixed"),
                     active=not is_curve_mode, dash=is_curve_mode,
                     text_color=TEXT_DARK if not is_curve_mode else TEXT,
                     font_weight="bold" if not is_curve_mode else "normal")
        # row 2: live dot + hysteresis band
        _legend_dot(col1, ly2, DOT, self._t("legend_live"),
                    text_color=TEXT_DARK, font_weight="bold")
        _legend_band(col2, ly2, self._t("legend_heat"))

        # ---- summary ----
        summary = (
            f'slope {slope:.2f}  ·  offset {offset:.1f}C  ·  '
            f'{self._t("legend_band")}: {r10:.0f}–{r11:.0f}C  ·  '
            f'R04 -{r04:.1f} / R05 +{r05:.1f}C  ·  '
            f'{self._t("mode_curve" if is_curve_mode else "mode_fixed")}'
        )
        svg.append(
            f'<text x="{pad_l + 8}" y="{ly_sum + 4}" fill="{TEXT}" '
            f'font-size="15">{summary}</text>'
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
