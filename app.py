import streamlit as st
from PIL import Image, ImageDraw
import numpy as np
import json, zipfile, io
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
.upload-box { border: 2px dashed #7c6fff; border-radius: 10px; padding: 16px; text-align: center; background: rgba(124,111,255,.04); margin-bottom: 8px; }
.format-pill { display:inline-block; background:#1e1e22; border:1px solid #2e2e36; border-radius:20px; padding:3px 10px; font-size:11px; margin:2px; }
.ok-pill { background:rgba(62,207,142,.12); border-color:rgba(62,207,142,.3); color:#3ecf8e; }
.warn-pill { background:rgba(255,96,89,.1); border-color:rgba(255,96,89,.3); color:#ff6059; }
div[data-testid="stFileUploader"] label { font-size: 13px; }
</style>
""", unsafe_allow_html=True)

FORMATS = ["Orizzontale", "Quadrato", "Verticali"]

# ── Session state ──────────────────────────────────────────────────────────
for k, v in {
    "templates": {},       # {fmt: [{name, img: PIL.Image, bytes}]}
    "coords_map": {},      # {fmt: {x,y,width,height}}
    "scale_map": {},       # {fmt: int}
    "graphics": [],        # [{name, img: PIL.Image}]
    "step": 1,             # 1=upload templates, 2=calibrate, 3=graphics, 4=export
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

ss = st.session_state

# ── Helpers ────────────────────────────────────────────────────────────────
def auto_detect_coords(img: Image.Image) -> dict | None:
    try:
        orig_w, orig_h = img.size
        SAMPLE = 400
        small = img.resize((SAMPLE, SAMPLE), Image.NEAREST).convert("RGB")
        arr = np.array(small, dtype=float)
        H, W = arr.shape[:2]
        corners = [arr[:8,:8], arr[:8,W-8:], arr[H-8:,:8], arr[H-8:,W-8:]]
        bg = np.mean([c.mean(axis=(0,1)) for c in corners], axis=0)
        diff = np.abs(arr - bg).sum(axis=2)
        mask = diff > 18
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return None
        PAD = 4
        minX = max(0, int(xs.min()) - PAD)
        maxX = min(W-1, int(xs.max()) + PAD)
        minY = max(0, int(ys.min()) - PAD)
        maxY = min(H-1, int(ys.max()) + PAD)
        sx, sy = orig_w / SAMPLE, orig_h / SAMPLE
        return {"x": int(minX*sx), "y": int(minY*sy), "width": int((maxX-minX)*sx), "height": int((maxY-minY)*sy)}
    except:
        return None

def draw_zone_overlay(img: Image.Image, coords: dict | None, scale_pct: int) -> Image.Image:
    out = img.copy().convert("RGB")
    if not coords:
        return out
    draw = ImageDraw.Draw(out, "RGBA")
    x, y, w, h = coords["x"], coords["y"], coords["width"], coords["height"]
    draw.rectangle([x, y, x+w, y+h], outline=(124,111,255,200), width=3)
    draw.rectangle([x, y, x+w, y+h], fill=(124,111,255,30))
    sc = max(0.1, min(1.0, scale_pct/100))
    gw, gh = int(w*sc), int(h*sc)
    gx, gy = x + (w-gw)//2, y + (h-gh)//2
    draw.rectangle([gx, gy, gx+gw, gy+gh], outline=(62,207,142,220), width=2)
    draw.rectangle([gx, gy, gx+gw, gy+gh], fill=(62,207,142,25))
    return out

def composite(graphic: Image.Image, template: Image.Image, coords: dict, scale_pct: int) -> Image.Image:
    x, y, w, h = coords["x"], coords["y"], coords["width"], coords["height"]
    sc = max(0.1, min(1.0, scale_pct/100))
    tw, th = int(w*sc), int(h*sc)
    g = graphic.copy()
    g.thumbnail((tw, th), Image.LANCZOS)
    rw, rh = g.size
    ox, oy = x + (w-rw)//2, y + (h-rh)//2
    result = template.copy().convert("RGB")
    if g.mode == "RGBA":
        result.paste(g, (ox, oy), g)
    else:
        result.paste(g.convert("RGB"), (ox, oy))
    return result

def img_to_bytes(img: Image.Image, fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=92)
    return buf.getvalue()

# ── SIDEBAR: progress nav ──────────────────────────────────────────────────
with st.sidebar:
    st.image("https://www.photosi.com/static/images/logo.svg", width=120) if False else st.markdown("## 🖼️ Mockup Compositor")
    st.markdown("---")

    steps = ["📁 Template", "🎯 Calibra", "🎨 Grafiche", "📦 Esporta"]
    for i, s in enumerate(steps, 1):
        active = "**" if ss.step == i else ""
        color = "#7c6fff" if ss.step == i else ("#3ecf8e" if ss.step > i else "#50505f")
        st.markdown(f"<span style='color:{color}'>{active}{i}. {s}{active}</span>", unsafe_allow_html=True)

    st.markdown("---")

    # Status riepilogo
    total_tpl = sum(len(v) for v in ss.templates.values())
    if total_tpl:
        st.markdown(f"**Template:** {total_tpl} in {len(ss.templates)} formati")
    coords_done = [f for f in FORMATS if f in ss.coords_map]
    if coords_done:
        st.markdown(f"**Calibrati:** {', '.join(coords_done)}")
    if ss.graphics:
        st.markdown(f"**Grafiche:** {len(ss.graphics)}")

# ── STEP 1: UPLOAD TEMPLATES ───────────────────────────────────────────────
if ss.step == 1:
    st.markdown("## 📁 Step 1 — Carica i Template")
    st.markdown("Carica tutti i template per ogni formato. Puoi caricarli tutti insieme o formato per formato.")

    col1, col2, col3 = st.columns(3)
    format_cols = {"Orizzontale": col1, "Quadrato": col2, "Verticali": col3}

    for fmt, col in format_cols.items():
        with col:
            st.markdown(f"### {fmt}")
            files = st.file_uploader(
                f"Template {fmt}",
                type=["jpg","jpeg","png"],
                accept_multiple_files=True,
                key=f"upload_{fmt}",
                label_visibility="collapsed"
            )
            if files:
                ss.templates[fmt] = []
                for f in files:
                    img = Image.open(f)
                    ss.templates[fmt].append({
                        "name": Path(f.name).stem,
                        "img": img,
                        "bytes": f.getvalue(),
                        "ext": Path(f.name).suffix.lower()
                    })
                st.success(f"✓ {len(files)} template")
                # Show thumbs
                thumb_cols = st.columns(min(3, len(files)))
                for i, t in enumerate(ss.templates[fmt][:6]):
                    with thumb_cols[i % 3]:
                        st.image(t["img"], caption=t["name"][:15], width=80)
            else:
                if fmt in ss.templates and ss.templates[fmt]:
                    st.info(f"✓ {len(ss.templates[fmt])} già caricati")
                else:
                    st.markdown(f"<div class='upload-box'><span style='color:#50505f'>Nessun file</span></div>", unsafe_allow_html=True)

    st.markdown("---")
    total = sum(len(v) for v in ss.templates.values())
    if total > 0:
        st.success(f"✅ {total} template caricati in {len(ss.templates)} formati")
        if st.button("Avanti → Calibra Zone 🎯", type="primary", use_container_width=True):
            ss.step = 2
            st.rerun()
    else:
        st.info("Carica almeno un formato per continuare")

# ── STEP 2: CALIBRATE ─────────────────────────────────────────────────────
elif ss.step == 2:
    st.markdown("## 🎯 Step 2 — Calibra la Zona Copertina")
    st.markdown("Per ogni formato, definisci dove posizionare la grafica sulla copertina.")

    fmt_tabs = st.tabs([f for f in FORMATS if f in ss.templates])
    fmt_list = [f for f in FORMATS if f in ss.templates]

    for tab, fmt in zip(fmt_tabs, fmt_list):
        with tab:
            tpls = ss.templates[fmt]
            coords = ss.coords_map.get(fmt)
            scale = ss.scale_map.get(fmt, 90)

            # Pick a reference template to calibrate on
            tpl_names = [t["name"] for t in tpls]
            ref_idx = st.selectbox(f"Template di riferimento", range(len(tpl_names)),
                                   format_func=lambda i: tpl_names[i], key=f"ref_{fmt}")
            ref_tpl = tpls[ref_idx]

            col_img, col_cfg = st.columns([3, 1])

            with col_cfg:
                st.markdown("**Scala grafica**")
                new_scale = st.slider("", 10, 100, scale, key=f"scale_{fmt}", label_visibility="collapsed")
                ss.scale_map[fmt] = new_scale

                st.markdown("**Auto-detect zona**")
                if st.button(f"🔍 Auto-detect", key=f"auto_{fmt}", use_container_width=True):
                    detected = auto_detect_coords(ref_tpl["img"])
                    if detected:
                        ss.coords_map[fmt] = detected
                        st.success("✓ Zona rilevata!")
                        st.rerun()
                    else:
                        st.error("Non rilevato — usa coordinate manuali")

                st.markdown("**Coordinate manuali (px)**")
                c = coords or {}
                with st.form(key=f"form_{fmt}"):
                    cx = st.number_input("X", value=c.get("x",0), min_value=0, step=1, key=f"cx_{fmt}")
                    cy = st.number_input("Y", value=c.get("y",0), min_value=0, step=1, key=f"cy_{fmt}")
                    cw = st.number_input("W", value=c.get("width",800), min_value=1, step=1, key=f"cw_{fmt}")
                    ch = st.number_input("H", value=c.get("height",600), min_value=1, step=1, key=f"ch_{fmt}")
                    if st.form_submit_button("💾 Salva", use_container_width=True, type="primary"):
                        ss.coords_map[fmt] = {"x":cx,"y":cy,"width":cw,"height":ch}
                        st.success(f"✓ Salvato")
                        st.rerun()

                if coords:
                    st.markdown(f"""
                    <div style='background:#1e1e22;border-radius:6px;padding:8px;font-size:11px;font-family:monospace;color:#8888a0;margin-top:8px'>
                    x={coords['x']} y={coords['y']}<br/>w={coords['width']} h={coords['height']}<br/>scala={ss.scale_map.get(fmt,90)}%
                    </div>""", unsafe_allow_html=True)
                    st.success("✅ Formato calibrato")
                else:
                    st.warning("⚠️ Zona non definita")

            with col_img:
                overlay = draw_zone_overlay(ref_tpl["img"], coords, ss.scale_map.get(fmt, 90))
                st.image(overlay, caption=f"🟣 Zona totale · 🟢 Grafica al {ss.scale_map.get(fmt,90)}%", use_container_width=True)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Indietro", use_container_width=True):
            ss.step = 1; st.rerun()
    with col2:
        calibrated = [f for f in ss.templates if f in ss.coords_map]
        if calibrated:
            if st.button(f"Avanti → Carica Grafiche 🎨", type="primary", use_container_width=True):
                ss.step = 3; st.rerun()
        else:
            st.button("Calibra almeno un formato per continuare", disabled=True, use_container_width=True)

# ── STEP 3: UPLOAD GRAPHICS ────────────────────────────────────────────────
elif ss.step == 3:
    st.markdown("## 🎨 Step 3 — Carica le Grafiche")
    st.markdown("Carica tutte le grafiche da applicare ai template. Puoi caricarle in bulk.")

    uploaded = st.file_uploader(
        "Carica grafiche (JPG, PNG, WEBP)",
        type=["jpg","jpeg","png","webp"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    if uploaded:
        ss.graphics = []
        for f in uploaded:
            img = Image.open(f)
            ss.graphics.append({"name": Path(f.name).stem, "img": img, "ext": Path(f.name).suffix.lower(), "bytes": f.getvalue()})
        st.success(f"✓ {len(uploaded)} grafiche caricate")

        # Grid preview
        cols = st.columns(5)
        for i, g in enumerate(ss.graphics):
            with cols[i % 5]:
                st.image(g["img"], caption=g["name"][:12], width=100)

    elif ss.graphics:
        st.info(f"✓ {len(ss.graphics)} grafiche già caricate")
        cols = st.columns(5)
        for i, g in enumerate(ss.graphics):
            with cols[i % 5]:
                st.image(g["img"], caption=g["name"][:12], width=100)

    # Quick preview
    if ss.graphics and ss.coords_map:
        st.markdown("---")
        st.markdown("**🔍 Quick Preview**")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            pg = st.selectbox("Grafica", [g["name"] for g in ss.graphics], key="prev_g")
        with pc2:
            pf = st.selectbox("Formato", [f for f in ss.templates if f in ss.coords_map], key="prev_f")
        with pc3:
            pt_list = ss.templates.get(pf, [])
            pt = st.selectbox("Template", [t["name"] for t in pt_list], key="prev_t")

        if st.button("👁️ Preview", type="secondary"):
            g_obj = next(g for g in ss.graphics if g["name"] == pg)
            t_obj = next(t for t in ss.templates[pf] if t["name"] == pt)
            result = composite(g_obj["img"], t_obj["img"], ss.coords_map[pf], ss.scale_map.get(pf,90))
            st.image(result, caption=f"{pg} → {pf}/{pt}", use_container_width=True)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Indietro", use_container_width=True):
            ss.step = 2; st.rerun()
    with col2:
        if ss.graphics:
            if st.button("Avanti → Esporta ZIP 📦", type="primary", use_container_width=True):
                ss.step = 4; st.rerun()
        else:
            st.button("Carica almeno una grafica per continuare", disabled=True, use_container_width=True)

# ── STEP 4: EXPORT ─────────────────────────────────────────────────────────
elif ss.step == 4:
    st.markdown("## 📦 Step 4 — Esporta ZIP")

    valid_fmts = {f: ss.coords_map[f] for f in ss.templates if f in ss.coords_map}
    all_tpls = [(fmt, tpl) for fmt, tpls in ss.templates.items() for tpl in tpls if fmt in valid_fmts]
    total_jobs = len(ss.graphics) * len(all_tpls)

    # Summary cards
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎨 Grafiche", len(ss.graphics))
    c2.metric("📋 Formati", len(valid_fmts))
    c3.metric("🖼️ Template", len(all_tpls))
    c4.metric("📁 Immagini totali", total_jobs)

    st.markdown("---")

    # Graphic selection
    st.markdown("**Seleziona grafiche da includere:**")
    gcols = st.columns(min(5, len(ss.graphics)))
    graphic_sel = {}
    for i, g in enumerate(ss.graphics):
        with gcols[i % 5]:
            st.image(g["img"], width=80)
            graphic_sel[g["name"]] = st.checkbox(g["name"][:10], value=True, key=f"gs_{i}")

    sel_graphics = [g for g in ss.graphics if graphic_sel.get(g["name"], True)]

    # Format/scale summary
    st.markdown("**Scala per formato:**")
    scols = st.columns(len(valid_fmts))
    for i, fmt in enumerate(valid_fmts):
        with scols[i]:
            new_s = st.slider(fmt, 10, 100, ss.scale_map.get(fmt, 90), key=f"exp_scale_{fmt}")
            ss.scale_map[fmt] = new_s

    st.markdown("---")
    n_jobs = len(sel_graphics) * len(all_tpls)

    if st.button(f"🚀 Genera {n_jobs} immagini e crea ZIP", type="primary", use_container_width=True, disabled=n_jobs==0):
        progress = st.progress(0, text="Avvio...")
        zip_buf = io.BytesIO()
        done, errors = 0, []

        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for g in sel_graphics:
                for fmt, tpl in all_tpls:
                    progress.progress(done/n_jobs, text=f"⚙️ {g['name']} → {fmt}/{tpl['name']}")
                    try:
                        result = composite(g["img"], tpl["img"], valid_fmts[fmt], ss.scale_map.get(fmt,90))
                        buf = io.BytesIO()
                        ext = g["ext"]
                        fmt_save = "PNG" if ext == ".png" else "JPEG"
                        result.save(buf, format=fmt_save, quality=92)
                        fname = f"{g['name']}/{fmt}/{tpl['name']}{ext if ext else '.jpg'}"
                        zf.writestr(fname, buf.getvalue())
                    except Exception as e:
                        errors.append(f"{tpl['name']}: {e}")
                    done += 1

        progress.progress(1.0, text="✅ Completato!")

        if errors:
            with st.expander(f"⚠️ {len(errors)} errori"):
                for e in errors: st.text(e)

        st.download_button(
            label=f"⬇️ Scarica ZIP — {done} immagini",
            data=zip_buf.getvalue(),
            file_name="mockup-export.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary"
        )

    st.markdown("---")
    if st.button("← Torna alle grafiche", use_container_width=True):
        ss.step = 3; st.rerun()
