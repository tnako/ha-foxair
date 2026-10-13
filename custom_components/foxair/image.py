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
temperature dotted-outline markers give both threshold temps.

Labels are placed by _Layout, a greedy candidate search over an obstacle map
(curve, band lines, markers, placed labels): every curve point keeps its
value, and the live target with its start/stop values is one card on a
leader line. The bottom is a stat footer that wraps into rows.

Mode (driven by H36 / register 1236):
  * H36 = 1  -> AT-compensation (curve) mode:
                target(AT) = offset - slope * AT, clamped to [R10, R11]
                drawn as the main cyan curve line.
  * H36 = 2  -> V3.5 7-point curve: setpoints at -20/-10/-5/0/5/10/20 C,
                linearly interpolated, drawn as the cyan line with point markers.
  * H36 = 0  -> constant (fixed) mode:
                target = R02 (register 1158), drawn as amber line.
                Weather-compensation curve shown faintly as a preview.

Footer adds the V3.5 outdoor sensor source (1463/2033) and the
heating/summer cut-off (1464/1465/2146) when the unit reports them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.image import ImageEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.translation import async_get_translations

from .const import main_device, get_device_prefix, get_slave_id, bind_device_info
from .heating_curve import (active_control, calc_curve_target, calc_points_target, curve_points,
                            curve_target_for_at, outdoor_source, summer_cutoff)

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
    "cap_mode": "Mode",
    "cap_slope": "Slope",
    "cap_design": "Flow at 0C",
    "cap_limits": "Limits (R10\u2013R11)",
    "cap_start": "Start (R04)",
    "cap_stop": "Stop (R05)",
    "legend_heat": "Heating range (R04-R05)",
    "legend_start": "Start heating",
    "legend_stop": "Stop heating",
    "mode_curve": "AT compensation (curve)",
    "mode_fixed": "Constant (fixed)",
    "mode_points": "7-point curve",
    "legend_points": "Curve points",
    "cap_points": "Points (H36=2)",
    "cap_point0": "0C point",
    "cap_at_source": "Outdoor sensor",
    "at_external": "External",
    "at_internal": "Internal T04",
    "at_fallback": "T04 (external invalid)",
    "cap_cutoff": "Summer cut-off",
    "cutoff_active": "Active",
    "cutoff_armed": "from",
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


def _seg_hits_box(x1, y1, x2, y2, box) -> bool:
    """Liang-Barsky clip: does the segment touch the box."""
    bx0, by0, bx1, by1 = box
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - bx0), (dx, bx1 - x1), (-dy, y1 - by0), (dy, by1 - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)
    return True


def _nearest_on_box(ax, ay, box):
    return min(max(ax, box[0]), box[2]), min(max(ay, box[1]), box[3])


def _around(ax, ay, w, h, dirs, rings):
    """Candidate (box, preference penalty) around an anchor, earlier dirs preferred."""
    out = []
    for d in rings:
        for i, (ox, oy) in enumerate(dirs):
            cx = ax + ox * (d + w / 2)
            cy = ay + oy * (d + h / 2)
            out.append(((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), 0.05 * i))
    return out


def _box_dist(px, py, box):
    nx, ny = _nearest_on_box(px, py, box)
    return ((nx - px) ** 2 + (ny - py) ** 2) ** 0.5


