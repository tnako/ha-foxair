"""Image platform — heating curve on device page without YAML.

Renders image.foxair_heating_curve on the FoxAir Heat Pump device.
Same math as views.py/svg but as PNG via PIL so it shows inside
/config/devices/device/<id> as a thumbnail.

AT is 2048 (T04), slope 1234 DIGI5/10, offset 1235 TEMP1/10, enable 1236,
clamp R10 1164 / R11 1165, fixed R02 1158, after-comp 2014 for validation.
"""
from __future__ import annotations
import io
import logging
from datetime import datetime, timezone
from homeassistant.components.image import ImageEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import main_device
from .heating_curve import calc_curve_target, curve_target_for_at

_LOGGER = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:
    HAS_PIL = False


class FoxAirHeatingCurveImage(CoordinatorEntity, ImageEntity):
    _attr_has_entity_name = False
    _attr_name = "Heating Curve"
    _attr_icon = "mdi:chart-bell-curve"
    _attr_content_type = "image/png"

    def __init__(self, coordinator, entry_id: str):
        CoordinatorEntity.__init__(self, coordinator)
        # ImageEntity needs hass in ctor (HA 2024+)
        ImageEntity.__init__(self, coordinator.hass)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_heating_curve_image"
        self._attr_device_info = main_device(entry_id)
        # entity_id follows HA naming: image.foxair_heating_curve
        self.entity_id = "image.foxair_heating_curve"
        self._image_bytes: bytes | None = None
        self._image_last_updated: datetime | None = None
        self._render()  # initial empty render even before first coordinator data

    @property
    def image_last_updated(self):
        return self._image_last_updated

    async def async_image(self) -> bytes | None:
        # HA calls this when frontend requests /api/image_proxy/image.foxair_heating_curve
        if self._image_bytes is None:
            self._render()
        return self._image_bytes

    def _handle_coordinator_update(self) -> None:
        self._render()
        super()._handle_coordinator_update()

    def _render(self):
        if not HAS_PIL:
            # fallback 1x1 transparent png
            self._image_bytes = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n"
                b"-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            self._image_last_updated = datetime.now(timezone.utc)
            return
        coord = self.coordinator
        # defaults (same as views.py)
        slope = 0.3
        offset = 37.0
        r10, r11 = 20.0, 60.0
        fixed = None
        at_live = None
        target_live = None
        after_comp = None
        if coord and getattr(coord, "data", None):
            try:
                rec_slope = coord.data.get(1234)
                if rec_slope:
                    slope = float(rec_slope.get("value", slope))
                if slope and slope > 5:
                    slope = slope / 10.0
                rec_off = coord.data.get(1235)
                if rec_off:
                    offset = float(rec_off.get("value", offset))
                r10 = float(coord.data.get(1164, {}).get("value", r10)) if coord.data.get(1164) else r10
                r11 = float(coord.data.get(1165, {}).get("value", r11)) if coord.data.get(1165) else r11
                rec_at = coord.data.get(2048)
                if rec_at:
                    try:
                        at_live = float(rec_at.get("value"))
                    except:
                        at_live = None
                if at_live is not None:
                    try:
                        target_live = curve_target_for_at(coord, at_live)
                    except:
                        target_live = None
                rec_ac = coord.data.get(2014)
                if rec_ac:
                    try:
                        after_comp = float(rec_ac.get("value"))
                    except:
                        after_comp = None
                rec_f = coord.data.get(1158)
                if rec_f:
                    try:
                        fixed = float(rec_f.get("value"))
                    except:
                        fixed = None
            except Exception as e:
                _LOGGER.debug("image render coord read fail %s", e)

        W, H = 800, 400
        pad_l, pad_r, pad_t, pad_b = 60, 20, 30, 40
        plot_w = W - pad_l - pad_r
        plot_h = H - pad_t - pad_b

        def x_at(v: float) -> float:
            return pad_l + (v + 20) / 40 * plot_w

        def y_flow(v: float) -> float:
            # flow 15..65 maps to y
            return pad_t + (65 - v) / 50 * plot_h

        # clamp helper
        def clamp(v, lo, hi):
            return max(lo, min(hi, v))

        # palette
        BG = (15, 23, 42)  # #0f172a
        GRID = (30, 41, 59)  # #1e293b
        AXIS = (51, 65, 85)  # #334155
        TEXT = (148, 163, 184)  # #94a3b8
        TITLE_TXT = (226, 232, 240)
        CURVE = (56, 189, 248)  # #38bdf8
        FIXED_COL = (245, 158, 11)  # #f59e0b
        DOT = (34, 197, 94)  # #22c55e
        AFTER_COL = (167, 139, 250)

        im = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(im)
        # use default bitmap font (no external deps)
        try:
            font_title = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_tiny = ImageFont.load_default()
        except:
            font_title = font_small = font_tiny = None

        # title
        title = f"FoxAir Heating Curve  AT vs Flow  (slope {slope:.2f}  offset {offset:.1f}C)"
        # centered approx
        draw.text((W // 2, 6), title, fill=TITLE_TXT, font=font_title, anchor="mt")

        # axes
        draw.line([(pad_l, pad_t), (pad_l, H - pad_b)], fill=AXIS, width=1)
        draw.line([(pad_l, H - pad_b), (W - pad_r, H - pad_b)], fill=AXIS, width=1)

        # vertical grid AT
        for at_g in [-20, -10, 0, 10, 20]:
            x = x_at(at_g)
            draw.line([(x, pad_t), (x, H - pad_b)], fill=GRID, width=1)
            lab = f"{at_g}C"
            draw.text((x, H - pad_b + 6), lab, fill=TEXT, font=font_small, anchor="mt")
        # horizontal grid flow
        for f in [20, 30, 40, 50, 60]:
            y = y_flow(f)
            draw.line([(pad_l, y), (W - pad_r, y)], fill=GRID, width=1)
            draw.text((pad_l - 6, y), f"{f}C", fill=TEXT, font=font_small, anchor="rm")

        # R10..R11 band
        y_r11 = y_flow(r11)
        y_r10 = y_flow(r10)
        # translucent band via rectangle with alpha blend (simulate with lighter bg rect)
        band_col = (14, 165, 233)  # approx with opacity 0.06 over BG - just draw faint rect
        # draw band as thin outline + fill using stipple via overlay rectangle semi-transparent not easy without RGBA
        # use RGBA overlay
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle([(pad_l, y_r11), (W - pad_r, y_r10)], fill=(56, 189, 248, 18))
        im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(im)
        draw.text((W - pad_r, y_r11 - 10), f"R10 {r10:.0f} - R11 {r11:.0f}", fill=CURVE, font=font_tiny, anchor="rb")

        # curve polyline -20..20 step 0.5 for smoothness
        pts = []
        for i in range(-20 * 2, 20 * 2 + 1):
            at_step = i / 2.0
            raw = calc_curve_target(at_step, slope, offset)
            clamped = clamp(raw, r10, r11)
            # also show beyond Y range clamped to plot
            pts.append((x_at(at_step), y_flow(clamped)))
        # draw curve as segments
        for a, b in zip(pts, pts[1:]):
            draw.line([a, b], fill=CURVE, width=3)

        # fixed line
        if fixed is not None:
            fy = y_flow(clamp(fixed, 15, 65))
            # dashed
            dash = 6
            x = pad_l
            while x < W - pad_r:
                x2 = min(x + dash, W - pad_r)
                draw.line([(x, fy), (x2, fy)], fill=FIXED_COL, width=2)
                x += dash * 2
            draw.text((W - pad_r, fy - 10), f"Fixed R02 {fixed:.1f}C", fill=FIXED_COL, font=font_small, anchor="rb")

        # current dot
        if at_live is not None and target_live is not None:
            try:
                dot_x = x_at(float(at_live))
                dot_y = y_flow(float(target_live))
                # clip dot to plot
                if pad_l - 5 <= dot_x <= W - pad_r + 5 and pad_t - 5 <= dot_y <= H - pad_b + 5:
                    r = 7
                    # white border
                    draw.ellipse([(dot_x - r - 2, dot_y - r - 2), (dot_x + r + 2, dot_y + r + 2)], fill=(255, 255, 255))
                    draw.ellipse([(dot_x - r, dot_y - r), (dot_x + r, dot_y + r)], fill=DOT)
                    txt = f"AT {at_live:.1f} -> {target_live:.1f}C"
                    # keep label inside
                    lx = dot_x + 12
                    ly = dot_y - 12
                    if lx > W - pad_r - 80:
                        lx = dot_x - 12
                        anchor = "rm"
                    else:
                        anchor = "lm"
                    draw.text((lx, ly), txt, fill=DOT, font=font_small, anchor=anchor)
                    if after_comp is not None:
                        ay = y_flow(float(after_comp))
                        draw.ellipse([(dot_x - 4, ay - 4), (dot_x + 4, ay + 4)], fill=AFTER_COL)
                        draw.text((lx, ly + 14), f"after 2014 {after_comp:.1f}", fill=AFTER_COL, font=font_tiny, anchor=anchor)
            except Exception as e:
                _LOGGER.debug("dot draw fail %s", e)
        else:
            # hint when AT not yet available
            draw.text((W // 2, H // 2), "waiting for AT 2048 ...", fill=TEXT, font=font_small, anchor="mm")

        # footer hint
        draw.text((pad_l, pad_t - 12), "Slope 0.2 floor .. 1.5 radiators  *  Offset fine-tune  *  Live AT 2048", fill=TEXT, font=font_tiny, anchor="lm")

        # also indicate enable state
        try:
            en = coord.data.get(1236, {}).get("raw") if coord and getattr(coord, "data", None) else None
            if en == 0:
                draw.text((W // 2, H - 8), "H36=0 fixed mode (curve disabled) - image shows curve preview", fill=(251, 191, 36), font=font_tiny, anchor="mb")
        except:
            pass

        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        self._image_bytes = buf.getvalue()
        self._image_last_updated = datetime.now(timezone.utc)


async def async_setup_entry(hass, entry, async_add_entities):
    coord = hass.data.get("foxair", {}).get(entry.entry_id)
    if not coord:
        return
    ent = FoxAirHeatingCurveImage(coord, entry.entry_id)
    async_add_entities([ent])
