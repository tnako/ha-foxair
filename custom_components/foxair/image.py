"""Image platform — heating curve on device page without YAML.

Renders image.foxair_heating_curve on the FoxAir Heat Pump device.
Light theme  — white BG, grey grid, blue
curve with light fill, red live dot. 1200x720 for crisp device thumbnail
(expands on tap). Same math as views.py/svg but as PNG via PIL.

AT is 2048 (T04), slope 1234 DIGI5/10, offset 1235 TEMP1/10, enable 1236,
clamp R10 1164 / R11 1165, fixed R02 1158, after-comp 2014.
"""
from __future__ import annotations
import io
import logging
import pathlib
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

def _load_font(size: int):
    # try DejaVuSans available in ha docker and on macOS
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in candidates:
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except:
        return None

class FoxAirHeatingCurveImage(CoordinatorEntity, ImageEntity):
    _attr_has_entity_name = False
    _attr_name = "Heating Curve"
    _attr_icon = "mdi:chart-bell-curve"
    _attr_content_type = "image/png"

    def __init__(self, coordinator, entry_id: str):
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_heating_curve_image"
        self._attr_device_info = main_device(entry_id)
        self.entity_id = "image.foxair_heating_curve"
        self._image_bytes: bytes | None = None
        self._image_last_updated: datetime | None = None
        self._render()

    @property
    def image_last_updated(self):
        return self._image_last_updated

    async def async_image(self) -> bytes | None:
        if self._image_bytes is None:
            self._render()
        return self._image_bytes

    def _handle_coordinator_update(self) -> None:
        self._render()
        super()._handle_coordinator_update()

    def _render(self):
        if not HAS_PIL:
            self._image_bytes = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n"
                b"-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            self._image_last_updated = datetime.now(timezone.utc)
            return
        coord = self.coordinator
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
                    try: at_live = float(rec_at.get("value"))
                    except: at_live = None
                if at_live is not None:
                    try: target_live = curve_target_for_at(coord, at_live)
                    except: target_live = None
                rec_ac = coord.data.get(2014)
                if rec_ac:
                    try: after_comp = float(rec_ac.get("value"))
                    except: after_comp = None
                rec_f = coord.data.get(1158)
                if rec_f:
                    try: fixed = float(rec_f.get("value"))
                    except: fixed = None
            except Exception as e:
                _LOGGER.debug("image render coord read fail %s", e)

        W, H = 1200, 720
        pad_l, pad_r, pad_t, pad_b = 90, 40, 70, 80
        plot_w = W - pad_l - pad_r
        plot_h = H - pad_t - pad_b

        def x_at(v: float) -> float:
            return pad_l + (v + 30) / 50 * plot_w
        def y_flow(v: float) -> float:
            return pad_t + (65 - v) / 50 * plot_h
        def clamp(v, lo, hi):
            return max(lo, min(hi, v))

        # dark theme — matches  if dark display, larger 1200x720 not icon
        BG = (15, 23, 42)        # #0f172a
        GRID = (30, 41, 59)      # #1e293b
        GRID_MINOR = (23, 33, 54)
        AXIS = (51, 65, 85)      # #334155
        TEXT = (148, 163, 184)   # #94a3b8
        TEXT_DARK = (226, 232, 240)
        TITLE_CLR = (226, 232, 240)
        CURVE = (96, 165, 250)   # muted blue -> #60a5fa
        CURVE_FILL = (30, 58, 95)
        FIXED_COL = (251, 146, 60)   # orange
        DOT = (248, 113, 113)    # red-400 live
        AFTER_COL = (167, 139, 250)

        im = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(im)
        f_title = _load_font(28)
        f_axis = _load_font(18)
        f_small = _load_font(16)
        f_tiny = _load_font(13)
        f_big = _load_font(22)

        # title
        title = f"Heating Curve  —  slope {slope:.2f}  ·  offset {offset:.1f}°C  ·  AT → Flow"
        try:
            draw.text((W//2, 18), title, fill=TITLE_CLR, font=f_title, anchor="mt")
        except: draw.text((W//2, 18), title, fill=TITLE_CLR, anchor="mt")
        subtitle = f"Flow = 35 + offset + slope × (20 − AT)   clamped R10 {r10:.0f}°C … R11 {r11:.0f}°C"
        try: draw.text((W//2, 52), subtitle, fill=TEXT, font=f_tiny, anchor="mt")
        except: pass

        # axes
        draw.line([(pad_l, pad_t), (pad_l, H - pad_b)], fill=AXIS, width=2)
        draw.line([(pad_l, H - pad_b), (W - pad_r, H - pad_b)], fill=AXIS, width=2)

        # minor grid every 5C AT / 5C flow — faint
        for at_g in range(-30, 21, 5):
            if at_g % 10 == 0: continue
            x = x_at(at_g)
            draw.line([(x, pad_t), (x, H - pad_b)], fill=GRID_MINOR, width=1)
        for f in range(20, 66, 5):
            if f % 10 == 0: continue
            y = y_flow(f)
            draw.line([(pad_l, y), (W - pad_r, y)], fill=GRID_MINOR, width=1)
        # major grid
        for at_g in [-30, -20, -10, 0, 10, 20]:
            x = x_at(at_g)
            draw.line([(x, pad_t), (x, H - pad_b)], fill=GRID, width=1)
            lab = f"{at_g}°"
            try: draw.text((x, H - pad_b + 10), lab, fill=TEXT, font=f_axis, anchor="mt")
            except: draw.text((x, H - pad_b + 10), lab, fill=TEXT, anchor="mt")
        for f in [20, 30, 40, 50, 60]:
            y = y_flow(f)
            draw.line([(pad_l, y), (W - pad_r, y)], fill=GRID, width=1)
            try: draw.text((pad_l - 12, y), f"{f}°", fill=TEXT, font=f_axis, anchor="rm")
            except: draw.text((pad_l - 12, y), f"{f}°", fill=TEXT, anchor="rm")
        # axis titles
        try:
            draw.text((pad_l + plot_w//2, H - 14), "Outdoor temperature AT  [°C]", fill=TEXT_DARK, font=f_small, anchor="mb")
        except: pass
        # vertical axis title rotated — draw via text then rotate would need extra; keep as side label
        # R10/R11 band as light fill
        y_r11 = y_flow(r11)
        y_r10 = y_flow(r10)
        overlay = Image.new("RGBA", (W, H), (0,0,0,0))
        od = ImageDraw.Draw(overlay)
        od.rectangle([(pad_l, y_r11), (W - pad_r, y_r10)], fill=CURVE_FILL + (70,))
        # subtle border of band
        od.line([(pad_l, y_r11), (W - pad_r, y_r11)], fill=CURVE + (90,), width=1)
        od.line([(pad_l, y_r10), (W - pad_r, y_r10)], fill=CURVE + (90,), width=1)
        im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(im)
        try: draw.text((W - pad_r - 6, y_r11 + 6), f"R10 {r10:.0f}° — R11 {r11:.0f}°", fill=CURVE, font=f_tiny, anchor="rt")
        except: pass

        # fill under curve (clamped) — range -30..+20 per user, step 10 labels but 0.5 for smoothness
        pts = []
        for i in range(-30*2, 20*2+1):
            at_step = i/2.0
            raw = calc_curve_target(at_step, slope, offset)
            clamped = clamp(raw, r10, r11)
            pts.append((x_at(at_step), y_flow(clamped)))
        # polygon for fill: curve + bottom edge
        if len(pts) >= 2:
            poly = pts + [(pts[-1][0], H - pad_b), (pts[0][0], H - pad_b)]
            overlay2 = Image.new("RGBA", (W, H), (0,0,0,0))
            od2 = ImageDraw.Draw(overlay2)
            od2.polygon(poly, fill=CURVE_FILL + (55,))
            im = Image.alpha_composite(im.convert("RGBA"), overlay2).convert("RGB")
            draw = ImageDraw.Draw(im)
        # curve line — always drawn, but prominent only in curve mode
        # detect mode: H36 1236 raw 0=fixed, 1=curve
        try:
            h36_raw = coord.data.get(1236, {}).get("raw") if coord and getattr(coord, "data", None) else None
            is_curve_mode = (h36_raw != 0)  # None defaults to curve (show curve)
        except:
            is_curve_mode = True
        for a,b in zip(pts, pts[1:]):
            draw.line([a,b], fill=CURVE, width=4)
        # fixed line dashed — only when NOT in curve mode
        if fixed is not None and not is_curve_mode:
            fy = y_flow(clamp(fixed, 15, 65))
            dash, gap = 14, 10
            x = pad_l
            while x < W - pad_r:
                x2 = min(x+dash, W-pad_r)
                draw.line([(x, fy), (x2, fy)], fill=FIXED_COL, width=3)
                x += dash+gap
            try: draw.text((W - pad_r - 6, fy - 10), f"Fixed R02 {fixed:.1f}°C", fill=FIXED_COL, font=f_small, anchor="rb")
            except: pass

        # live dot — big red as in photo
        if at_live is not None and target_live is not None:
            try:
                dot_x = x_at(float(at_live))
                dot_y = y_flow(float(target_live))
                if pad_l-10 <= dot_x <= W-pad_r+10 and pad_t-10 <= dot_y <= H-pad_b+10:
                    r = 10
                    # shadow
                    draw.ellipse([(dot_x-r-3, dot_y-r-3), (dot_x+r+3, dot_y+r+3)], fill=(0,0,0,30) if False else (255,255,255))
                    # white halo
                    draw.ellipse([(dot_x-r-3, dot_y-r-3), (dot_x+r+3, dot_y+r+3)], fill=(255,255,255), outline=(200,200,200))
                    draw.ellipse([(dot_x-r, dot_y-r), (dot_x+r, dot_y+r)], fill=DOT, outline=(255,255,255))
                    # label box
                    txt = f"AT {at_live:.1f}° → {target_live:.1f}°C"
                    lx = dot_x + 18
                    ly = dot_y - 18
                    anchor = "lm"
                    if lx > W - pad_r - 160:
                        lx = dot_x - 18
                        anchor = "rm"
                    # label bg
                    bbox = draw.textbbox((lx, ly), txt, font=f_small, anchor=anchor) if f_small else (lx-50, ly-10, lx+50, ly+10)
                    pad = 6
                    draw.rounded_rectangle([(bbox[0]-pad, bbox[1]-pad), (bbox[2]+pad, bbox[3]+pad)], radius=6, fill=(30,41,59), outline=(51,65,85))
                    try: draw.text((lx, ly), txt, fill=DOT, font=f_small, anchor=anchor)
                    except: draw.text((lx, ly), txt, fill=DOT, anchor=anchor)
                    if after_comp is not None:
                        ay = y_flow(float(after_comp))
                        draw.ellipse([(dot_x-5, ay-5), (dot_x+5, ay+5)], fill=AFTER_COL, outline=(255,255,255))
                        try: draw.text((lx, ly+20), f"after 2014 {after_comp:.1f}°", fill=AFTER_COL, font=f_tiny, anchor=anchor)
                        except: pass
            except Exception as e:
                _LOGGER.debug("dot draw fail %s", e)
        else:
            try: draw.text((W//2, H//2), "waiting for AT 2048 …", fill=TEXT, font=f_small, anchor="mm")
            except: pass

        # footer — flow label on left edge
        try:
            # draw vertical Flow label via text at left margin
            draw.text((18, pad_t + plot_h//2), "Flow", fill=TEXT_DARK, font=f_small, anchor="mm")
            draw.text((18, pad_t + plot_h//2 + 18), "°C", fill=TEXT, font=f_tiny, anchor="mm")
        except: pass

        # mode hint
        try:
            en = coord.data.get(1236, {}).get("raw") if coord and getattr(coord, "data", None) else None
            if en == 0:
                draw.rounded_rectangle([(W//2-220, H-38), (W//2+220, H-14)], radius=8, fill=(254,243,199), outline=(251,191,36))
                draw.text((W//2, H-26), "H36=0 fixed mode — preview of curve", fill=(146,64,14), font=f_tiny, anchor="mm")
        except: pass

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