class _Layout:
    """Greedy label placement over an obstacle map.

    Marks (curve, band lines, markers, dots) and every placed label are
    obstacles. Each label takes the candidate with the lowest collision cost
    plus distance from its anchor, so no value is ever dropped. A label that
    sits closer to another marker than to its own is penalised, so it never
    reads as that marker's value.
    """

    LABEL, MARK, CURVE, BAND, GUIDE, RIVAL = 100.0, 60.0, 20.0, 8.0, 0.1, 40.0
    PER_PX = 0.05

    def __init__(self, bounds):
        self.bounds = bounds
        self.boxes: list = []
        self.segs: list = []
        self.anchors: list = []

    def block(self, box, weight):
        self.boxes.append((box, weight))

    def block_line(self, pts, weight):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.segs.append((x1, y1, x2, y2, weight))

    def anchor(self, x, y):
        self.anchors.append((x, y))

    def _cost(self, box, anchor, leader, strict):
        gap = 10 if leader else 3
        lx0, ly0, lx1, ly1 = self.bounds
        if box[0] < lx0 or box[1] < ly0 or box[2] > lx1 or box[3] > ly1:
            return None
        g = (box[0] - gap, box[1] - gap, box[2] + gap, box[3] + gap)
        hits = [w for o, w in self.boxes
                if o[0] < g[2] and g[0] < o[2] and o[1] < g[3] and g[1] < o[3]]
        if strict and any(w >= self.LABEL for w in hits):
            return None
        cost = sum(hits)
        cost += sum(s[4] for s in self.segs if _seg_hits_box(s[0], s[1], s[2], s[3], g))
        nx, ny = _nearest_on_box(anchor[0], anchor[1], box)
        own = ((nx - anchor[0]) ** 2 + (ny - anchor[1]) ** 2) ** 0.5
        cost += self.PER_PX * own
        cost += sum(self.RIVAL for ax, ay in self.anchors
                    if (abs(ax - anchor[0]) > 1 or abs(ay - anchor[1]) > 1)
                    and _box_dist(ax, ay, box) < own + 4)
        if leader:
            cost += sum(w for o, w in self.boxes
                        if w >= self.MARK and _seg_hits_box(anchor[0], anchor[1], nx, ny, o)
                        and not (o[0] <= anchor[0] <= o[2] and o[1] <= anchor[1] <= o[3]))
        return cost

    def place(self, cands, anchor, leader=False):
        best, best_cost = None, None
        for strict in (True, False):
            for box, pref in cands:
                cost = self._cost(box, anchor, leader, strict)
                if cost is not None and (best_cost is None or cost + pref < best_cost):
                    best, best_cost = box, cost + pref
            if best is not None:
                break
        if best is None:
            box = cands[0][0]
            w, h = box[2] - box[0], box[3] - box[1]
            lx0, ly0, lx1, ly1 = self.bounds
            x0 = min(max(box[0], lx0), lx1 - w)
            y0 = min(max(box[1], ly0), ly1 - h)
            best = (x0, y0, x0 + w, y0 + h)
        self.block(best, self.LABEL)
        return best


