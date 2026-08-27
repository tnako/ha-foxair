"""HTTP views for v0.3.3 — SVG curve + iframe panel (no Lovelace edits)."""
from homeassistant.components.http import HomeAssistantView
from aiohttp import web
import math

class FoxAirCurveSvgView(HomeAssistantView):
    url = "/api/foxair/heating_curve.svg"
    name = "api:foxair:heating_curve_svg"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        # find coordinator (first entry)
        coord = None
        for data in hass.data.get("foxair", {}).values():
            coord = data
            break
        at = 0
        slope = 0.6
        offset = 0
        r10, r11 = 20, 60
        r31, r34 = 60, 35
        at_live = None
        target_live = None
        after_comp = None
        fixed = None
        if coord and getattr(coord, "data", None):
            try:
                from .heating_curve import curve_target_for_at
                rec_at = coord.data.get(2048)
                if rec_at: at_live = rec_at.get("value")
                rec_slope = coord.data.get(1234)
                if rec_slope: slope = rec_slope.get("value", 0.6)
                rec_off = coord.data.get(1235)
                if rec_off: offset = rec_off.get("value", 0)
                # slope may be 0..100 raw if not scaled correctly, normalize
                if slope and slope > 5:
                    slope = slope/10
                r10 = coord.data.get(1164, {}).get("value", 20) if coord.data.get(1164) else 20
                r11 = coord.data.get(1165, {}).get("value", 60) if coord.data.get(1165) else 60
                r31 = coord.data.get(1169, {}).get("value", 60) if coord.data.get(1169) else 60
                r34 = coord.data.get(1172, {}).get("value", 35) if coord.data.get(1172) else 35
                # current computed target
                if at_live is not None:
                    target_live = curve_target_for_at(coord, at_live)
                rec_ac = coord.data.get(2014)
                if rec_ac: after_comp = rec_ac.get("value")
                rec_f = coord.data.get(1158)
                if rec_f: fixed = rec_f.get("value")
            except:
                pass
        # SVG 800x400, AT -20..20 => x 60..760, flow 10..70 => y 340..40
        W, H = 800, 400
        pad_l, pad_r, pad_t, pad_b = 60, 20, 30, 40
        plot_w = W - pad_l - pad_r
        plot_h = H - pad_t - pad_b
        def x_at(atv): return pad_l + (atv + 20) / 40 * plot_w
        def y_flow(f): return pad_t + (70 - f) / 60 * plot_h

        # build curve polyline -20..20 step 1
        pts = []
        for at_step in range(-20, 21):
            from .heating_curve import calc_curve_target, clamp
            raw = calc_curve_target(at_step, slope, offset)
            # clamp same as helper
            clamped = max(r10, min(r11, raw))
            # also envelope? keep simple
            pts.append((x_at(at_step), y_flow(clamped)))
        poly = " ".join(f"{x:.1f},{y:.1f}" for x,y in pts)

        # fixed line
        fixed_y = y_flow(fixed) if fixed is not None else y_flow(35)
        # current dot
        dot_x = x_at(at_live) if at_live is not None else None
        dot_y = y_flow(target_live) if target_live is not None and dot_x else None
        after_y = y_flow(after_comp) if after_comp is not None and dot_x is not None else None

        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<rect width="100%" height="100%" fill="#0f172a"/>
