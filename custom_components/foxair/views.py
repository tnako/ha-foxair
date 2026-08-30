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
        hc_a = {}
        if coord and getattr(coord, "data", None):
            try:
                from .heating_curve import curve_target_for_at
                hc = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
                hc_a = hc.get("addr_single", {}) if isinstance(hc, dict) else {}
                st = coord.marker("setpoints") if hasattr(coord, "marker") else {}
                st_a = st.get("addr_single", {}) if isinstance(st, dict) else {}
                rec_at = coord.data.get(hc_a.get("at_sensor")) if hc_a.get("at_sensor") else None
                if rec_at: at_live = rec_at.get("value")
                rec_slope = coord.data.get(hc_a.get("slope")) if hc_a.get("slope") else None
                if rec_slope: slope = rec_slope.get("value", 0.6)
                rec_off = coord.data.get(hc_a.get("offset")) if hc_a.get("offset") else None
                if rec_off: offset = rec_off.get("value", 0)
                # slope may be 0..100 raw if not scaled correctly, normalize
                if slope and slope > 5:
                    slope = slope/10
                r10 = coord.data.get(hc_a.get("r10_min")) if hc_a.get("r10_min") else None
                r11 = coord.data.get(hc_a.get("r11_max")) if hc_a.get("r11_max") else None
                if r10: r10 = r10.get("value", 20)
                else: r10 = 20
                if r11: r11 = r11.get("value", 60)
                else: r11 = 60
                r31 = coord.data.get(hc_a.get("r31_at_lo")) if hc_a.get("r31_at_lo") else None
                r34 = coord.data.get(hc_a.get("r34_at_hi")) if hc_a.get("r34_at_hi") else None
                if r31: r31 = r31.get("value", 60)
                else: r31 = 60
                if r34: r34 = r34.get("value", 35)
                else: r34 = 35
                # current computed target
                if at_live is not None:
                    target_live = curve_target_for_at(coord, at_live)
                live_target_addr = hc_a.get("live_target")
                rec_ac = coord.data.get(live_target_addr) if live_target_addr else None
                if rec_ac: after_comp = rec_ac.get("value")
                fixed_addr = st_a.get("heating_target")
                rec_f = coord.data.get(fixed_addr) if fixed_addr else None
                if rec_f: fixed = rec_f.get("value")
            except:
                pass
        # SVG 800x460: plot 800x400 (AT -20..20 => x 60..760, flow 10..70 => y 330..30) + 60px legend strip
        W, H = 800, 460
        pad_l, pad_r, pad_t, pad_b = 60, 20, 30, 30
        legend_h = 60
        plot_w = W - pad_l - pad_r
        plot_h = H - pad_t - pad_b - legend_h
        def x_at(atv): return pad_l + (atv + 20) / 40 * plot_w
        def y_flow(f): return pad_t + (70 - f) / 60 * plot_h

        # build curve polyline -20..20 step 1
        pts = []
        from .heating_curve import calc_curve_target
        slope_n = slope if slope is not None else 0.6
        if slope_n > 3.0:
            slope_n = slope_n / 10.0
        offset_n = offset if offset is not None else 0.0
        for at_step in range(-20, 21):
            raw = calc_curve_target(at_step, slope_n, offset_n, base=0.0)
            clamped = max(r10, min(r11, raw))
            pts.append((x_at(at_step), y_flow(clamped)))
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

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
<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{H-pad_b-legend_h}" stroke="#334155"/>
<line x1="{pad_l}" y1="{H-pad_b-legend_h}" x2="{W-pad_r}" y2="{H-pad_b-legend_h}" stroke="#334155"/>
'''
        for at_g in [-20,-10,0,10,20]:
            x = x_at(at_g)
            svg += f'<line x1="{x}" y1="{pad_t}" x2="{x}" y2="{H-pad_b-legend_h}" stroke="#1e293b"/><text x="{x}" y="{H-pad_b-legend_h+15}" text-anchor="middle" fill="#94a3b8" font-size="11">{at_g}°C</text>'
        for f in [20,30,40,50,60]:
            y = y_flow(f)
            svg += f'<line x1="{pad_l}" y1="{y}" x2="{W-pad_r}" y2="{y}" stroke="#1e293b"/><text x="{pad_l-8}" y="{y+4}" text-anchor="end" fill="#94a3b8" font-size="11">{f}°C</text>'
        # bands — label at band top inside plot, right-aligned to avoid curve overlap
        svg += f'<rect x="{pad_l}" y="{y_flow(r11)}" width="{plot_w}" height="{y_flow(r10)-y_flow(r11)}" fill="#0ea5e3" opacity="0.06"/><text x="{pad_l+8}" y="{y_flow(r10)+14}" fill="#38bdf8" font-size="10">R10 {r10:.0f} — R11 {r11:.0f}</text>'
        svg += f'<polyline fill="none" stroke="#38bdf8" stroke-width="3" points="{poly}"/>'
        svg += f'<line x1="{pad_l}" y1="{fixed_y:.1f}" x2="{W-pad_r}" y2="{fixed_y:.1f}" stroke="#f59e0b" stroke-dasharray="6 4" opacity="0.9"/><text x="{pad_l+8}" y="{fixed_y-6:.0f}" fill="#fbbf24" font-size="11">Fixed R02 {fixed:.1f}°C</text>' if fixed is not None else ''
        if dot_x is not None and dot_y is not None:
            svg += f'<circle cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="7" fill="#22c55e" stroke="#fff" stroke-width="2"/>'
            # AT label placed to the left, vertically centered beside the dot
            svg += f'<text x="{max(dot_x-52,pad_l+4):.0f}" y="{dot_y+4:.0f}" fill="#22c55e" font-size="11" text-anchor="end">AT {at_live:.1f}→{target_live:.1f}°C</text>'
            if after_y is not None:
                svg += f'<circle cx="{dot_x:.1f}" cy="{after_y:.1f}" r="4" fill="#a78bfa" opacity="0.9"/>'
                # after-comp label placed to the left of the dot, below
                svg += f'<text x="{max(dot_x-52,pad_l+4):.0f}" y="{after_y-6:.0f}" fill="#a78bfa" font-size="10" text-anchor="end">after {after_comp:.1f}</text>'
        # legend strip at bottom — no overlap with plot area
        legend_y = H - pad_b + 14
        svg += f'<rect x="{pad_l}" y="{H-pad_b-legend_h+4}" width="{plot_w}" height="{legend_h-12}" fill="#020617" stroke="#1e293b" rx="4"/>'
        svg += f'<text x="{pad_l+12}" y="{legend_y}" fill="#38bdf8" font-size="10">Curve target — live AT</text>'
        svg += f'<text x="{pad_l+120}" y="{legend_y}" fill="#fbbf24" font-size="10">Fixed R02 — H36=0</text>'
        svg += f'<text x="{pad_l+240}" y="{legend_y}" fill="#a78bfa" font-size="10">After compensation — live validation</text>'
        svg += f'<text x="{W-pad_r}" y="{legend_y}" text-anchor="end" fill="#94a3b8" font-size="10">Slope {slope:.2f} • Offset {offset:.1f}°C • R10 {r10:.0f}–R11 {r11:.0f}</text>'
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
                hc = coord.marker("heat_curve") if hasattr(coord, "marker") else {}
                hc_a = hc.get("addr_single", {}) if isinstance(hc, dict) else {}
                st = coord.marker("setpoints") if hasattr(coord, "marker") else {}
                st_a = st.get("addr_single", {}) if isinstance(st, dict) else {}
                at = coord.data.get(hc_a.get("at_sensor"), {}).get("value", "—") if hc_a.get("at_sensor") else "—"
                slope = coord.data.get(hc_a.get("slope"), {}).get("value", "—") if hc_a.get("slope") else "—"
                offset = coord.data.get(hc_a.get("offset"), {}).get("value", "—") if hc_a.get("offset") else "—"
                at_v = at if isinstance(at,(int,float)) else None
                if at_v is not None:
                    target = curve_target_for_at(coord, at_v)
                    target = f"{target:.1f}" if target is not None else "—"
                fixed = coord.data.get(st_a.get("heating_target"), {}).get("value", "—") if st_a.get("heating_target") else "—"
                if isinstance(fixed,(int,float)): fixed=f"{fixed:.1f}"
                after = coord.data.get(hc_a.get("live_target"), {}).get("value", "—") if hc_a.get("live_target") else "—"
                if isinstance(after,(int,float)): after=f"{after:.1f}"
                if isinstance(at,(int,float)): at=f"{at:.1f}"
                if isinstance(slope,(int,float)): slope=f"{slope}"
                if isinstance(offset,(int,float)): offset=f"{offset}"
            except:
                pass
        _at_lbl = hc_a.get("at_sensor", "—")
        _slope_lbl = hc_a.get("slope", "—")
        _offset_lbl = hc_a.get("offset", "—")
        _fixed_lbl = st_a.get("heating_target", "—")
        _after_lbl = hc_a.get("live_target", "—")
        _h36_lbl = hc_a.get("at_comp_en", "—")
        html = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FoxAir Heating Curve</title>
<style>body{{margin:0;background:#020617;color:#e2e8f0;font-family:system-ui,sans-serif}} .wrap{{max-width:900px;margin:0 auto;padding:16px}} h1{{font-size:20px;margin:8px 0}} .card{{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:12px;margin:12px 0}} td{{padding:4px 10px}} .muted{{color:#94a3b8}} img{{width:100%;height:auto;border-radius:8px;background:#020617}}</style>
<div class="wrap">
<h1>FoxAir Heating Curve <span class="muted">— auto panel, no Lovelace edit</span></h1>
<div class="card"><img src="/api/foxair/heating_curve.svg?v={at}" alt="Heating curve"></div>
<div class="card"><table>
<tr><td>Ambient AT ({_at_lbl})</td><td><b>{at} °C</b></td></tr>
<tr><td>Slope ({_slope_lbl})</td><td><b>{slope}</b> — 0.2 floor, 1.5 radiator</td></tr>
<tr><td>Offset ({_offset_lbl})</td><td><b>{offset} °C</b> — parallel shift</td></tr>
<tr><td>Curve target (calc)</td><td><b>{target} °C</b></td></tr>
<tr><td>Fixed R02 ({_fixed_lbl})</td><td><b>{fixed} °C</b> — used when H36=0</td></tr>
<tr><td>After comp ({_after_lbl})</td><td><b>{after} °C</b> — live validation</td></tr>
</table>
<p class="muted">Tune: if cold days too cold → increase slope. If always 1K off → shift offset. Panel refreshes every 30s. Entities: number.foxair_{_slope_lbl}, number.foxair_{_offset_lbl}, select.foxair_{_h36_lbl} (H36 enable), sensor.foxair_heating_curve_target.</p>
<p><a href="/api/foxair/heating_curve.svg" target="_blank" style="color:#38bdf8">Open SVG standalone</a></p>
</div>
</div>
"""
        return web.Response(body=html.encode("utf-8"), content_type="text/html")