_POINT_DIRS = ((0, -1), (0, 1), (1, -1), (-1, -1), (1, 1), (-1, 1), (1, 0), (-1, 0))
_TARGET_DIRS = ((1, 0), (-1, 0), (1, -1), (1, 1), (-1, -1), (-1, 1), (0, -1), (0, 1))
_UP_DIRS = ((1, -1), (-1, -1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, 1), (0, 1))
_DOWN_DIRS = ((1, 1), (-1, 1), (0, 1), (1, 0), (-1, 0), (1, -1), (-1, -1), (0, -1))


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
            loaded.update(self._source_labels(cat))
            self._tl = {**_TL_FALLBACK, **loaded}
            if loaded_raw:
                self._render()
        except Exception as e:  # pragma: no cover - never fatal
            _LOGGER.debug("heating-curve translations unavailable: %s", e)
            self._tl = dict(_TL_FALLBACK)

    def _t(self, key: str) -> str:
        return self._tl.get(key, _TL_FALLBACK.get(key, key))

    def _source_labels(self, cat: dict) -> dict:
        """H25 select state labels as source.<key>, so the y-axis names the controlled sensor."""
        coord = self.coordinator
        selector = ((coord.marker("control_source") or {}).get("addr_single") or {}).get("selector")
        code = (coord.get_metadata(selector).get("code") or "").lower() if selector else ""
        pfx = f"component.foxair.entity.select.foxair_{code}.state."
        return {f"source.{k[len(pfx):]}": v for k, v in cat.items() if code and k.startswith(pfx)}

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

        ctl = active_control(coord)
        sp = ((coord.marker("setpoints") if hasattr(coord, "marker") else None) or {}).get("addr_single") or {}
        slope = val(hca.get("slope"), None)
        offset = val(hca.get("offset"), None)
        fixed = val(sp.get("heating_target"), None)
        h36 = 1 if ctl.get("curve") else 0
        points = curve_points(coord) if ctl.get("curve_mode") == "points" else None
        at_live = val(hca.get("at_sensor"), None)
        live_target = val(hca.get("live_target"), None)
        r10 = val(sp.get("heating_min"), None)
        r11 = val(sp.get("heating_max"), None)
        r04 = val(sp.get("heating_start"), None)
        r05 = val(sp.get("heating_stop"), None)

        st_status = (coord.marker("status") if hasattr(coord, "marker") else None) or {}
        sts = st_status.get("addr_single", {}) or {}
        comp_freq = val(sts.get("compressor_freq"), None)
        try:
            compressor_on = comp_freq is not None and float(comp_freq) > 0
        except (TypeError, ValueError):
            compressor_on = False

        ready = (slope is not None) and (offset is not None) and (fixed is not None)
        return {
            "slope": slope, "offset": offset, "fixed": fixed,
            "h36": h36, "source": None if ctl.get("own_target") else ctl.get("source"), "at_live": at_live, "live_target": live_target,
            "r10": r10, "r11": r11, "r04": r04, "r05": r05, "ready": ready,
            "compressor_on": compressor_on,
            "points": points, "at_source": outdoor_source(coord), "cutoff": summer_cutoff(coord),
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
        pad_l, pad_r, pad_t, pad_b = 90, 50, 64, 104
        legend_h = 46
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
        points = inp.get("points") if is_curve_mode else None

        def curve_at(at_v):
            if points:
                return calc_points_target(at_v, points)
            return calc_curve_target(at_v, slope, offset, base=0.0)

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
        CUTOFF_COL = "#f97316"
        CUTOFF_FILL = "rgba(249,115,22,0.14)"
        CUTOFF_FILL_IDLE = "rgba(249,115,22,0.05)"
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
            for at_g in range(-30, 21, 10):
                x = round(x_at(at_g), 1)
                svg.append(f'<line x1="{x}" y1="{pad_t}" x2="{x}" y2="{plot_bottom}" '
                           f'stroke="{GRID}" stroke-width="1"/>')
            for fg in range(10, 71, 10):
                y = round(y_flow(fg), 1)
                svg.append(f'<line x1="{pad_l}" y1="{y}" x2="{plot_right}" y2="{y}" '
                           f'stroke="{GRID}" stroke-width="1"/>')
            svg.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{plot_bottom}" '
                       f'stroke="{AXIS}" stroke-width="2"/>')
            svg.append(f'<line x1="{pad_l}" y1="{plot_bottom}" x2="{plot_right}" y2="{plot_bottom}" '
                       f'stroke="{AXIS}" stroke-width="2"/>')
            ghost = " ".join(
                f"{round(x_at(at), 1)},{round(y_flow(min(60.0, max(20.0, 35.0 - 0.6 * at))), 1)}"
                for at in range(-30, 21, 2))
            svg.append(
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="3" opacity="0.25" '
                f'points="{ghost}">'
                f'<animate attributeName="opacity" values="0.15;0.35;0.15" dur="1.8s" '
                f'repeatCount="indefinite"/></polyline>'
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

        # ---- live device target = register 2014 (for the moving dot) ----
        # 2014 is the pump's own AT-compensated flow setpoint — the vendor
        # value, so in curve mode the dot sits exactly on the pump's target.
        # curve_target_for_at() (offset/slope formula) stays as the fallback
        # for when 2014 is missing from the poll data.
        live_target = inp.get("live_target")
        target_live = None
        if is_curve_mode and live_target is not None:
            try:
                target_live = float(live_target)
            except (TypeError, ValueError):
                target_live = None
        if target_live is None and at_live is not None and self.coordinator is not None:
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

        lay = _Layout((pad_l + 2, pad_t + 2, W - 6, plot_bottom - 2))

        # ---- reference cross at design point (AT=0 -> flow=offset) ----
        cutoff = inp.get("cutoff") or {}
        if cutoff.get("enabled") and AT_MIN < cutoff.get("threshold", AT_MAX) < AT_MAX:
            xc = round(x_at(cutoff["threshold"]), 1)
            svg.append(
                f'<rect x="{xc}" y="{pad_t}" width="{round(plot_right - xc, 1)}" '
                f'height="{plot_bottom - pad_t}" fill="{CUTOFF_FILL if cutoff.get("active") else CUTOFF_FILL_IDLE}"/>'
            )
            svg.append(
                f'<line x1="{xc}" y1="{pad_t}" x2="{xc}" y2="{plot_bottom}" '
                f'stroke="{CUTOFF_COL}" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.7"/>'
            )
            lay.block_line([(xc, pad_t), (xc, plot_bottom)], _Layout.GUIDE)
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
            lay.block((x0 - 8, y0 - 8, x0 + 8, y0 + 8), _Layout.MARK)
            lay.block_line([(x0, pad_t), (x0, plot_bottom)], _Layout.GUIDE)
            lay.block_line([(pad_l, y0), (plot_right, y0)], _Layout.GUIDE)
        except Exception:
            pass

        # ---- X axis ticks (tick marks + dots + labels) ----
        # 7-point mode adds the -5 / +5 points so every setpoint has a tick + value.
        at_ticks = [-30, -20, -10, 0, 10, 20]
        if points:
            at_ticks = sorted(set(at_ticks) | {int(a) for a, _ in points if AT_MIN <= a <= AT_MAX})
        for at_g in at_ticks:
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
        axis_y = self._tl.get(f"source.{inp.get('source')}") or self._t("axis_y")
        svg.append(
            f'<text x="{pad_l + plot_w // 2}" y="{plot_bottom + 46}" text-anchor="middle" '
            f'fill="{TEXT}" font-size="16">{self._t("axis_x")}</text>'
        )
        svg.append(
            f'<text x="26" y="{pad_t + plot_h // 2}" text-anchor="middle" fill="{TEXT}" '
            f'font-size="16" transform="rotate(-90 26, {pad_t + plot_h // 2})">'
            f'{axis_y}</text>'
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
                raw_val = curve_at(at_step)
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

        lay.block_line(lo_pts, _Layout.BAND)
        lay.block_line(hi_pts, _Layout.BAND)

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

        # ---- main line (only the ACTIVE target is drawn) ----
        fixed_y = round(y_flow(clamp(fixed, r10, r11)), 1)
        if is_curve_mode:
            svg.append(f'<polygon points="{poly_fill}" fill="{CURVE_FILL}"/>')
            svg.append(
                f'<polyline fill="none" stroke="{CURVE}" stroke-width="4" '
                f'stroke-linejoin="round" points="{poly_pts}"/>'
            )
            lay.block_line(curve_pts, _Layout.CURVE)
            for at_p, v_p in points or ():
                if AT_MIN <= at_p <= AT_MAX:
                    xm, ym = round(x_at(at_p), 1), round(y_flow(clamp(v_p, r10, r11)), 1)
                    lay.block((xm - 8, ym - 8, xm + 8, ym + 8), _Layout.MARK)
                    lay.anchor(xm, ym)
                    svg.append(
                        f'<rect x="{round(x_at(at_p) - 6, 1)}" y="{round(y_flow(clamp(v_p, r10, r11)) - 6, 1)}" '
                        f'width="12" height="12" rx="2" fill="{BG}" stroke="{CURVE}" stroke-width="3"/>'
                    )
        else:
            svg.append(
                f'<line x1="{pad_l}" y1="{fixed_y}" x2="{plot_right}" y2="{fixed_y}" '
                f'stroke="{FIXED_COL}" stroke-width="4"/>'
            )
            fixed_txt = f"{clamp(fixed, r10, r11):.0f}C"
            svg.append(
                f'<text x="{pad_l + 10}" y="{fixed_y - 10}" {HALO} fill="{FIXED_COL}" '
                f'font-size="16" font-weight="bold">{fixed_txt}</text>'
            )
            lay.block_line([(pad_l, fixed_y), (plot_right, fixed_y)], _Layout.CURVE)
            lay.block((pad_l + 8, fixed_y - 24, pad_l + 12 + _text_w(fixed_txt, 16), fixed_y - 6),
                      _Layout.LABEL)

        # ---- live dot (single) on the ACTIVE target ----
        # Curve mode = device register 2014 (live_target), fixed mode =
        # the R02 setpoint. The formula stays only as fallback in target_live.
        active_target = target_live if is_curve_mode else fixed
        compressor_on = bool(inp.get("compressor_on"))
        dot_fill = DOT if compressor_on else "#64748b"
        live = None
        if at_live is not None and active_target is not None:
            try:
                live = (float(at_live), float(active_target))
            except (TypeError, ValueError):
                live = None
        thresholds = []
        dx = dy = 0.0
        if live is not None:
            dx = max(pad_l, min(plot_right, round(x_at(live[0]), 1)))
            dy = max(pad_t, min(plot_bottom, round(y_flow(live[1]), 1)))
            # Start (R04) below / stop (R05) above the target, at the live AT.
            c_live = clamp(live[1], r10, r11)
            for value, color, key in ((clamp(c_live + r05, r10, r11), STOP_COL, "legend_stop"),
                                      (clamp(c_live - r04, r10, r11), START_COL, "legend_start")):
                if abs(value - c_live) >= 0.3:
                    thresholds.append((round(y_flow(value), 1), value, color, key))
            if thresholds:
                ys = [t[0] for t in thresholds] + [dy]
                svg.append(
                    f'<line x1="{dx}" y1="{min(ys)}" x2="{dx}" y2="{max(ys)}" '
                    f'stroke="{DOT}" stroke-width="2" stroke-dasharray="2 4" opacity="0.55"/>'
                )
                lay.block_line([(dx, min(ys)), (dx, max(ys))], _Layout.BAND)
            for ty, _v, color, _k in thresholds:
                svg.append(
                    f'<circle cx="{dx}" cy="{ty}" r="6" fill="{BG}" '
                    f'stroke="{color}" stroke-width="2" stroke-dasharray="3 3"/>'
                )
                lay.block((dx - 8, ty - 8, dx + 8, ty + 8), _Layout.MARK)
                lay.anchor(dx, ty)
            if compressor_on:
                svg.append(
                    f'<circle cx="{dx}" cy="{dy}" r="9" fill="none" '
                    f'stroke="{DOT}" stroke-width="2" opacity="0.8">'
                    f'<animate attributeName="r" values="9;16;9" dur="2.4s" repeatCount="indefinite"/>'
                    f'<animate attributeName="opacity" values="0.8;0;0.8" dur="2.4s" repeatCount="indefinite"/>'
                    f'</circle>'
                )
            svg.append(
                f'<circle cx="{dx}" cy="{dy}" r="9" fill="#fff" opacity="0.9"/>'
            )
            svg.append(
                f'<circle cx="{dx}" cy="{dy}" r="7" fill="{dot_fill}" stroke="#fff" '
                f'stroke-width="2"/>'
            )
            lay.block((dx - 11, dy - 11, dx + 11, dy + 11), _Layout.MARK)
            lay.anchor(dx, dy)

        # ---- labels: placed after every mark, drawn on top ----
        # The live card goes first (it may move out on a leader line), then
        # each curve value next to its own point.
        def _leader(ax, ay, r, box, color):
            nx, ny = _nearest_on_box(ax, ay, box)
            dist = ((nx - ax) ** 2 + (ny - ay) ** 2) ** 0.5
            if dist <= r + 2:
                return
            sx, sy = ax + (nx - ax) * r / dist, ay + (ny - ay) * r / dist
            svg.append(
                f'<line x1="{sx:.1f}" y1="{sy:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" '
                f'stroke="{color}" stroke-width="1.5" opacity="0.9"/>'
            )

        live_card = None
        if live is not None:
            # One card for the live point: stop / target / start rows in the
            # same vertical order as their markers, one leader to the dot.
            target_key = "legend_curve" if is_curve_mode else "legend_fixed"
            rows = [(f"{self._t(key)} {value:.1f}C", color, False)
                    for ty, value, color, key in thresholds if ty < dy]
            rows.append((f"{self._t(target_key)} {live[1]:.1f}C", DOT, True))
            rows += [(f"{self._t(key)} {value:.1f}C", color, False)
                     for ty, value, color, key in thresholds if ty > dy]
            row_h = 22
            card_w = max(_text_w(t, 15) for t, _c, _m in rows) + 38
            card_h = row_h * len(rows) + 10
            box = lay.place(_around(dx, dy, card_w, card_h, _TARGET_DIRS, (16, 30, 50, 80, 120, 170)),
                            (dx, dy), leader=True)
            live_card = (box, rows)

        if is_curve_mode:
            anchors = ([(a, v) for a, v in points if AT_MIN <= a <= AT_MAX] if points
                       else [(a, curve_at(a)) for a in at_ticks])
            if not points:
                for at_p, v_p in anchors:
                    lay.anchor(x_at(at_p), y_flow(clamp(v_p, r10, r11)))
            for at_p, v_p in anchors:
                cv = clamp(v_p, r10, r11)
                txt = f"{cv:.0f}"
                px, py = x_at(at_p), y_flow(cv)
                if live is not None and abs(px - dx) < 12 and abs(py - dy) < 12:
                    continue
                box = lay.place(_around(px, py, _text_w(txt, 15) + 4, 17, _POINT_DIRS, (9, 16, 26)),
                                (px, py))
                svg.append(
                    f'<text x="{(box[0] + box[2]) / 2:.1f}" y="{(box[1] + box[3]) / 2 + 5.2:.1f}" '
                    f'text-anchor="middle" {HALO} fill="{TEXT_DARK}" font-size="15" '
                    f'font-weight="bold">{txt}</text>'
                )

        if live_card is not None:
            box, rows = live_card
            _leader(dx, dy, 9, box, DOT)
            svg.append(
                f'<rect x="{box[0]:.1f}" y="{box[1]:.1f}" width="{box[2] - box[0]:.1f}" '
                f'height="{box[3] - box[1]:.1f}" rx="6" fill="{BG}" stroke="{DOT}" '
                f'stroke-width="1.5" opacity="0.95"/>'
            )
            ry = box[1] + 5
            for label, color, main in rows:
                cy = ry + row_h / 2
                mx = box[0] + 15
                if main:
                    svg.append(f'<circle cx="{mx:.1f}" cy="{cy:.1f}" r="5" fill="{dot_fill}" '
                               f'stroke="#fff" stroke-width="1.5"/>')
                else:
                    svg.append(f'<circle cx="{mx:.1f}" cy="{cy:.1f}" r="5" fill="{BG}" '
                               f'stroke="{color}" stroke-width="2" stroke-dasharray="3 3"/>')
                svg.append(
                    f'<text x="{box[0] + 28:.1f}" y="{cy + 5.2:.1f}" fill="{color}" '
                    f'font-size="15" font-weight="bold">{label}</text>'
                )
                ry += row_h

        # ---- stat footer (caption-over-value cells) ----
        cap_y = plot_bottom + 70
        mode_key = "mode_points" if points else "mode_curve" if is_curve_mode else "mode_fixed"
        mode_label = self._t(mode_key)
        mode_col = CURVE if is_curve_mode else FIXED_COL
        cells = [(self._t("cap_mode"), mode_label, mode_col)]
        if points:
            cells.append((self._t("cap_points"), f"{points[0][1]:.0f}\u2192{points[-1][1]:.0f}C", TEXT_DARK))
            # 0 degC point is register 1235 (the linear offset), not one of the
            # six extra points: show it so "45 everywhere, 32 at 0" is explained.
            p0 = next((v for a, v in points if a == 0), None)
            if p0 is not None:
                cells.append((self._t("cap_point0"), f"{p0:.0f}C", TEXT_DARK))
        elif is_curve_mode:
            cells.append((self._t("cap_design"), f"{offset:.0f}C", TEXT_DARK))
            cells.append((self._t("cap_slope"), f"{slope:.2f}", TEXT_DARK))
        else:
            cells.append((self._t("legend_fixed"), f"{fixed:.0f}C", TEXT_DARK))
        cells.append((self._t("cap_limits"), f"{r10:.0f}\u2013{r11:.0f}C", TEXT_DARK))
        cells.append((self._t("cap_start"), f"\u2212{r04:.1f}C", START_COL))
        cells.append((self._t("cap_stop"), f"+{r05:.1f}C", STOP_COL))
        at_source = inp.get("at_source")
        if at_source:
            cells.append((self._t("cap_at_source"), self._t(f"at_{at_source}"),
                          CUTOFF_COL if at_source == "fallback" else TEXT_DARK))
        if cutoff.get("enabled"):
            cut_val = (self._t("cutoff_active") if cutoff.get("active")
                       else f"{self._t('cutoff_armed')} {cutoff['threshold']:.0f}C")
            cells.append((self._t("cap_cutoff"), cut_val, CUTOFF_COL))

        row_h = 56
        rows = [[]]
        cx = pad_l
        for cap, val, vcol in cells:
            cell_w = max(_text_w(cap, font_size=13) + 8,
                         _text_w(val, font_size=18) + 8, 70)
            if cx + cell_w > plot_right and rows[-1]:
                rows.append([])
                cx = pad_l
            rows[-1].append((cx, cell_w, cap, val, vcol))
            cx += cell_w + 34
        for r_i, row in enumerate(rows):
            ry = cap_y + r_i * row_h
            for c_i, (cx, cell_w, cap, val, vcol) in enumerate(row):
                svg.append(
                    f'<text x="{cx:.1f}" y="{ry}" fill="{TEXT}" font-size="13" '
                    f'letter-spacing="0.5">{cap.upper()}</text>'
                )
                svg.append(
                    f'<text x="{cx:.1f}" y="{ry + 24}" fill="{vcol}" font-size="18" '
                    f'font-weight="bold">{val}</text>'
                )
                if c_i < len(row) - 1:
                    xd = cx + cell_w + 17
                    svg.append(
                        f'<line x1="{xd:.1f}" y1="{ry - 12}" x2="{xd:.1f}" '
                        f'y2="{ry + 28}" stroke="{GRID}" stroke-width="1"/>'
                    )
        if len(rows) > 1:
            extra = (len(rows) - 1) * row_h
            svg[0] = svg[0].replace(f'height="{H}"', f'height="{H + extra}"').replace(
                f'viewBox="0 0 {W} {H}"', f'viewBox="0 0 {W} {H + extra}"')

        svg.append("</svg>")
        self._image_bytes = "".join(svg).encode("utf-8")
        self._image_last_updated = datetime.now(timezone.utc)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = entry.runtime_data
    if not coord:
        return
    entity = FoxAirHeatingCurveImage(coord, entry.entry_id)
    await entity.async_load_translations()
    async_add_entities([entity])