<text x="{W/2}" y="20" text-anchor="middle" fill="#e2e8f0" font-family="sans-serif" font-size="16">FoxAir Heating Curve  AT vs Flow  (slope {slope:.2f}  offset {offset:.1f}°C)</text>
<!-- grid -->
<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{H-pad_b}" stroke="#334155"/>
<line x1="{pad_l}" y1="{H-pad_b}" x2="{W-pad_r}" y2="{H-pad_b}" stroke="#334155"/>
'''
        for at_g in [-20,-10,0,10,20]:
            x = x_at(at_g)
            svg += f'<line x1="{x}" y1="{pad_t}" x2="{x}" y2="{H-pad_b}" stroke="#1e293b"/><text x="{x}" y="{H-pad_b+15}" text-anchor="middle" fill="#94a3b8" font-size="11">{at_g}°C</text>'
        for f in [20,30,40,50,60]:
            y = y_flow(f)
            svg += f'<line x1="{pad_l}" y1="{y}" x2="{W-pad_r}" y2="{y}" stroke="#1e293b"/><text x="{pad_l-8}" y="{y+4}" text-anchor="end" fill="#94a3b8" font-size="11">{f}°C</text>'
        # bands
        svg += f'<rect x="{pad_l}" y="{y_flow(r11)}" width="{plot_w}" height="{y_flow(r10)-y_flow(r11)}" fill="#0ea5e9" opacity="0.06"/><text x="{W-pad_r}" y="{y_flow(r11)-6}" text-anchor="end" fill="#38bdf8" font-size="10">R10 {r10:.0f} — R11 {r11:.0f}</text>'
        svg += f'<polyline fill="none" stroke="#38bdf8" stroke-width="3" points="{poly}"/>'
        svg += f'<line x1="{pad_l}" y1="{fixed_y:.1f}" x2="{W-pad_r}" y2="{fixed_y:.1f}" stroke="#f59e0b" stroke-dasharray="6 4" opacity="0.9"/><text x="{W-pad_r}" y="{fixed_y-6:.0f}" text-anchor="end" fill="#fbbf24" font-size="11">Fixed R02 {fixed:.1f}°C</text>' if fixed is not None else ''
        if dot_x is not None and dot_y is not None:
            svg += f'<circle cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="7" fill="#22c55e" stroke="#fff" stroke-width="2"/><text x="{dot_x+10:.0f}" y="{dot_y-10:.0f}" fill="#22c55e" font-size="12">AT {at_live:.1f} → {target_live:.1f}°C</text>'
            if after_y is not None:
                svg += f'<circle cx="{dot_x:.1f}" cy="{after_y:.1f}" r="4" fill="#a78bfa" opacity="0.9"/><text x="{dot_x+10:.0f}" y="{after_y+14:.0f}" fill="#a78bfa" font-size="10">after comp 2014 {after_comp:.1f}</text>'
        # legend
        svg += f'<text x="{pad_l}" y="{pad_t-8}" fill="#94a3b8" font-size="10">Slope 0.2 shallow (floor) … 1.5 steep (radiators)  •  Offset ±10K fine-tune  •  Live AT 2048</text>'
        svg += '</svg>'
        return web.Response(body=svg.encode("utf-8"), content_type="image/svg+xml", headers={"Cache-Control":"no-cache, max-age=30"})

class FoxAirCurvePanelView(HomeAssistantView):
    url = "/api/foxair/heating-curve-panel"
    name = "api:foxair:heating_curve_panel"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        coord = None
        for d in hass.data.get("foxair", {}).values():
            coord = d
            break
        at = slope = offset = target = fixed = after = "—"
        if coord and getattr(coord, "data", None):
            try:
                from .heating_curve import curve_target_for_at
                at = coord.data.get(2048, {}).get("value", "—")
                slope = coord.data.get(1234, {}).get("value", "—")
                offset = coord.data.get(1235, {}).get("value", "—")
                at_v = at if isinstance(at,(int,float)) else None
                if at_v is not None:
                    target = curve_target_for_at(coord, at_v)
                    target = f"{target:.1f}" if target is not None else "—"
                fixed = coord.data.get(1158, {}).get("value", "—")
                if isinstance(fixed,(int,float)): fixed=f"{fixed:.1f}"
                after = coord.data.get(2014, {}).get("value", "—")
                if isinstance(after,(int,float)): after=f"{after:.1f}"
                if isinstance(at,(int,float)): at=f"{at:.1f}"
                if isinstance(slope,(int,float)): slope=f"{slope}"
                if isinstance(offset,(int,float)): offset=f"{offset}"
            except:
                pass
        html = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FoxAir Heating Curve</title>
<style>body{{margin:0;background:#020617;color:#e2e8f0;font-family:system-ui,sans-serif}} .wrap{{max-width:900px;margin:0 auto;padding:16px}} h1{{font-size:20px;margin:8px 0}} .card{{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:12px;margin:12px 0}} td{{padding:4px 10px}} .muted{{color:#94a3b8}} img{{width:100%;height:auto;border-radius:8px;background:#020617}}</style>
<div class="wrap">
<h1>FoxAir Heating Curve <span class="muted">— auto panel, no Lovelace edit</span></h1>
<div class="card"><img src="/api/foxair/heating_curve.svg?v={at}" alt="Heating curve"></div>
<div class="card"><table>
<tr><td>Ambient AT (2048 T04)</td><td><b>{at} °C</b></td></tr>
<tr><td>Slope (1234)</td><td><b>{slope}</b> — 0.2 floor, 1.5 radiator</td></tr>
<tr><td>Offset (1235)</td><td><b>{offset} °C</b> — parallel shift</td></tr>
<tr><td>Curve target (calc)</td><td><b>{target} °C</b></td></tr>
<tr><td>Fixed R02 (1158)</td><td><b>{fixed} °C</b> — used when H36=0</td></tr>
<tr><td>After comp 2014</td><td><b>{after} °C</b> — live validation</td></tr>
</table>
<p class="muted">Tune: if cold days too cold → increase slope. If always 1K off → shift offset. Panel refreshes every 30s. Entities: number.foxair_1234, number.foxair_1235, select.foxair_1236 (H36 enable), sensor.foxair_heating_curve_target.</p>
<p><a href="/api/foxair/heating_curve.svg" target="_blank" style="color:#38bdf8">Open SVG standalone</a></p>
</div>
</div>
"""
        return web.Response(body=html.encode("utf-8"), content_type="text/html")
