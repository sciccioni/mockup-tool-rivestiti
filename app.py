import streamlit as st
from PIL import Image, ImageDraw
import numpy as np
import zipfile, io, base64
from pathlib import Path

st.set_page_config(
    page_title="Mockup Compositor · PhotoSì",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
body, [data-testid="stAppViewContainer"], [data-testid="stMain"] { background:#0c0c0e !important; }
[data-testid="stSidebar"] { background:#141416 !important; min-width:280px; }
* { color:#e4e4ec; }
h1,h2,h3 { color:#e4e4ec !important; }
.stButton>button { border-radius:6px; font-weight:500; }
[data-testid="stFileUploader"] { background:#1e1e22; border-radius:8px; }
</style>
""", unsafe_allow_html=True)

FORMATS = ["Orizzontale", "Quadrato", "Verticali"]

for k, v in {
    "templates": {}, "default_coords": {}, "default_scale": {},
    "tpl_coords": {}, "tpl_scale": {}, "graphics": [], "step": 1,
    "calib_p1": None, "calib_key": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v
ss = st.session_state

# ── Helpers ────────────────────────────────────────────────────────────────
def flatten(img: Image.Image) -> Image.Image:
    """Flatten PNG transparency onto white"""
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        src = img.convert("RGBA") if img.mode == "P" else img
        bg.paste(src, mask=src.split()[-1])
        return bg
    return img.convert("RGB")

def get_coords(fmt, tpl_name):
    ov = ss.tpl_coords.get(fmt, {}).get(tpl_name)
    if ov: return ov, "custom"
    df = ss.default_coords.get(fmt)
    if df: return df, "default"
    return None, None

def get_scale(fmt, tpl_name):
    ov = ss.tpl_scale.get(fmt, {}).get(tpl_name)
    if ov is not None: return ov, "custom"
    return ss.default_scale.get(fmt, 90), "default"

def auto_detect(img: Image.Image):
    try:
        ow, oh = img.size
        S = 400
        arr = np.array(img.resize((S,S), Image.NEAREST).convert("RGB"), dtype=float)
        H, W = arr.shape[:2]
        corners = [arr[:8,:8], arr[:8,W-8:], arr[H-8:,:8], arr[H-8:,W-8:]]
        bg = np.mean([c.mean(axis=(0,1)) for c in corners], axis=0)
        mask = np.abs(arr-bg).sum(axis=2) > 18
        ys, xs = np.where(mask)
        if not len(xs): return None
        PAD = 4
        x1,x2 = max(0,int(xs.min())-PAD), min(W-1,int(xs.max())+PAD)
        y1,y2 = max(0,int(ys.min())-PAD), min(H-1,int(ys.max())+PAD)
        return {"x":int(x1*ow/S),"y":int(y1*oh/S),"width":int((x2-x1)*ow/S),"height":int((y2-y1)*oh/S)}
    except: return None

def draw_overlay(img: Image.Image, coords, scale_pct, p1=None) -> Image.Image:
    out = flatten(img)
    draw = ImageDraw.Draw(out, "RGBA")
    if coords:
        x,y,w,h = coords["x"],coords["y"],coords["width"],coords["height"]
        x,y = max(0,x), max(0,y)
        w,h = min(w, img.width-x), min(h, img.height-y)
        draw.rectangle([x,y,x+w,y+h], outline=(124,111,255,220), width=3)
        draw.rectangle([x,y,x+w,y+h], fill=(124,111,255,30))
        sc = max(0.1, min(1.0, scale_pct/100))
        gw,gh = int(w*sc),int(h*sc)
        gx,gy = x+(w-gw)//2, y+(h-gh)//2
        draw.rectangle([gx,gy,gx+gw,gy+gh], outline=(62,207,142,220), width=2)
        draw.rectangle([gx,gy,gx+gw,gy+gh], fill=(62,207,142,25))
    if p1:
        px,py = p1["x"],p1["y"]
        draw.ellipse([px-10,py-10,px+10,py+10], fill=(245,166,35,230), outline=(255,255,255,180), width=2)
    return out

def composite(graphic: Image.Image, template: Image.Image, coords: dict, scale_pct: int) -> Image.Image:
    x,y,w,h = coords["x"],coords["y"],coords["width"],coords["height"]
    sc = max(0.1, min(1.0, scale_pct/100))
    g = graphic.copy()
    g.thumbnail((int(w*sc), int(h*sc)), Image.LANCZOS)
    rw,rh = g.size
    result = flatten(template)
    ox,oy = x+(w-rw)//2, y+(h-rh)//2
    if g.mode=="RGBA": result.paste(g,(max(0,ox),max(0,oy)),g)
    else:
        mask = g.convert("L").point(lambda v: 255)
        result.paste(g,(max(0,ox),max(0,oy)),mask)
    return result

# ── Click canvas ───────────────────────────────────────────────────────────
def click_canvas(img: Image.Image, canvas_key: str, height_px=400):
    """Embed image in HTML canvas at fixed height. Returns clicked {x,y} in original px."""
    flat = flatten(img)
    orig_w, orig_h = flat.size

    # Resize to fixed display height
    disp_h = height_px
    disp_w = int(orig_w * disp_h / orig_h)

    resized = flat.resize((disp_w, disp_h), Image.LANCZOS)
    buf = io.BytesIO()
    resized.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()

    uid = canvas_key.replace("-","_").replace(" ","_")

    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  html,body {{ margin:0; padding:0; background:#1e1e22; overflow:hidden; }}
  canvas {{ display:block; cursor:crosshair; border-radius:6px; }}
  #info {{ font-size:13px; font-weight:700; color:#ffffff; font-family:monospace; padding:6px 10px; min-height:24px; background:#1e1e22; border:1px solid #7c6fff; border-radius:0 0 6px 6px; }}
</style>
</head>
<body>
<canvas id="cv_{uid}" width="{disp_w}" height="{disp_h}"></canvas>
<div id="info_{uid}">👆 clicca per definire il punto</div>
<script>
(function(){{
  const cv  = document.getElementById('cv_{uid}');
  const ctx = cv.getContext('2d');
  const info = document.getElementById('info_{uid}');
  const OW={orig_w}, OH={orig_h}, DW={disp_w}, DH={disp_h};

  const imgEl = new Image();
  imgEl.onload = () => ctx.drawImage(imgEl, 0, 0, DW, DH);
  imgEl.src = 'data:image/jpeg;base64,{b64}';

  cv.onmousemove = function(e) {{
    const r = cv.getBoundingClientRect();
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    const ox = Math.round(dx * OW / DW), oy = Math.round(dy * OH / DH);
    info.textContent = '📍 ' + ox + ' , ' + oy + ' px';
    ctx.drawImage(imgEl, 0, 0, DW, DH);
    ctx.strokeStyle = 'rgba(245,166,35,0.7)';
    ctx.lineWidth = 1; ctx.setLineDash([6,4]);
    ctx.beginPath(); ctx.moveTo(dx,0); ctx.lineTo(dx,DH); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0,dy); ctx.lineTo(DW,dy); ctx.stroke();
    ctx.setLineDash([]);
  }};

  cv.onmouseleave = function() {{
    ctx.drawImage(imgEl, 0, 0, DW, DH);
    info.textContent = '👆 clicca per definire il punto';
  }};

  cv.onclick = function(e) {{
    const r = cv.getBoundingClientRect();
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    const ox = Math.round(dx * OW / DW), oy = Math.round(dy * OH / DH);
    info.textContent = '✅ ' + ox + ' , ' + oy;
    ctx.drawImage(imgEl, 0, 0, DW, DH);
    ctx.fillStyle = 'rgba(245,166,35,0.9)';
    ctx.beginPath(); ctx.arc(dx, dy, 8, 0, Math.PI*2); ctx.fill();
    // send to parent
    const inputs = window.parent.document.querySelectorAll('input[type="text"]');
    for (const inp of inputs) {{
      if (inp.getAttribute('aria-label') === 'coord_{uid}') {{
        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
          .set.call(inp, ox+','+oy);
        inp.dispatchEvent(new Event('input',{{bubbles:true}}));
        break;
      }}
    }}
  }};
}})();
</script>
</body>
</html>"""

    iframe_h = disp_h + 30
    st.components.v1.html(html, height=iframe_h, scrolling=False)
    val = st.text_input("", key=f"coord_{uid}", label_visibility="collapsed",
                        placeholder="clicca sull'immagine…")
    if val and "," in val:
        try:
            cx,cy = val.split(",")
            result = {"x":int(cx),"y":int(cy)}
            st.markdown(f"<div style='background:#7c6fff;color:#fff;font-family:monospace;font-size:14px;font-weight:700;padding:8px 14px;border-radius:6px;display:inline-block'>📍 X: {result["x"]} px &nbsp;&nbsp; Y: {result["y"]} px</div>", unsafe_allow_html=True)
            return result
        except: pass
    return None

# ── SIDEBAR ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🖼️ Mockup Compositor")
    st.markdown("---")
    labels = ["📁 Template","🎯 Calibra","🎨 Grafiche","📦 Esporta"]
    for i,l in enumerate(labels,1):
        if ss.step==i: st.markdown(f"**→ {i}. {l}**")
        elif ss.step>i: st.markdown(f"<span style='color:#3ecf8e'>✓ {i}. {l}</span>", unsafe_allow_html=True)
        else: st.markdown(f"<span style='color:#50505f'>{i}. {l}</span>", unsafe_allow_html=True)
    st.markdown("---")
    if ss.templates: st.caption(f"Template: {sum(len(v) for v in ss.templates.values())}")
    if ss.default_coords: st.caption(f"Default: {', '.join(ss.default_coords.keys())}")
    if ss.graphics: st.caption(f"Grafiche: {len(ss.graphics)}")

# ══════════════════════════════════════════════════════════════════
# STEP 1: UPLOAD TEMPLATES
# ══════════════════════════════════════════════════════════════════
if ss.step == 1:
    st.markdown("## 📁 Step 1 — Carica i Template")
    for fmt, col in zip(FORMATS, st.columns(3)):
        with col:
            st.markdown(f"### {fmt}")
            files = st.file_uploader(f"Template {fmt}", type=["jpg","jpeg","png"],
                                     accept_multiple_files=True, key=f"up_{fmt}",
                                     label_visibility="collapsed")
            if files:
                ss.templates[fmt] = [{"name":Path(f.name).stem,"img":Image.open(f),"ext":Path(f.name).suffix.lower()} for f in files]
                st.success(f"✓ {len(files)}")
                tcols = st.columns(min(3,len(files)))
                for i,t in enumerate(ss.templates[fmt][:6]):
                    with tcols[i%3]: st.image(flatten(t["img"]), caption=t["name"][:14], width=80)
            elif fmt in ss.templates and ss.templates[fmt]:
                st.info(f"✓ {len(ss.templates[fmt])} caricati")
    st.markdown("---")
    if sum(len(v) for v in ss.templates.values()) > 0:
        if st.button("Avanti → Calibra 🎯", type="primary", use_container_width=True):
            ss.step=2; st.rerun()

# ══════════════════════════════════════════════════════════════════
# STEP 2: CALIBRATE
# ══════════════════════════════════════════════════════════════════
elif ss.step == 2:
    st.markdown("## 🎯 Step 2 — Calibra le Zone")
    fmt_list = [f for f in FORMATS if f in ss.templates]
    fmt_tabs = st.tabs(fmt_list)

    for tab, fmt in zip(fmt_tabs, fmt_list):
        with tab:
            tpls = ss.templates[fmt]
            def_coords = ss.default_coords.get(fmt)
            def_scale  = ss.default_scale.get(fmt, 90)

            st.markdown(f"#### Default per {fmt}")
            col_cfg, col_img = st.columns([1, 2])

            with col_cfg:
                new_scale = st.slider("Scala %", 10, 100, def_scale, key=f"dsc_{fmt}")
                ss.default_scale[fmt] = new_scale

                if st.button("🔍 Auto-detect", key=f"dad_{fmt}", use_container_width=True):
                    det = auto_detect(tpls[0]["img"])
                    if det:
                        ss.default_coords[fmt] = det
                        ss.calib_p1 = None
                        st.rerun()
                    else:
                        st.error("Non rilevato")

                with st.form(key=f"dform_{fmt}"):
                    dc = def_coords or {}
                    dx = st.number_input("X", value=dc.get("x",0), min_value=0, step=1)
                    dy = st.number_input("Y", value=dc.get("y",0), min_value=0, step=1)
                    dw = st.number_input("W", value=dc.get("width",800), min_value=1, step=1)
                    dh = st.number_input("H", value=dc.get("height",600), min_value=1, step=1)
                    if st.form_submit_button("💾 Salva default", use_container_width=True, type="primary"):
                        ss.default_coords[fmt] = {"x":dx,"y":dy,"width":dw,"height":dh}
                        ss.default_scale[fmt] = new_scale
                        ss.calib_p1 = None
                        st.rerun()

                if def_coords:
                    st.markdown(f"""
<div style='background:#1e1e22;border:1px solid #3ecf8e;border-radius:8px;padding:10px 14px;font-family:monospace;font-size:13px;line-height:2'>
  <span style='color:#3ecf8e;font-weight:700'>✅ Calibrato</span><br/>
  <span style='color:#a89eff'>X</span> <span style='color:#fff;font-weight:600'>{def_coords['x']}</span>
  &nbsp;&nbsp;
  <span style='color:#a89eff'>Y</span> <span style='color:#fff;font-weight:600'>{def_coords['y']}</span><br/>
  <span style='color:#a89eff'>W</span> <span style='color:#fff;font-weight:600'>{def_coords['width']}</span>
  &nbsp;&nbsp;
  <span style='color:#a89eff'>H</span> <span style='color:#fff;font-weight:600'>{def_coords['height']}</span><br/>
  <span style='color:#a89eff'>Scala</span> <span style='color:#f5a623;font-weight:600'>{new_scale}%</span>
</div>
""", unsafe_allow_html=True)

                # P1 status
                ck = f"def_{fmt}"
                if ss.calib_p1 and ss.calib_key == ck:
                    st.warning(f"P1: {ss.calib_p1['x']},{ss.calib_p1['y']}\n→ clicca in basso a destra")
                    if st.button("✕ Annulla", key=f"canc_{fmt}"):
                        ss.calib_p1=None; ss.calib_key=None; st.rerun()
                else:
                    st.info("👆 Clicca P1 (alto sx) poi P2 (basso dx) sull'immagine")

            with col_img:
                p1_show = ss.calib_p1 if ss.calib_key == f"def_{fmt}" else None
                overlay = draw_overlay(tpls[0]["img"], def_coords, new_scale, p1_show)
                click = click_canvas(overlay, f"def_{fmt}", height_px=380)
                if click:
                    ck = f"def_{fmt}"
                    if ss.calib_p1 is None or ss.calib_key != ck:
                        ss.calib_p1 = click; ss.calib_key = ck; st.rerun()
                    else:
                        p1 = ss.calib_p1
                        x=min(p1["x"],click["x"]); y=min(p1["y"],click["y"])
                        w=abs(click["x"]-p1["x"]); h=abs(click["y"]-p1["y"])
                        if w>10 and h>10:
                            ss.default_coords[fmt]={"x":x,"y":y,"width":w,"height":h}
                        ss.calib_p1=None; ss.calib_key=None; st.rerun()

            # Per-template overrides
            st.markdown("---")
            with st.expander(f"⚙️ Override per singolo template"):
                tpl_names = [t["name"] for t in tpls]
                sel_name = st.selectbox("Template", tpl_names, key=f"osel_{fmt}")
                sel_tpl  = next(t for t in tpls if t["name"]==sel_name)
                ov_coords, ov_src = get_coords(fmt, sel_name)
                ov_scale, _ = get_scale(fmt, sel_name)

                st.caption(f"Sorgente: {'🟢 custom' if ov_src=='custom' else '🔵 default formato'}")

                ocol1, ocol2 = st.columns([1,2])
                with ocol1:
                    nov_scale = st.slider("Scala %", 10, 100, ov_scale, key=f"ovsc_{fmt}_{sel_name}")
                    if st.button("🔍 Auto-detect", key=f"ovad_{fmt}_{sel_name}", use_container_width=True):
                        det = auto_detect(sel_tpl["img"])
                        if det:
                            if fmt not in ss.tpl_coords: ss.tpl_coords[fmt]={}
                            ss.tpl_coords[fmt][sel_name]=det
                            st.rerun()
                    with st.form(key=f"ovform_{fmt}_{sel_name}"):
                        oc = ov_coords or {}
                        ox2=st.number_input("X",value=oc.get("x",0),min_value=0,step=1)
                        oy2=st.number_input("Y",value=oc.get("y",0),min_value=0,step=1)
                        ow2=st.number_input("W",value=oc.get("width",800),min_value=1,step=1)
                        oh2=st.number_input("H",value=oc.get("height",600),min_value=1,step=1)
                        c1,c2=st.columns(2)
                        with c1:
                            if st.form_submit_button("💾 Salva", use_container_width=True, type="primary"):
                                if fmt not in ss.tpl_coords: ss.tpl_coords[fmt]={}
                                ss.tpl_coords[fmt][sel_name]={"x":ox2,"y":oy2,"width":ow2,"height":oh2}
                                if fmt not in ss.tpl_scale: ss.tpl_scale[fmt]={}
                                ss.tpl_scale[fmt][sel_name]=nov_scale
                                st.rerun()
                        with c2:
                            if st.form_submit_button("🗑️ Reset", use_container_width=True):
                                ss.tpl_coords.get(fmt,{}).pop(sel_name,None)
                                ss.tpl_scale.get(fmt,{}).pop(sel_name,None)
                                st.rerun()

                with ocol2:
                    ovck = f"ov_{fmt}_{sel_name}"
                    p1_ov = ss.calib_p1 if ss.calib_key==ovck else None
                    ov_overlay = draw_overlay(sel_tpl["img"], ov_coords, nov_scale, p1_ov)
                    click2 = click_canvas(ov_overlay, ovck, height_px=320)
                    if click2:
                        if ss.calib_p1 is None or ss.calib_key!=ovck:
                            ss.calib_p1=click2; ss.calib_key=ovck; st.rerun()
                        else:
                            p1=ss.calib_p1
                            x=min(p1["x"],click2["x"]); y=min(p1["y"],click2["y"])
                            w=abs(click2["x"]-p1["x"]); h=abs(click2["y"]-p1["y"])
                            if w>10 and h>10:
                                if fmt not in ss.tpl_coords: ss.tpl_coords[fmt]={}
                                ss.tpl_coords[fmt][sel_name]={"x":x,"y":y,"width":w,"height":h}
                                if fmt not in ss.tpl_scale: ss.tpl_scale[fmt]={}
                                ss.tpl_scale[fmt][sel_name]=nov_scale
                            ss.calib_p1=None; ss.calib_key=None; st.rerun()

    st.markdown("---")
    c1,c2=st.columns(2)
    with c1:
        if st.button("← Indietro", use_container_width=True): ss.step=1; st.rerun()
    with c2:
        if ss.default_coords or any(ss.tpl_coords.values()):
            if st.button("Avanti → Grafiche 🎨", type="primary", use_container_width=True): ss.step=3; st.rerun()
        else:
            st.button("Calibra almeno un formato", disabled=True, use_container_width=True)

# ══════════════════════════════════════════════════════════════════
# STEP 3: GRAPHICS
# ══════════════════════════════════════════════════════════════════
elif ss.step == 3:
    st.markdown("## 🎨 Step 3 — Carica le Grafiche")
    uploaded = st.file_uploader("Carica grafiche", type=["jpg","jpeg","png","webp"],
                                accept_multiple_files=True, label_visibility="collapsed")
    if uploaded:
        ss.graphics=[{"name":Path(f.name).stem,"img":Image.open(f),"ext":Path(f.name).suffix.lower()} for f in uploaded]
    elif ss.graphics:
        st.info(f"✓ {len(ss.graphics)} già caricate")
    if ss.graphics:
        gcols=st.columns(min(5,len(ss.graphics)))
        for i,g in enumerate(ss.graphics):
            with gcols[i%5]: st.image(flatten(g["img"]), caption=g["name"][:12], width=90)
        if ss.default_coords or ss.tpl_coords:
            st.markdown("---")
            st.markdown("**👁️ Quick Preview**")
            pc1,pc2,pc3=st.columns(3)
            with pc1: pg=st.selectbox("Grafica",[g["name"] for g in ss.graphics])
            with pc2:
                avail=[f for f in ss.templates if ss.default_coords.get(f) or ss.tpl_coords.get(f)]
                pf=st.selectbox("Formato",avail) if avail else None
            with pc3:
                pt=st.selectbox("Template",[t["name"] for t in ss.templates.get(pf,[])]) if pf else None
            if pf and pt and st.button("Genera preview"):
                go=next(g for g in ss.graphics if g["name"]==pg)
                to=next(t for t in ss.templates[pf] if t["name"]==pt)
                coords,_=get_coords(pf,pt); scale,_=get_scale(pf,pt)
                if coords:
                    st.image(composite(go["img"],to["img"],coords,scale), use_container_width=True)
    st.markdown("---")
    c1,c2=st.columns(2)
    with c1:
        if st.button("← Indietro", use_container_width=True): ss.step=2; st.rerun()
    with c2:
        if ss.graphics:
            if st.button("Avanti → Esporta 📦", type="primary", use_container_width=True): ss.step=4; st.rerun()

# ══════════════════════════════════════════════════════════════════
# STEP 4: EXPORT
# ══════════════════════════════════════════════════════════════════
elif ss.step == 4:
    st.markdown("## 📦 Step 4 — Esporta ZIP")
    all_jobs=[]
    for fmt,tpls in ss.templates.items():
        for tpl in tpls:
            coords,src=get_coords(fmt,tpl["name"])
            scale,_=get_scale(fmt,tpl["name"])
            all_jobs.append({"fmt":fmt,"tpl":tpl,"coords":coords,"scale":scale})
    valid=[j for j in all_jobs if j["coords"]]
    c1,c2,c3,c4=st.columns(4)
    c1.metric("🎨 Grafiche",len(ss.graphics))
    c2.metric("🖼️ Template validi",len(valid))
    c3.metric("❌ Senza coords",len(all_jobs)-len(valid))
    c4.metric("📁 Tot.",len(ss.graphics)*len(valid))
    st.markdown("---")
    gcols=st.columns(min(5,len(ss.graphics)))
    gsel={}
    for i,g in enumerate(ss.graphics):
        with gcols[i%5]:
            st.image(flatten(g["img"]),width=80)
            gsel[g["name"]]=st.checkbox(g["name"][:12],value=True,key=f"gs_{i}")
    sel_g=[g for g in ss.graphics if gsel.get(g["name"],True)]
    st.markdown("---")
    n=len(sel_g)*len(valid)
    if st.button(f"🚀 Genera {n} immagini → ZIP", type="primary", use_container_width=True, disabled=n==0):
        prog=st.progress(0,text="Avvio...")
        zip_buf=io.BytesIO(); done,errors=0,[]
        with zipfile.ZipFile(zip_buf,"w",zipfile.ZIP_DEFLATED) as zf:
            for g in sel_g:
                for job in valid:
                    prog.progress(done/n, text=f"⚙️ {g['name']} → {job['fmt']}/{job['tpl']['name']}")
                    try:
                        res=composite(g["img"],job["tpl"]["img"],job["coords"],job["scale"])
                        buf=io.BytesIO()
                        res.save(buf,format="PNG" if g["ext"]==".png" else "JPEG",quality=92)
                        zf.writestr(f"{g['name']}/{job['fmt']}/{job['tpl']['name']}{g['ext'] or '.jpg'}",buf.getvalue())
                    except Exception as e: errors.append(str(e))
                    done+=1
        prog.progress(1.0,text="✅ Completato!")
        if errors:
            with st.expander(f"⚠️ {len(errors)} errori"): [st.text(e) for e in errors]
        st.download_button(f"⬇️ Scarica ZIP — {done} immagini",zip_buf.getvalue(),
                          "mockup-export.zip","application/zip",use_container_width=True,type="primary")
    if st.button("← Indietro", use_container_width=True): ss.step=3; st.rerun()
