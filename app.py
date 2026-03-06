import streamlit as st
from PIL import Image, ImageDraw
import numpy as np
import json, zipfile, io, base64
from pathlib import Path

st.set_page_config(
    page_title="Mockup Compositor · PhotoSì",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
[data-testid="stSidebar"] { min-width: 300px; }
.tpl-row { display:flex; align-items:center; gap:8px; padding:6px 8px; border-radius:6px; margin-bottom:4px; background:#1e1e22; border:1px solid #2e2e36; }
.badge-ok  { background:rgba(62,207,142,.15); color:#3ecf8e; border-radius:4px; padding:1px 6px; font-size:10px; font-weight:600; }
.badge-def { background:rgba(124,111,255,.15); color:#a89eff; border-radius:4px; padding:1px 6px; font-size:10px; font-weight:600; }
.badge-no  { background:rgba(255,96,89,.1); color:#ff6059; border-radius:4px; padding:1px 6px; font-size:10px; font-weight:600; }
</style>
""", unsafe_allow_html=True)

FORMATS = ["Orizzontale", "Quadrato", "Verticali"]

for k, v in {
    "templates": {},
    "default_coords": {},   # {fmt: {x,y,width,height}}
    "default_scale": {},    # {fmt: int}
    "tpl_coords": {},       # {fmt: {tpl_name: {x,y,width,height}}}  overrides per template
    "tpl_scale": {},        # {fmt: {tpl_name: int}}
    "graphics": [],
    "step": 1,
    "calib_p1": None,
    "calib_fmt": None,
    "calib_tpl": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v
ss = st.session_state

# ── Helpers ────────────────────────────────────────────────────────────────
def get_coords(fmt, tpl_name):
    """Get coords for a template: per-template override or format default"""
    override = ss.tpl_coords.get(fmt, {}).get(tpl_name)
    if override:
        return override, "custom"
    default = ss.default_coords.get(fmt)
    if default:
        return default, "default"
    return None, None

def get_scale(fmt, tpl_name):
    override = ss.tpl_scale.get(fmt, {}).get(tpl_name)
    if override is not None:
        return override, "custom"
    return ss.default_scale.get(fmt, 90), "default"

def set_coords(fmt, tpl_name, coords, as_default=False):
    if as_default:
        ss.default_coords[fmt] = coords
        # Remove per-template overrides for this format if user wants to reset
    else:
        if fmt not in ss.tpl_coords:
            ss.tpl_coords[fmt] = {}
        ss.tpl_coords[fmt][tpl_name] = coords

def set_scale(fmt, tpl_name, scale, as_default=False):
    if as_default:
        ss.default_scale[fmt] = scale
    else:
        if fmt not in ss.tpl_scale:
            ss.tpl_scale[fmt] = {}
        ss.tpl_scale[fmt][tpl_name] = scale

def img_to_b64(img: Image.Image, max_w=1200) -> tuple:
    """Returns (b64_str, display_w, display_h, orig_w, orig_h)"""
    orig_w, orig_h = img.size
    disp_w = min(orig_w, max_w)
    ratio = disp_w / orig_w
    disp_h = int(orig_h * ratio)
    # Flatten transparency onto white background before JPEG encoding
    resized = img.resize((disp_w, disp_h), Image.LANCZOS)
    if resized.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", resized.size, (255, 255, 255))
        if resized.mode == "P":
            resized = resized.convert("RGBA")
        bg.paste(resized, mask=resized.split()[-1] if resized.mode in ("RGBA","LA") else None)
        resized = bg
    else:
        resized = resized.convert("RGB")
    buf = io.BytesIO()
    resized.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return b64, disp_w, disp_h, orig_w, orig_h

def auto_detect(img: Image.Image) -> dict | None:
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

def draw_overlay(img: Image.Image, coords: dict | None, scale_pct: int, p1=None) -> Image.Image:
    out = img.copy().convert("RGB")
    draw = ImageDraw.Draw(out, "RGBA")
    if coords:
        x,y,w,h = coords["x"],coords["y"],coords["width"],coords["height"]
        # Clamp to image bounds
        x = max(0, min(x, img.width-1))
        y = max(0, min(y, img.height-1))
        w = min(w, img.width - x)
        h = min(h, img.height - y)
        draw.rectangle([x,y,x+w,y+h], outline=(124,111,255,220), width=3)
        draw.rectangle([x,y,x+w,y+h], fill=(124,111,255,30))
        sc = max(0.1, min(1.0, scale_pct/100))
        gw,gh = int(w*sc),int(h*sc)
        gx,gy = x+(w-gw)//2, y+(h-gh)//2
        draw.rectangle([gx,gy,gx+gw,gy+gh], outline=(62,207,142,220), width=2)
        draw.rectangle([gx,gy,gx+gw,gy+gh], fill=(62,207,142,25))
    if p1:
        px,py = p1["x"],p1["y"]
        draw.ellipse([px-10,py-10,px+10,py+10], fill=(245,166,35,230), outline=(255,255,255,200), width=2)
    return out

def composite(graphic: Image.Image, template: Image.Image, coords: dict, scale_pct: int) -> Image.Image:
    x, y, w, h = coords["x"], coords["y"], coords["width"], coords["height"]
    sc = max(0.1, min(1.0, scale_pct/100))
    g = graphic.copy()
    g.thumbnail((int(w * sc), int(h * sc)), Image.LANCZOS)
    rw, rh = g.size
    result = template.copy().convert("RGB")
    ox = x + (w - rw) // 2
    oy = y + (h - rh) // 2
    if g.mode == "RGBA":
        result.paste(g, (ox, oy), g)
    else:
        mask = g.convert("L").point(lambda x: 255)
        result.paste(g, (ox, oy), mask)
    return result

# ── Click canvas ───────────────────────────────────────────────────────────
def click_canvas(img: Image.Image, canvas_key: str) -> dict | None:
    """
    Shows image via st.image (full width, no iframe issues).
    A transparent HTML overlay captures clicks and crosshair.
    """
    orig_w, orig_h = img.size

    # Show the actual image via st.image — full width, no iframe
    st.image(img, use_container_width=True)

    # Transparent click overlay — same aspect ratio, positioned over the image
    aspect = orig_h / orig_w
    # We use a % padding-bottom trick to match the image aspect ratio
    html = f"""
<div id="wrap_{canvas_key}" style="position:relative;width:100%;padding-bottom:{aspect*100:.4f}%;margin-top:-8px;cursor:crosshair;">
  <canvas id="cv_{canvas_key}"
    style="position:absolute;top:0;left:0;width:100%;height:100%;border-radius:4px;">
  </canvas>
</div>
<div id="info_{canvas_key}" style="font-size:11px;color:#7c6fff;font-family:monospace;min-height:16px;margin-top:2px;"></div>
<script>
(function(){{
  const wrap = document.getElementById('wrap_{canvas_key}');
  const cv   = document.getElementById('cv_{canvas_key}');
  const info = document.getElementById('info_{canvas_key}');
  const OW = {orig_w}, OH = {orig_h};

  function sync() {{
    cv.width  = wrap.offsetWidth;
    cv.height = wrap.offsetHeight;
  }}
  sync();
  new ResizeObserver(sync).observe(wrap);

  function toOrig(e) {{
    const r = wrap.getBoundingClientRect();
    return {{
      x: Math.round((e.clientX - r.left) / r.width  * OW),
      y: Math.round((e.clientY - r.top)  / r.height * OH)
    }};
  }}

  wrap.addEventListener('mousemove', function(e) {{
    const p = toOrig(e);
    info.textContent = p.x + ' , ' + p.y + ' px';
    const r = wrap.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const ctx = cv.getContext('2d');
    ctx.clearRect(0,0,cv.width,cv.height);
    ctx.strokeStyle = 'rgba(245,166,35,0.55)';
    ctx.lineWidth = 1; ctx.setLineDash([4,3]);
    ctx.beginPath(); ctx.moveTo(px,0); ctx.lineTo(px,cv.height); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0,py); ctx.lineTo(cv.width,py);  ctx.stroke();
  }});

  wrap.addEventListener('mouseleave', function() {{
    cv.getContext('2d').clearRect(0,0,cv.width,cv.height);
    info.textContent = '';
  }});

  wrap.addEventListener('click', function(e) {{
    const p = toOrig(e);
    const inputs = window.parent.document.querySelectorAll('input[type="text"]');
    for (const inp of inputs) {{
      if (inp.getAttribute('aria-label') === 'coord_input_{canvas_key}') {{
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, p.x + ',' + p.y);
        inp.dispatchEvent(new Event('input', {{bubbles:true}}));
        break;
      }}
    }}
  }});
}})();
</script>
"""
    st.components.v1.html(html, height=60, scrolling=False)
    coord_str = st.text_input("", key=f"coord_input_{canvas_key}",
                               label_visibility="collapsed",
                               placeholder="clicca sull'immagine…")
    if coord_str and "," in coord_str:
        try:
            cx, cy = coord_str.strip().split(",")
            return {"x": int(cx), "y": int(cy)}
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

# ══════════════════════════════════════════════════════════════════════════
# STEP 1: UPLOAD TEMPLATES
# ══════════════════════════════════════════════════════════════════════════
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
                    with tcols[i%3]: st.image(t["img"], caption=t["name"][:14], width=80)
            elif fmt in ss.templates and ss.templates[fmt]:
                st.info(f"✓ {len(ss.templates[fmt])} caricati")
            else:
                st.markdown("<div style='border:2px dashed #2e2e36;border-radius:8px;padding:24px;text-align:center;color:#50505f'>Nessun file</div>", unsafe_allow_html=True)
    st.markdown("---")
    if sum(len(v) for v in ss.templates.values()) > 0:
        if st.button("Avanti → Calibra 🎯", type="primary", use_container_width=True):
            ss.step=2; st.rerun()

# ══════════════════════════════════════════════════════════════════════════
# STEP 2: CALIBRATE
# ══════════════════════════════════════════════════════════════════════════
elif ss.step == 2:
    st.markdown("## 🎯 Step 2 — Calibra le Zone")

    fmt_list = [f for f in FORMATS if f in ss.templates]
    fmt_tabs = st.tabs(fmt_list)

    for tab, fmt in zip(fmt_tabs, fmt_list):
        with tab:
            tpls = ss.templates[fmt]

            # ── Default coords for this format ──
            st.markdown(f"### 🔧 Default per {fmt}")
            st.caption("Le coordinate default si applicano a tutti i template del formato che non hanno un override specifico.")

            def_coords = ss.default_coords.get(fmt)
            def_scale  = ss.default_scale.get(fmt, 90)

            dcol1, dcol2 = st.columns([1,3])
            with dcol1:
                new_def_scale = st.slider("Scala default %", 10, 100, def_scale, key=f"dsc_{fmt}")
                ss.default_scale[fmt] = new_def_scale

                if st.button(f"🔍 Auto-detect (primo template)", key=f"dad_{fmt}", use_container_width=True):
                    det = auto_detect(tpls[0]["img"])
                    if det:
                        ss.default_coords[fmt] = det
                        st.rerun()
                    else:
                        st.error("Non rilevato")

                with st.form(key=f"dform_{fmt}"):
                    dc = def_coords or {}
                    dx = st.number_input("X", value=dc.get("x",0), min_value=0, step=1, key=f"dx_{fmt}")
                    dy = st.number_input("Y", value=dc.get("y",0), min_value=0, step=1, key=f"dy_{fmt}")
                    dw = st.number_input("W", value=dc.get("width",800), min_value=1, step=1, key=f"dw_{fmt}")
                    dh = st.number_input("H", value=dc.get("height",600), min_value=1, step=1, key=f"dh_{fmt}")
                    if st.form_submit_button("💾 Salva default", use_container_width=True, type="primary"):
                        ss.default_coords[fmt] = {"x":dx,"y":dy,"width":dw,"height":dh}
                        ss.default_scale[fmt] = new_def_scale
                        st.rerun()

                if def_coords:
                    st.success(f"✅ Default impostato\n\nscala={new_def_scale}%")

            with dcol2:
                ref_img = tpls[0]["img"]
                # Click calibration for default
                canvas_key = f"def_{fmt}"
                click = click_canvas(draw_overlay(ref_img, def_coords, new_def_scale, ss.calib_p1 if ss.calib_fmt==canvas_key else None), canvas_key)

                if click:
                    if ss.calib_p1 is None or ss.calib_fmt != canvas_key:
                        ss.calib_p1 = click
                        ss.calib_fmt = canvas_key
                        st.rerun()
                    else:
                        p1 = ss.calib_p1
                        x = min(p1["x"], click["x"]); y = min(p1["y"], click["y"])
                        w = abs(click["x"]-p1["x"]); h = abs(click["y"]-p1["y"])
                        if w > 10 and h > 10:
                            ss.default_coords[fmt] = {"x":x,"y":y,"width":w,"height":h}
                        ss.calib_p1 = None; ss.calib_fmt = None
                        st.rerun()

                if ss.calib_p1 and ss.calib_fmt == canvas_key:
                    st.warning(f"P1 selezionato ({ss.calib_p1['x']}, {ss.calib_p1['y']}) → clicca il punto in basso a destra")
                    if st.button("✕ Annulla", key=f"canc_{fmt}"):
                        ss.calib_p1=None; ss.calib_fmt=None; st.rerun()
                else:
                    st.caption("👆 Clicca in alto a sinistra, poi in basso a destra · 🟣 Zona · 🟢 Grafica")

            st.markdown("---")

            # ── Per-template overrides ──
            with st.expander(f"⚙️ Override per singolo template ({fmt})", expanded=False):
                st.caption("Imposta coordinate specifiche per un singolo template, sovrascrivendo il default.")

                tpl_names = [t["name"] for t in tpls]
                sel_tpl_name = st.selectbox("Template", tpl_names, key=f"otpl_{fmt}")
                sel_tpl = next(t for t in tpls if t["name"]==sel_tpl_name)

                ov_coords, ov_src = get_coords(fmt, sel_tpl_name)
                ov_scale, ov_sc_src = get_scale(fmt, sel_tpl_name)

                src_badge = "🟣 Override custom" if ov_src=="custom" else "🔵 Usa default formato"
                st.markdown(f"**Sorgente coordinate:** {src_badge}")

                ocol1, ocol2 = st.columns([1,3])
                with ocol1:
                    new_ov_scale = st.slider("Scala %", 10, 100, ov_scale, key=f"ovsc_{fmt}_{sel_tpl_name}")

                    if st.button("🔍 Auto-detect", key=f"ovad_{fmt}_{sel_tpl_name}", use_container_width=True):
                        det = auto_detect(sel_tpl["img"])
                        if det:
                            set_coords(fmt, sel_tpl_name, det, as_default=False)
                            st.rerun()
                        else: st.error("Non rilevato")

                    with st.form(key=f"ovform_{fmt}_{sel_tpl_name}"):
                        oc = ov_coords or {}
                        ox2 = st.number_input("X", value=oc.get("x",0), min_value=0, step=1)
                        oy2 = st.number_input("Y", value=oc.get("y",0), min_value=0, step=1)
                        ow2 = st.number_input("W", value=oc.get("width",800), min_value=1, step=1)
                        oh2 = st.number_input("H", value=oc.get("height",600), min_value=1, step=1)
                        c1,c2 = st.columns(2)
                        with c1:
                            if st.form_submit_button("💾 Salva override", use_container_width=True, type="primary"):
                                set_coords(fmt, sel_tpl_name, {"x":ox2,"y":oy2,"width":ow2,"height":oh2})
                                set_scale(fmt, sel_tpl_name, new_ov_scale)
                                st.rerun()
                        with c2:
                            if st.form_submit_button("🗑️ Rimuovi override", use_container_width=True):
                                if fmt in ss.tpl_coords and sel_tpl_name in ss.tpl_coords[fmt]:
                                    del ss.tpl_coords[fmt][sel_tpl_name]
                                if fmt in ss.tpl_scale and sel_tpl_name in ss.tpl_scale[fmt]:
                                    del ss.tpl_scale[fmt][sel_tpl_name]
                                st.rerun()

                with ocol2:
                    ov_canvas_key = f"ov_{fmt}_{sel_tpl_name}"
                    p1_this = ss.calib_p1 if ss.calib_fmt == ov_canvas_key else None
                    click2 = click_canvas(draw_overlay(sel_tpl["img"], ov_coords, new_ov_scale, p1_this), ov_canvas_key)
                    if click2:
                        if ss.calib_p1 is None or ss.calib_fmt != ov_canvas_key:
                            ss.calib_p1 = click2; ss.calib_fmt = ov_canvas_key; st.rerun()
                        else:
                            p1 = ss.calib_p1
                            x = min(p1["x"],click2["x"]); y = min(p1["y"],click2["y"])
                            w = abs(click2["x"]-p1["x"]); h = abs(click2["y"]-p1["y"])
                            if w>10 and h>10:
                                set_coords(fmt, sel_tpl_name, {"x":x,"y":y,"width":w,"height":h})
                                set_scale(fmt, sel_tpl_name, new_ov_scale)
                            ss.calib_p1=None; ss.calib_fmt=None; st.rerun()
                    if ss.calib_p1 and ss.calib_fmt == ov_canvas_key:
                        st.warning(f"P1 ({ss.calib_p1['x']}, {ss.calib_p1['y']}) → clicca in basso a destra")
                        if st.button("✕ Annulla", key=f"ocanc_{fmt}_{sel_tpl_name}"):
                            ss.calib_p1=None; ss.calib_fmt=None; st.rerun()

                # List all overrides
                overrides = ss.tpl_coords.get(fmt, {})
                if overrides:
                    st.markdown("**Override attivi:**")
                    for tn, tc in overrides.items():
                        sc_ov = ss.tpl_scale.get(fmt,{}).get(tn, ss.default_scale.get(fmt,90))
                        st.markdown(f"<span class='badge-ok'>✓</span> **{tn}** — x={tc['x']} y={tc['y']} w={tc['width']} h={tc['height']} · {sc_ov}%", unsafe_allow_html=True)

            # Template status grid
            st.markdown(f"**Stato template {fmt}:**")
            rows = st.columns(min(4, len(tpls)))
            for i, t in enumerate(tpls):
                with rows[i % 4]:
                    c, src = get_coords(fmt, t["name"])
                    badge = "✅" if src=="custom" else ("🔵" if src=="default" else "❌")
                    label = "custom" if src=="custom" else ("default" if src=="default" else "no coords")
                    st.caption(f"{badge} {t['name'][:16]}\n{label}")

    st.markdown("---")
    c1,c2 = st.columns(2)
    with c1:
        if st.button("← Indietro", use_container_width=True): ss.step=1; st.rerun()
    with c2:
        if ss.default_coords or any(ss.tpl_coords.values()):
            if st.button("Avanti → Grafiche 🎨", type="primary", use_container_width=True): ss.step=3; st.rerun()
        else:
            st.button("Calibra almeno un formato", disabled=True, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════
# STEP 3: GRAPHICS
# ══════════════════════════════════════════════════════════════════════════
elif ss.step == 3:
    st.markdown("## 🎨 Step 3 — Carica le Grafiche")
    uploaded = st.file_uploader("Carica grafiche", type=["jpg","jpeg","png","webp"],
                                accept_multiple_files=True, label_visibility="collapsed")
    if uploaded:
        ss.graphics = [{"name":Path(f.name).stem,"img":Image.open(f),"ext":Path(f.name).suffix.lower()} for f in uploaded]
        st.success(f"✓ {len(uploaded)} grafiche")
    elif ss.graphics:
        st.info(f"✓ {len(ss.graphics)} già caricate")

    if ss.graphics:
        gcols = st.columns(min(5, len(ss.graphics)))
        for i,g in enumerate(ss.graphics):
            with gcols[i%5]: st.image(g["img"], caption=g["name"][:12], width=90)

        if ss.default_coords or ss.tpl_coords:
            st.markdown("---")
            st.markdown("**👁️ Quick Preview**")
            pc1,pc2,pc3 = st.columns(3)
            with pc1: pg = st.selectbox("Grafica",[g["name"] for g in ss.graphics])
            with pc2:
                avail_fmts = [f for f in ss.templates if ss.default_coords.get(f) or ss.tpl_coords.get(f)]
                pf = st.selectbox("Formato", avail_fmts) if avail_fmts else None
            with pc3:
                pt = st.selectbox("Template", [t["name"] for t in ss.templates.get(pf,[])]) if pf else None
            if pf and pt and st.button("Genera preview", type="secondary"):
                go = next(g for g in ss.graphics if g["name"]==pg)
                to = next(t for t in ss.templates[pf] if t["name"]==pt)
                coords, _ = get_coords(pf, pt)
                scale, _  = get_scale(pf, pt)
                if coords:
                    result = composite(go["img"], to["img"], coords, scale)
                    st.image(result, caption=f"{pg} → {pf}/{pt}", use_container_width=True)
                else:
                    st.error("Nessuna coordinata per questo template")

    st.markdown("---")
    c1,c2 = st.columns(2)
    with c1:
        if st.button("← Indietro", use_container_width=True): ss.step=2; st.rerun()
    with c2:
        if ss.graphics:
            if st.button("Avanti → Esporta 📦", type="primary", use_container_width=True): ss.step=4; st.rerun()

# ══════════════════════════════════════════════════════════════════════════
# STEP 4: EXPORT
# ══════════════════════════════════════════════════════════════════════════
elif ss.step == 4:
    st.markdown("## 📦 Step 4 — Esporta ZIP")

    # Build job list
    all_tpls = []
    for fmt, tpls in ss.templates.items():
        for tpl in tpls:
            coords, src = get_coords(fmt, tpl["name"])
            scale, _ = get_scale(fmt, tpl["name"])
            all_tpls.append({"fmt":fmt,"tpl":tpl,"coords":coords,"scale":scale,"src":src})

    valid_tpls = [j for j in all_tpls if j["coords"]]
    invalid_tpls = [j for j in all_tpls if not j["coords"]]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("🎨 Grafiche", len(ss.graphics))
    c2.metric("🖼️ Template validi", len(valid_tpls))
    c3.metric("❌ Senza coords", len(invalid_tpls))
    c4.metric("📁 Totale immagini", len(ss.graphics)*len(valid_tpls))

    if invalid_tpls:
        with st.expander(f"⚠️ {len(invalid_tpls)} template senza coordinate (verranno saltati)"):
            for j in invalid_tpls:
                st.text(f"{j['fmt']}/{j['tpl']['name']}")

    st.markdown("---")
    st.markdown("**Seleziona grafiche:**")
    gcols = st.columns(min(5, len(ss.graphics)))
    gsel = {}
    for i,g in enumerate(ss.graphics):
        with gcols[i%5]:
            st.image(g["img"], width=80)
            gsel[g["name"]] = st.checkbox(g["name"][:12], value=True, key=f"gs_{i}")
    sel_g = [g for g in ss.graphics if gsel.get(g["name"],True)]

    st.markdown("**Scala finale per formato** (sovrascrive solo i default, non gli override):")
    scols = st.columns(max(1,len(ss.default_scale)))
    for i,fmt in enumerate(ss.default_scale):
        with scols[i%len(scols)]:
            ns = st.slider(fmt, 10, 100, ss.default_scale.get(fmt,90), key=f"es_{fmt}")
            ss.default_scale[fmt] = ns

    st.markdown("---")
    n = len(sel_g) * len(valid_tpls)
    if st.button(f"🚀 Genera {n} immagini → ZIP", type="primary", use_container_width=True, disabled=n==0):
        prog = st.progress(0, text="Avvio...")
        zip_buf = io.BytesIO()
        done, errors = 0, []
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for g in sel_g:
                for job in valid_tpls:
                    fmt, tpl = job["fmt"], job["tpl"]
                    coords, scale = job["coords"], job["scale"]
                    prog.progress(done/n, text=f"⚙️ {g['name']} → {fmt}/{tpl['name']}")
                    try:
                        res = composite(g["img"], tpl["img"], coords, scale)
                        buf = io.BytesIO()
                        fmt_save = "PNG" if g["ext"]==".png" else "JPEG"
                        res.save(buf, format=fmt_save, quality=92)
                        ext = g["ext"] or ".jpg"
                        zf.writestr(f"{g['name']}/{fmt}/{tpl['name']}{ext}", buf.getvalue())
                    except Exception as e:
                        errors.append(f"{tpl['name']}: {e}")
                    done += 1
        prog.progress(1.0, text="✅ Completato!")
        if errors:
            with st.expander(f"⚠️ {len(errors)} errori"): [st.text(e) for e in errors]
        st.download_button(f"⬇️ Scarica ZIP — {done} immagini", zip_buf.getvalue(),
                          "mockup-export.zip","application/zip",
                          use_container_width=True, type="primary")

    if st.button("← Torna alle grafiche", use_container_width=True): ss.step=3; st.rerun()
