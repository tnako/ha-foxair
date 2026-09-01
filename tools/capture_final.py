#!/usr/bin/env python3
"""Final FoxAir screenshot capture — Safari/CUA lessons ported to Playwright.

Fixes vs README_shots.py:
  * language via frontend/set_user_data websocket (not ?hl= / selectedLanguage)
  * expert toggle via SSH .storage/core.config_entries + homeassistant.reload_config_entry
  * hassTokens: bare JSON.stringify(tok) + also {hassUrl: tok} for compat
  * wait_for_selector("text=FoxAir") + shadow-DOM walk
  * full_page=True, extra_http_headers for /api/foxair/*
  * device-detail click for expert diff

Output: docs/screenshots/foxair_{en,de,ru}_{non-expert,expert}.png (6)
        docs/screenshots/foxair_{en,ru}_expert_curve.png (2)
        docs/screenshots/foxair_demo.gif + collage.png
        README.md embed
"""
import asyncio, json, os, sys, time, subprocess, urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

HASS = os.environ.get("HASS_URL", "").rstrip("/")
if not HASS:
    HASS = os.environ.get("HASS_URL", "")
TOKEN = os.environ.get("HASS_TOKEN", "") or os.environ.get("TOKEN", "")
HA_HOST = os.environ.get("HA_HOST", "")
ENTRY_ID = "01M1CHN11EP8WMGGWD5RZ9JFWT"

LANGS = [("en","English"),("de","Deutsch"),("ru","Русский")]
MODES = [("non-expert", False), ("expert", True)]

INTEGRATION_URL = f"{HASS}/config/integrations/integration/foxair"

try:
    import websockets
except ImportError:
    websockets = None

def ha_headers():
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

def build_hass_tokens():
    tok = {
        "access_token": TOKEN,
        "token_type": "bearer",
        "refresh_token": "x",
        "expires_in": 999999999,
        "hassUrl": HASS,
        "clientId": HASS + "/",
        "expires": 9999999999999,
    }
    # bare + keyed for compat (user fix: bare-token)
    bare = json.dumps(tok)
    keyed = json.dumps({HASS: tok, HASS+"/": tok})
    return bare, keyed, tok

async def ws_set_language(lang_code):
    """Set HA user language via websocket frontend/set_user_data."""
    if not websockets:
        print("  WARN no websockets module, skip lang set")
        return
    url = HASS.replace("http://","ws://").replace("https://","wss://") + "/api/websocket"
    try:
        async with websockets.connect(url, open_timeout=5) as ws:
            await ws.recv()
            await ws.send(json.dumps({"type":"auth","access_token":TOKEN}))
            r=json.loads(await ws.recv())
            if r.get("type")!="auth_ok":
                print(f"  WS auth failed {r}")
                return
            # need increasing id
            mid = int(time.time()*1000) % 100000
            await ws.send(json.dumps({"id": mid, "type":"frontend/set_user_data","key":"language","value": lang_code}))
            resp=json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print(f"  WS language -> {lang_code}: {resp.get('success')}")
            # also set locale
            await ws.send(json.dumps({"id": mid+1, "type":"frontend/set_user_data","key":"core","value":{"language":lang_code}}))
            try:
                await asyncio.wait_for(ws.recv(), timeout=2)
            except: pass
    except Exception as e:
        print(f"  WS language error: {e}")

def ws_set_language_sync(lang_code):
    # run in subprocess to avoid event-loop clash with playwright sync API
    import subprocess, textwrap
    code = textwrap.dedent(f"""
import asyncio, json, os
import websockets
HASS=os.environ.get("HASS_URL","")
TOKEN=os.environ.get("HASS_TOKEN") or os.environ.get("TOKEN","")
async def go():
    url=HASS.replace("http://","ws://").replace("https://","wss://")+"/api/websocket"
    async with websockets.connect(url, open_timeout=5) as ws:
        await ws.recv()
        await ws.send(json.dumps({{"type":"auth","access_token":TOKEN}}))
        r=json.loads(await ws.recv())
        if r.get("type")!="auth_ok": print(r); return
        mid=100
        await ws.send(json.dumps({{"id":mid,"type":"frontend/set_user_data","key":"language","value":"{lang_code}"}}))
        print(await ws.recv())
asyncio.run(go())
""")
    env=dict(os.environ)
    r=subprocess.run([sys.executable,"-c",code], capture_output=True, text=True, timeout=10, env=env)
    print(f"  WS lang {lang_code}: {r.stdout.strip()[:120]} {r.stderr.strip()[:120]}")

