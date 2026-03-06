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
.step-nav { display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }
.step-btn { padding:6px 14px; border-radius:20px; font-size:12px; font-weight:600; border:1.5px solid #2e2e36; background:#1e1e22; color:#8888a0; cursor:pointer; }
.step-btn.active { background:#7c6fff; border-color:#7c6fff; color:#fff; }
.step-btn.done { background:rgba(62,207,142,.12); border-color:rgba(62,207,142,.3); color:#3ecf8e; }
</style>
""", unsafe_allow_html=True)

FORMATS = ["Orizzontale", "Quadrato", "Verticali"]

for k, v in {
    "templates": {}, "coords_map": {}, "scale_map": {},
    "graphics": [], "step": 1,
    "calib_click_p1": None,  # first click point {x,y} in original coords
}.items():
    if k not in st.session_state:
        st.session_state[k] = v
ss = st.session_state

# ── Helpers ────────────────────────────────────────────────────────────────
def pil_to_b64(img: Image.Image, max_w=900) -> str:
    img = img.copy()
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode(), img.width, img.height

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
        sx,sy = ow/S, oh/S
        return {"x":int(x1*sx),"y":int(y1*sy),"width":int((x2-x1)*sx),"height":int((y2-y1)*sy)}
    except: return None

def draw_overlay(img: Image.Image, coords: dict | None, scale_pct: int) -> Image.Image:
    out = img.copy().convert("RGB")
    if not coords: return out
    draw = ImageDraw.Draw(out, "RGBA")
    x,y,w,h = coords["x"],coords["y"],coords["width"],coords["height"]
    draw.rectangle([x,y,x+w,y+h], outline=(124,111,255,200), width=3)
    draw.rectangle([x,y,x+w,y+h], fill=(124,111,255,30))
    sc = max(0.1, min(1.0, scale_pct/100))
    gw,gh = int(w*sc),int(h*sc)
    gx,gy = x+(w-gw)//2, y+(h-gh)//2
    draw.rectangle([gx,gy,gx+gw,gy+gh], outline=(62,207,142,220), width=2)
    draw.rectangle([gx,gy,gx+gw,gy+gh], fill=(62,207,142,25))
    # Draw P1 dot if waiting for P2
    if ss.calib_click_p1:
        px,py = ss.calib_click_p1["x"], ss.calib_click_p1["y"]
        draw.ellipse([px-8,py-8,px+8,py+8], fill=(245,166,35,230))
    return out

def composite(graphic: Image.Image, template: Image.Image, coords: dict, scale_pct: int) -> Image.Image:
    x,y,w,h = coords["x"],coords["y"],coords["width"],coords["height"]
    sc = max(0.1, min(1.0, scale_pct/100))
    g = graphic.copy()
    g.thumbnail((int(w*sc), int(h*sc)), Image.LANCZOS)
    rw,rh = g.size
    result = template.copy().convert("RGB")
    ox,oy = x+(w-rw)//2, y+(h-rh)//2
    if g.mode=="RGBA": result.paste(g,(ox,oy),g)
    else: result.paste(g.convert("RGB"),(ox,oy))
    return result

# ── Click canvas component ─────────────────────────────────────────────────
def click_canvas(img: Image.Image, key: str, height=500) -> dict | None:
    """Renders an image with JS click detection. Returns {x, y} in original image coords or None."""
    b64, disp_w, disp_h = pil_to_b64(img, max_w=800)
    orig_w, orig_h = img.size
    scale_x = orig_w / disp_w
    scale_y = orig_h / disp_h

    html = f"""
    <div id="wrap_{key}" style="position:relative;display:inline-block;cursor:crosshair;user-select:none">
      <img id="img_{key}" src="data:image/jpeg;base64,{b64}"
           style="max-width:100%;display:block;border-radius:8px;"
           draggable="false"/>
      <canvas id="cv_{key}" style="position:absolute;top:0;left:0;pointer-events:none;border-radius:8px"></canvas>
    </div>
    <div id="info_{key}" style="font-size:11px;color:#8888a0;margin-top:6px;font-family:monospace"></div>

    <script>
    (function() {{
      const img = document.getElementById('img_{key}');
      const cv  = document.getElementById('cv_{key}');
      const info = document.getElementById('info_{key}');
      const SCALE_X = {scale_x};
      const SCALE_Y = {scale_y};

      function initCanvas() {{
        cv.width  = img.offsetWidth;
        cv.height = img.offsetHeight;
        cv.style.width  = img.offsetWidth  + 'px';
        cv.style.height = img.offsetHeight + 'px';
      }}

      img.onload = initCanvas;
      if (img.complete) initCanvas();

      img.parentElement.addEventListener('click', function(e) {{
        const rect = img.getBoundingClientRect();
        const px = (e.clientX - rect.left);
        const py = (e.clientY - rect.top);
        const origX = Math.round(px * SCALE_X);
        const origY = Math.round(py * SCALE_Y);

        info.textContent = 'Click: ' + origX + ', ' + origY + ' px';

        // Send to Streamlit via query param hack
        const input = window.parent.document.querySelector('input[data-testid="stTextInput"][aria-label="{key}_coord_input"]');
        if (input) {{
          const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          nativeInputValueSetter.call(input, origX + ',' + origY);
          input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}

        // Also try postMessage
        window.parent.postMessage({{type:'click_coord', key:'{key}', x:origX, y:origY}}, '*');
      }});

      // Crosshair on hover
      img.parentElement.addEventListener('mousemove', function(e) {{
        const rect = img.getBoundingClientRect();
        const px = e.clientX - rect.left;
        const py = e.clientY - rect.top;
        const ctx = cv.getContext('2d');
        ctx.clearRect(0,0,cv.width,cv.height);
        ctx.strokeStyle = 'rgba(245,166,35,0.6)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4,3]);
        ctx.beginPath(); ctx.moveTo(px,0); ctx.lineTo(px,cv.height); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0,py); ctx.lineTo(cv.width,py); ctx.stroke();
      }});
    }})();
    </script>
    """
    st.components.v1.html(html, height=disp_h + 40, scrolling=False)

    # Hidden text input to receive click coords via JS
    coord_str = st.text_input("", key=f"{key}_coord_input", label_visibility="collapsed",
                               placeholder="clicca sull'immagine sopra...")
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
    steps_labels = ["📁 Template", "🎯 Calibra", "🎨 Grafiche", "📦 Esporta"]
    for i, label in enumerate(steps_labels, 1):
        if ss.step == i:
            st.markdown(f"**→ {i}. {label}**")
        elif ss.step > i:
            st.markdown(f"<span style='color:#3ecf8e'>✓ {i}. {label}</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"<span style='color:#50505f'>{i}. {label}</span>", unsafe_allow_html=True)
    st.markdown("---")
    total_tpl = sum(len(v) for v in ss.templates.values())
    if total_tpl: st.caption(f"Template: {total_tpl}")
    if ss.coords_map: st.caption(f"Calibrati: {', '.join(ss.coords_map.keys())}")
    if ss.graphics: st.caption(f"Grafiche: {len(ss.graphics)}")

# ── STEP 1: UPLOAD TEMPLATES ───────────────────────────────────────────────
if ss.step == 1:
    st.markdown("## 📁 Step 1 — Carica i Template")
    col1, col2, col3 = st.columns(3)
    for fmt, col in zip(FORMATS, [col1,col2,col3]):
        with col:
            st.markdown(f"### {fmt}")
            files = st.file_uploader(f"Template {fmt}", type=["jpg","jpeg","png"],
                                     accept_multiple_files=True, key=f"up_{fmt}",
                                     label_visibility="collapsed")
            if files:
                ss.templates[fmt] = [{"name": Path(f.name).stem, "img": Image.open(f),
                                       "ext": Path(f.name).suffix.lower()} for f in files]
                st.success(f"✓ {len(files)} caricati")
                tcols = st.columns(min(3, len(files)))
                for i,t in enumerate(ss.templates[fmt][:6]):
                    with tcols[i%3]: st.image(t["img"], caption=t["name"][:14], width=80)
            elif fmt in ss.templates and ss.templates[fmt]:
                st.info(f"✓ {len(ss.templates[fmt])} già caricati")
            else:
                st.markdown("<div style='border:2px dashed #2e2e36;border-radius:8px;padding:24px;text-align:center;color:#50505f'>Nessun file</div>", unsafe_allow_html=True)

    st.markdown("---")
    total = sum(len(v) for v in ss.templates.values())
    if total > 0:
        st.success(f"✅ {total} template pronti")
        if st.button("Avanti → Calibra Zone 🎯", type="primary", use_container_width=True):
            ss.step = 2; st.rerun()
    else:
        st.info("Carica almeno un formato per continuare")

# ── STEP 2: CALIBRATE ─────────────────────────────────────────────────────
elif ss.step == 2:
    st.markdown("## 🎯 Step 2 — Calibra la Zona Copertina")

    fmt_list = [f for f in FORMATS if f in ss.templates]
    fmt_tabs = st.tabs(fmt_list)

    for tab, fmt in zip(fmt_tabs, fmt_list):
        with tab:
            tpls = ss.templates[fmt]
            coords = ss.coords_map.get(fmt)
            scale = ss.scale_map.get(fmt, 90)

            col_cfg, col_img = st.columns([1, 3])

            with col_cfg:
                # Scale
                new_scale = st.slider("Scala %", 10, 100, scale, key=f"sc_{fmt}")
                ss.scale_map[fmt] = new_scale

                # Ref template
                ref_name = st.selectbox("Template riferimento", [t["name"] for t in tpls], key=f"ref_{fmt}")
                ref_tpl = next(t for t in tpls if t["name"] == ref_name)

                # Auto-detect
                if st.button("🔍 Auto-detect", key=f"ad_{fmt}", use_container_width=True):
                    det = auto_detect(ref_tpl["img"])
                    if det:
                        ss.coords_map[fmt] = det
                        ss.calib_click_p1 = None
                        st.success(f"✓ x={det['x']} y={det['y']} w={det['width']} h={det['height']}")
                        st.rerun()
                    else:
                        st.error("Non rilevato")

                st.markdown("---")

                # Click mode info
                if ss.calib_click_p1 is None:
                    st.info("👆 Clicca **in alto a sinistra** della copertina nell'immagine")
                else:
                    p1 = ss.calib_click_p1
                    st.warning(f"P1: {p1['x']}, {p1['y']}\n\n👆 Ora clicca **in basso a destra**")
                    if st.button("✕ Annulla click", key=f"canc_{fmt}", use_container_width=True):
                        ss.calib_click_p1 = None
                        st.rerun()

                st.markdown("---")

                # Manual coords form
                with st.expander("✏️ Coordinate manuali"):
                    c = coords or {}
                    with st.form(key=f"form_{fmt}"):
                        cx = st.number_input("X", value=c.get("x",0), min_value=0, step=1)
                        cy = st.number_input("Y", value=c.get("y",0), min_value=0, step=1)
                        cw = st.number_input("W", value=c.get("width",800), min_value=1, step=1)
                        ch = st.number_input("H", value=c.get("height",600), min_value=1, step=1)
                        if st.form_submit_button("💾 Salva", use_container_width=True, type="primary"):
                            ss.coords_map[fmt] = {"x":cx,"y":cy,"width":cw,"height":ch}
                            ss.calib_click_p1 = None
                            st.rerun()

                if coords:
                    st.success(f"✅ Calibrato\nx={coords['x']} y={coords['y']}\nw={coords['width']} h={coords['height']}\nscala={ss.scale_map.get(fmt,90)}%")

            with col_img:
                overlay_img = draw_overlay(ref_tpl["img"], coords, ss.scale_map.get(fmt,90))
                click = click_canvas(overlay_img, key=f"canvas_{fmt}")

                if click:
                    if ss.calib_click_p1 is None:
                        # First click — save P1
                        ss.calib_click_p1 = click
                        st.rerun()
                    else:
                        # Second click — compute zone
                        p1 = ss.calib_click_p1
                        p2 = click
                        x = min(p1["x"], p2["x"])
                        y = min(p1["y"], p2["y"])
                        w = abs(p2["x"] - p1["x"])
                        h = abs(p2["y"] - p1["y"])
                        if w > 10 and h > 10:
                            ss.coords_map[fmt] = {"x":x,"y":y,"width":w,"height":h}
                        ss.calib_click_p1 = None
                        st.rerun()

                st.caption("🟣 Zona totale · 🟢 Grafica scalata · Crosshair = posizione mouse")

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Indietro", use_container_width=True): ss.step=1; st.rerun()
    with c2:
        if ss.coords_map:
            if st.button("Avanti → Grafiche 🎨", type="primary", use_container_width=True): ss.step=3; st.rerun()
        else:
            st.button("Calibra almeno un formato", disabled=True, use_container_width=True)

# ── STEP 3: UPLOAD GRAPHICS ────────────────────────────────────────────────
elif ss.step == 3:
    st.markdown("## 🎨 Step 3 — Carica le Grafiche")

    uploaded = st.file_uploader("Carica grafiche", type=["jpg","jpeg","png","webp"],
                                accept_multiple_files=True, label_visibility="collapsed")
    if uploaded:
        ss.graphics = [{"name": Path(f.name).stem, "img": Image.open(f),
                        "ext": Path(f.name).suffix.lower()} for f in uploaded]
        st.success(f"✓ {len(uploaded)} grafiche")
    elif ss.graphics:
        st.info(f"✓ {len(ss.graphics)} grafiche già caricate")

    if ss.graphics:
        gcols = st.columns(min(5, len(ss.graphics)))
        for i,g in enumerate(ss.graphics):
            with gcols[i%5]: st.image(g["img"], caption=g["name"][:12], width=90)

        # Quick preview
        if ss.coords_map:
            st.markdown("---")
            st.markdown("**👁️ Quick Preview**")
            pc1, pc2, pc3 = st.columns(3)
            with pc1: pg = st.selectbox("Grafica", [g["name"] for g in ss.graphics])
            with pc2: pf = st.selectbox("Formato", list(ss.coords_map.keys()))
            with pc3:
                ptpls = ss.templates.get(pf, [])
                pt = st.selectbox("Template", [t["name"] for t in ptpls])
            if st.button("Genera preview", type="secondary"):
                go = next(g for g in ss.graphics if g["name"]==pg)
                to = next(t for t in ss.templates[pf] if t["name"]==pt)
                result = composite(go["img"], to["img"], ss.coords_map[pf], ss.scale_map.get(pf,90))
                st.image(result, caption=f"{pg} → {pf}/{pt}", use_container_width=True)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Indietro", use_container_width=True): ss.step=2; st.rerun()
    with c2:
        if ss.graphics:
            if st.button("Avanti → Esporta 📦", type="primary", use_container_width=True): ss.step=4; st.rerun()
        else:
            st.button("Carica almeno una grafica", disabled=True, use_container_width=True)

# ── STEP 4: EXPORT ─────────────────────────────────────────────────────────
elif ss.step == 4:
    st.markdown("## 📦 Step 4 — Esporta ZIP")

    valid = {f: ss.coords_map[f] for f in ss.templates if f in ss.coords_map}
    all_tpls = [(fmt, tpl) for fmt, tpls in ss.templates.items() for tpl in tpls if fmt in valid]

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("🎨 Grafiche", len(ss.graphics))
    c2.metric("📋 Formati", len(valid))
    c3.metric("🖼️ Template", len(all_tpls))
    c4.metric("📁 Tot. immagini", len(ss.graphics)*len(all_tpls))

    st.markdown("---")
    st.markdown("**Seleziona grafiche:**")
    gcols = st.columns(min(5, len(ss.graphics)))
    gsel = {}
    for i,g in enumerate(ss.graphics):
        with gcols[i%5]:
            st.image(g["img"], width=80)
            gsel[g["name"]] = st.checkbox(g["name"][:12], value=True, key=f"gs_{i}")

    sel_g = [g for g in ss.graphics if gsel.get(g["name"], True)]

    st.markdown("**Scala per formato:**")
    scols = st.columns(max(1, len(valid)))
    for i, fmt in enumerate(valid):
        with scols[i]:
            ns = st.slider(fmt, 10, 100, ss.scale_map.get(fmt,90), key=f"es_{fmt}")
            ss.scale_map[fmt] = ns

    st.markdown("---")
    n = len(sel_g) * len(all_tpls)
    if st.button(f"🚀 Genera {n} immagini → ZIP", type="primary", use_container_width=True, disabled=n==0):
        prog = st.progress(0, text="Avvio...")
        zip_buf = io.BytesIO()
        done, errors = 0, []
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for g in sel_g:
                for fmt, tpl in all_tpls:
                    prog.progress(done/n, text=f"⚙️ {g['name']} → {fmt}/{tpl['name']}")
                    try:
                        res = composite(g["img"], tpl["img"], valid[fmt], ss.scale_map.get(fmt,90))
                        buf = io.BytesIO()
                        fmt_save = "PNG" if g["ext"]==".png" else "JPEG"
                        res.save(buf, format=fmt_save, quality=92)
                        zf.writestr(f"{g['name']}/{fmt}/{tpl['name']}{g['ext'] or '.jpg'}", buf.getvalue())
                    except Exception as e:
                        errors.append(f"{tpl['name']}: {e}")
                    done += 1
        prog.progress(1.0, text="✅ Completato!")
        if errors:
            with st.expander(f"⚠️ {len(errors)} errori"): [st.text(e) for e in errors]
        st.download_button(f"⬇️ Scarica ZIP — {done} immagini", zip_buf.getvalue(),
                          "mockup-export.zip", "application/zip",
                          use_container_width=True, type="primary")

    if st.button("← Torna alle grafiche", use_container_width=True): ss.step=3; st.rerun()