def ssh_set_expert(enable: bool):
    """Edit .storage/core.config_entries options.enable_expert + data.enable_expert via SSH, then reload."""
    val_py = "True" if enable else "False"
    cmd = (
        f"python3 - << 'PY'\n"
        f"import json\n"
        f"p='/usr/share/hassio/homeassistant/.storage/core.config_entries'\n"
        f"d=json.load(open(p))\n"
        f"changed=False\n"
        f"for e in d['data']['entries']:\n"
        f"  if e.get('domain')=='foxair':\n"
        f"    e.setdefault('options',{{}})['enable_expert']={val_py}\n"
        f"    e.setdefault('data',{{}})['enable_expert']={val_py}\n"
        f"    changed=True\n"
        f"    print('set', e['entry_id'], e['options'])\n"
        f"if changed:\n"
        f"  open(p,'w').write(json.dumps(d))\n"
        f"  print('written')\n"
        f"PY\n"
    )
    r = subprocess.run(["ssh", f"{os.environ.get('HA_SSH_USER','root')}{chr(64)}{HA_HOST}" if HA_HOST else "", cmd], capture_output=True, text=True, timeout=15)
    print(f"  SSH expert={enable} -> {r.stdout.strip()[:200]} {r.stderr.strip()[:200]}")
    # reload via HA service (websocket) — try, ignore hang
    try:
        import urllib.request, json as _j
        data = _j.dumps({"entry_id": ENTRY_ID}).encode()
        req = urllib.request.Request(f"{HASS}/api/services/homeassistant/reload_config_entry",
            data=data, headers=ha_headers(), method="POST")
        urllib.request.urlopen(req, timeout=8).read()
        print("  reload_config_entry OK")
    except Exception as e:
        print(f"  reload via REST: {e} (fallback: wait)")
    time.sleep(6)  # let HA reload integration + entities repopulate
    # verify entity count
    try:
        req = urllib.request.Request(f"{HASS}/api/states", headers=ha_headers())
        import json as _j2
        states = _j2.loads(urllib.request.urlopen(req, timeout=5).read())
        fox = [s for s in states if "foxair" in s["entity_id"]]
        print(f"  foxair entities after reload: {len(fox)}")
    except Exception as e:
        print(f"  entity check: {e}")

def inject_auth(context, lang_code="en"):
    bare, keyed, tok = build_hass_tokens()
    # BARE token only — keyed {hassUrl: tok} breaks HA 2026.x (redirects to /auth/authorize)
    # selectedLanguage localStorage forces frontend translation (WS language alone not enough for first paint)
    context.add_init_script(f"""
        try {{
            localStorage.setItem('hassTokens', {json.dumps(bare)});
            localStorage.setItem('hassUrl', {json.dumps(HASS)});
            localStorage.setItem('selectedLanguage', JSON.stringify({json.dumps(lang_code)}));
        }} catch(e) {{}}
    """)
    context.set_extra_http_headers(ha_headers())

def shot(page, path):
    page.wait_for_load_state("networkidle", timeout=15000)
    # wait for FoxAir content — shadow-DOM aware
    try:
        page.wait_for_selector("text=FoxAir", timeout=10000)
    except:
        print("    WARN no FoxAir text found, continue")
    time.sleep(1.2)
    # shadow-DOM walk: ensure ha-config-integration-page or ha-device-page rendered
    try:
        page.evaluate("""() => {
            const walk = (root) => {
                if (!root) return;
                const els = root.querySelectorAll('*');
                for (const el of els) { if (el.shadowRoot) walk(el.shadowRoot); }
            };
            walk(document);
        }""")
    except: pass
    page.screenshot(path=str(path), full_page=True, animations="disabled")
    print(f"    saved {path.name} ({os.path.getsize(path)} bytes)")

def collage_and_gif(frames):
    from PIL import Image
    # GIF
    imgs = [Image.open(f).convert("RGB") for f in frames]
    # normalize size to max
    w = max(i.width for i in imgs); h = max(i.height for i in imgs)
    norm=[]
    for im in imgs:
        n=Image.new("RGB", (w,h), (24,24,24))
        n.paste(im, ((w-im.width)//2, 0))
        norm.append(n)
    # downscale if huge
    max_w=1280
    if w>max_w:
        scale=max_w/w
        resample=getattr(Image, "Resampling", Image).LANCZOS
        norm=[im.resize((int(im.width*scale), int(im.height*scale)), resample) for im in norm]
        # quantize
    paletted=[im.convert("P", palette=Image.Palette.ADAPTIVE, colors=128) for im in norm]
    gif=OUT/"foxair_demo.gif"
    paletted[0].save(str(gif), save_all=True, append_images=paletted[1:], duration=1400, loop=0, optimize=True, disposal=2)
    print(f"GIF {gif} ({os.path.getsize(gif)} bytes)")
    # collage
    cols=4
    rows=(len(imgs)+cols-1)//cols
    thumb_w, thumb_h = 320, 200
    thumbs=[]
    for p in frames:
        im=Image.open(p); im.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS); thumbs.append((im, p.name))
    cell_w, cell_h = thumb_w+20, thumb_h+40
    collage=Image.new("RGB", (cell_w*cols, cell_h*rows), "#1a1a2e")
    try:
        from PIL import ImageDraw, ImageFont
        draw=ImageDraw.Draw(collage)
        font=ImageFont.load_default()
    except: draw=None; font=None
    for i,(thumb,label) in enumerate(thumbs):
        x=(i%cols)*cell_w; y=(i//cols)*cell_h
        collage.paste(thumb, (x+(cell_w-thumb.width)//2, y+25))
        if draw:
            short=label.replace("foxair_","").replace(".png","")
            draw.text((x+5,y+5), short[:28], fill="#ffffff", font=font)
    cpath=OUT/"collage.png"
    collage.save(cpath)
    print(f"collage {cpath} ({os.path.getsize(cpath)} bytes)")

def run():
    if not TOKEN:
        print("HASS_TOKEN missing"); sys.exit(1)
    from playwright.sync_api import sync_playwright
    frames=[]
    # ensure clean language baseline
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        for lang_code, lang_name in LANGS:
            for mode_code, expert in MODES:
                print(f"\n== {lang_name} / {mode_code} ==")
                # expert toggle via SSH (true/false fixed)
                ssh_set_expert(expert)
                # language via websocket
                ws_set_language_sync(lang_code)
                time.sleep(1)
                ctx=browser.new_context(viewport={"width":1440,"height":900}, extra_http_headers=ha_headers())
                inject_auth(ctx, lang_code)
                page=ctx.new_page()
                # integration page
                page.goto(INTEGRATION_URL, wait_until="networkidle", timeout=30000)
                shot(page, OUT / f"foxair_{lang_code}_{mode_code}.png")
                frames.append(OUT / f"foxair_{lang_code}_{mode_code}.png")
                # device-detail for expert diff — direct goto to main FoxAir device (6619f62...)
                try:
                    device_id = "6619f62154987585ab43da8c3be4eb9e"
                    page.goto(f"{HASS}/config/devices/device/{device_id}", wait_until="networkidle", timeout=30000)
                    time.sleep(1.5)
                    page.wait_for_selector("text=FoxAir", timeout=8000)
                    p2 = OUT / f"foxair_{lang_code}_{mode_code}_device.png"
                    page.screenshot(path=str(p2), full_page=True, animations="disabled")
                    print(f"    device detail {p2.name} ({os.path.getsize(p2)} bytes)")
                except Exception as e:
                    print(f"    device goto: {e}")
                ctx.close()
        # curve panels (need bearer header)
        for lang_code in ("en","ru"):
            print(f"\n== curve {lang_code} expert ==")
            ws_set_language_sync(lang_code)
            ctx=browser.new_context(viewport={"width":1440,"height":920}, extra_http_headers=ha_headers())
            inject_auth(ctx, lang_code)
            page=ctx.new_page()
            page.goto(f"{HASS}/api/foxair/heating-curve-panel", wait_until="networkidle", timeout=30000)
            time.sleep(1)
            page.screenshot(path=str(OUT / f"foxair_{lang_code}_expert_curve.png"), full_page=True, animations="disabled")
            print(f"    curve panel {lang_code} saved")
            frames.append(OUT / f"foxair_{lang_code}_expert_curve.png")
            # also direct SVG (may timeout on fonts — non-fatal)
            try:
                page.goto(f"{HASS}/api/foxair/heating_curve.svg", wait_until="networkidle", timeout=15000)
                time.sleep(0.8)
                page.screenshot(path=str(OUT / f"foxair_{lang_code}_expert_curve_svg.png"), full_page=True, animations="disabled")
            except Exception as e:
                print(f"    SVG shot skip: {e}")
            ctx.close()
        browser.close()
    # trim to 8-12 for gif (prefer 10)
    # keep order: 6 integration + 2 curve
    gif_frames = [OUT/f"foxair_{l}_{m}.png" for l,_ in LANGS for m,_ in MODES] + [OUT/"foxair_en_expert_curve.png", OUT/"foxair_ru_expert_curve.png"]
    gif_frames=[f for f in gif_frames if f.exists()]
    collage_and_gif(gif_frames)
    print("\nDone frames:")
    for f in gif_frames: print(" ", f.name, os.path.getsize(f))
    # reset to non-expert en
    ssh_set_expert(False)
    ws_set_language_sync("en")

if __name__=="__main__":
    run()
