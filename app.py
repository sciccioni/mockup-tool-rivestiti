import streamlit as st
from PIL import Image
import numpy as np
import json, os, zipfile, io, tempfile
from pathlib import Path

st.set_page_config(
    page_title="Mockup Compositor",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #141416; }
[data-testid="stSidebar"] * { color: #e4e4ec !important; }
.stButton > button { border-radius: 6px; font-weight: 500; }
.format-header { font-size: 11px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: #50505f; padding: 8px 0 4px; }
.coord-box { background: #1e1e22; border: 1px solid #2e2e36; border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.zone-preview { border: 2px dashed #7c6fff; border-radius: 6px; padding: 8px; background: rgba(124,111,255,.05); }
</style>
""", unsafe_allow_html=True)

FORMATS = ["Orizzontale", "Quadrato", "Verticali"]

# ── Session state ──────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "template_root": None,
        "templates": {},        # {fmt: [{name, path}]}
        "coords_map": {},       # {fmt: {x,y,width,height}}
        "scale_map": {},        # {fmt: int 10-100}
        "printbox_dir": None,
        "graphics": [],         # list of uploaded file objects
        "sel_format": None,
        "sel_template": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()
ss = st.session_state

# ── Helpers ────────────────────────────────────────────────────────────────
def find_printbox_dir(root: str) -> str:
    """BFS search for folder containing Orizzontale/Quadrato/Verticali"""
    from collections import deque
    q = deque([(root, 0)])
    candidates = []
    while q:
        d, depth = q.popleft()
        try:
            subs = [e.lower() for e in os.listdir(d) if os.path.isdir(os.path.join(d, e))]
        except:
            continue
        matches = sum(1 for f in ["orizzontale","quadrato","verticali"] if f in subs)
        if matches == 3:
            return d
        if matches > 0:
            candidates.append((matches, d))
        if depth < 4:
            for e in os.listdir(d):
                sub = os.path.join(d, e)
                if os.path.isdir(sub):
                    q.append((sub, depth + 1))
    if candidates:
        return sorted(candidates, reverse=True)[0][1]
    return root

def resolve_format_dir(base: str, fmt: str) -> str | None:
    """Case-insensitive folder resolution"""
    try:
        for e in os.listdir(base):
            if e.lower() == fmt.lower() and os.path.isdir(os.path.join(base, e)):
                return os.path.join(base, e)
    except:
        pass
    return None

def load_templates(root: str):
    pb = find_printbox_dir(root)
    coords_file = os.path.join(pb, "coords.json")
    coords_map, scale_map = {}, {}
    if os.path.exists(coords_file):
        try:
            data = json.loads(open(coords_file).read())
            if "_scaleMap" in data:
                scale_map = data.pop("_scaleMap")
            coords_map = data
        except:
            pass

    templates = {}
    for fmt in FORMATS:
        d = resolve_format_dir(pb, fmt)
        if not d:
            continue
        files = sorted([f for f in os.listdir(d) if f.lower().endswith((".jpg",".jpeg",".png"))])
        if files:
            templates[fmt] = [{"name": Path(f).stem, "path": os.path.join(d, f)} for f in files]

    ss.templates = templates
    ss.coords_map = coords_map
    ss.scale_map = {fmt: scale_map.get(fmt, 90) for fmt in FORMATS}
    ss.printbox_dir = pb
    return templates, pb

def save_coords():
    if not ss.printbox_dir:
        return
    data = {**ss.coords_map, "_scaleMap": ss.scale_map}
    with open(os.path.join(ss.printbox_dir, "coords.json"), "w") as f:
        json.dump(data, f, indent=2)

def auto_detect_coords(img_path: str) -> dict | None:
    """Detect cover zone by finding region differing from background"""
    try:
        img = Image.open(img_path).convert("RGB")
        orig_w, orig_h = img.size
        SAMPLE = 400
        small = img.resize((SAMPLE, SAMPLE), Image.NEAREST)
        arr = np.array(small, dtype=float)
        H, W = arr.shape[:2]

        # Background color from corners
        corners = [arr[:8,:8], arr[:8,W-8:], arr[H-8:,:8], arr[H-8:,W-8:]]
        bg = np.mean([c.mean(axis=(0,1)) for c in corners], axis=0)

        # Diff mask
        diff = np.abs(arr - bg).sum(axis=2)
        mask = diff > 18

        ys, xs = np.where(mask)
        if len(xs) == 0:
            return None

        PAD = 4
        minX = max(0, xs.min() - PAD)
        maxX = min(W-1, xs.max() + PAD)
        minY = max(0, ys.min() - PAD)
        maxY = min(H-1, ys.max() + PAD)

        sx, sy = orig_w / SAMPLE, orig_h / SAMPLE
        return {
            "x": int(minX * sx), "y": int(minY * sy),
            "width": int((maxX - minX) * sx),
            "height": int((maxY - minY) * sy)
        }
    except:
        return None

def composite_image(graphic: Image.Image, template_path: str, coords: dict, scale_pct: int) -> Image.Image:
    """Center graphic at scale% inside the zone of the template"""
    template = Image.open(template_path).convert("RGB")
    x, y, w, h = coords["x"], coords["y"], coords["width"], coords["height"]
    scale = max(0.1, min(1.0, scale_pct / 100))

    target_w = int(w * scale)
    target_h = int(h * scale)

    # Resize maintaining aspect ratio (fit inside target box)
    graphic_rgb = graphic.convert("RGBA") if graphic.mode == "RGBA" else graphic.convert("RGB")
    graphic_rgb.thumbnail((target_w, target_h), Image.LANCZOS)

    rw, rh = graphic_rgb.size
    offset_x = x + (w - rw) // 2
    offset_y = y + (h - rh) // 2

    result = template.copy()
    if graphic_rgb.mode == "RGBA":
        result.paste(graphic_rgb, (offset_x, offset_y), graphic_rgb)
    else:
        result.paste(graphic_rgb, (offset_x, offset_y))
    return result

def draw_zone_preview(template_path: str, coords: dict | None, scale_pct: int) -> Image.Image:
    """Draw overlay showing zone + graphic area on template"""
    from PIL import ImageDraw
    img = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    if coords:
        x, y, w, h = coords["x"], coords["y"], coords["width"], coords["height"]
        # Zone outline
        draw.rectangle([x, y, x+w, y+h], outline=(124,111,255,180), width=3)
        draw.rectangle([x, y, x+w, y+h], fill=(124,111,255,30))

        # Graphic area at scale
        sc = max(0.1, min(1.0, scale_pct / 100))
        gw, gh = int(w * sc), int(h * sc)
        gx = x + (w - gw) // 2
        gy = y + (h - gh) // 2
        draw.rectangle([gx, gy, gx+gw, gy+gh], outline=(62,207,142,200), width=2)
        draw.rectangle([gx, gy, gx+gw, gy+gh], fill=(62,207,142,25))

    return img

# ── SIDEBAR ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🖼️ Mockup Compositor")
    st.markdown("---")

    # Template folder
    st.markdown("### 📁 Cartella Template")
    folder_path = st.text_input("Percorso cartella", placeholder="/Users/sciccioni/Desktop/preview app", key="folder_input", label_visibility="collapsed")
    if st.button("📂 Carica Template", use_container_width=True):
        if folder_path and os.path.exists(folder_path):
            templates, pb = load_templates(folder_path)
            total = sum(len(v) for v in templates.values())
            st.success(f"✓ {total} template in {len(templates)} formati")
            for fmt, tpls in templates.items():
                st.caption(f"  {fmt}: {len(tpls)} template")
        else:
            st.error("Percorso non trovato")

    st.markdown("---")

    # Graphics upload
    st.markdown("### 🎨 Grafiche")
    uploaded = st.file_uploader(
        "Carica grafiche",
        type=["jpg","jpeg","png","webp"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )
    if uploaded:
        ss.graphics = uploaded
        st.success(f"✓ {len(uploaded)} grafiche caricate")
        cols = st.columns(3)
        for i, g in enumerate(uploaded[:6]):
            with cols[i % 3]:
                st.image(g, width=60)

    st.markdown("---")

    # Template selector
    if ss.templates:
        st.markdown("### 📋 Template")
        fmt_options = list(ss.templates.keys())
        sel_fmt = st.selectbox("Formato", fmt_options, key="fmt_sel")
        ss.sel_format = sel_fmt

        if sel_fmt and sel_fmt in ss.templates:
            tpl_names = [t["name"] for t in ss.templates[sel_fmt]]
            sel_tpl_name = st.selectbox("Template", tpl_names, key="tpl_sel")
            ss.sel_template = next((t for t in ss.templates[sel_fmt] if t["name"] == sel_tpl_name), None)

# ── MAIN AREA ──────────────────────────────────────────────────────────────
if not ss.templates:
    st.markdown("""
    <div style='text-align:center; padding:80px 0; color:#50505f'>
        <div style='font-size:64px'>🖼️</div>
        <h2 style='color:#8888a0; font-weight:400'>Mockup Compositor</h2>
        <p>Inserisci il percorso della cartella template nella sidebar e clicca <strong>Carica Template</strong></p>
        <br/>
        <p style='font-size:12px'>Struttura attesa:<br/>
        <code>cartella/ → printbox/ → Orizzontale/ · Quadrato/ · Verticali/</code></p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ── TABS ───────────────────────────────────────────────────────────────────
tab_calibra, tab_preview, tab_export = st.tabs(["🎯 Calibra Zone", "👁️ Preview", "📦 Esporta ZIP"])

# ── TAB 1: CALIBRATION ─────────────────────────────────────────────────────
with tab_calibra:
    if not ss.sel_template:
        st.info("Seleziona un template dalla sidebar")
        st.stop()

    fmt = ss.sel_format
    tpl = ss.sel_template
    coords = ss.coords_map.get(fmt)
    scale = ss.scale_map.get(fmt, 90)

    col_img, col_cfg = st.columns([3, 1])

    with col_cfg:
        st.markdown(f"**Formato: {fmt}**")
        st.caption(f"{len(ss.templates.get(fmt,[]))} template")

        # Scale slider
        new_scale = st.slider("Scala grafica %", 10, 100, scale, key=f"scale_{fmt}")
        if new_scale != scale:
            ss.scale_map[fmt] = new_scale
            scale = new_scale

        st.markdown("**Zona copertina (px)**")

        # Auto-detect
        if st.button("🔍 Auto-detect", use_container_width=True):
            detected = auto_detect_coords(tpl["path"])
            if detected:
                ss.coords_map[fmt] = detected
                coords = detected
                st.success(f"✓ x={detected['x']} y={detected['y']} w={detected['width']} h={detected['height']}")
                st.rerun()
            else:
                st.error("Non rilevato — imposta manualmente")

        # Manual coords
        with st.form(key=f"coords_form_{fmt}"):
            c = coords or {}
            cx = st.number_input("X", value=c.get("x", 0), min_value=0, step=1)
            cy = st.number_input("Y", value=c.get("y", 0), min_value=0, step=1)
            cw = st.number_input("Larghezza", value=c.get("width", 800), min_value=1, step=1)
            ch = st.number_input("Altezza", value=c.get("height", 600), min_value=1, step=1)

            if st.form_submit_button("💾 Salva coordinate", use_container_width=True, type="primary"):
                ss.coords_map[fmt] = {"x": cx, "y": cy, "width": cw, "height": ch}
                ss.scale_map[fmt] = new_scale
                save_coords()
                st.success(f"✓ Salvato per {fmt}")
                st.rerun()

        if coords:
            st.markdown(f"""
            <div style='background:#1e1e22;border-radius:6px;padding:8px;font-size:11px;font-family:monospace;color:#8888a0'>
            x={coords['x']} y={coords['y']}<br/>
            w={coords['width']} h={coords['height']}<br/>
            scala={scale}%
            </div>
            """, unsafe_allow_html=True)

    with col_img:
        preview = draw_zone_preview(tpl["path"], coords, scale)
        st.image(preview, caption=f"{tpl['name']} — Viola=zona · Verde=grafica a {scale}%", use_container_width=True)

    # Show all formats status
    st.markdown("---")
    st.markdown("**Stato coordinate per formato:**")
    cols = st.columns(3)
    for i, f in enumerate(FORMATS):
        with cols[i]:
            c = ss.coords_map.get(f)
            sc = ss.scale_map.get(f, 90)
            if c:
                st.success(f"✅ {f}\n\nScala: {sc}%")
            else:
                st.warning(f"⚠️ {f}\n\nNessuna coordinata")

# ── TAB 2: PREVIEW ─────────────────────────────────────────────────────────
with tab_preview:
    if not ss.graphics:
        st.info("Carica le grafiche dalla sidebar")
        st.stop()
    if not ss.sel_template:
        st.info("Seleziona un template dalla sidebar")
        st.stop()

    fmt = ss.sel_format
    coords = ss.coords_map.get(fmt)
    scale = ss.scale_map.get(fmt, 90)

    col1, col2 = st.columns(2)
    with col1:
        graphic_names = [g.name for g in ss.graphics]
        sel_graphic_name = st.selectbox("Grafica", graphic_names)
        sel_graphic = next(g for g in ss.graphics if g.name == sel_graphic_name)
    with col2:
        tpl = ss.sel_template
        st.markdown(f"**Template:** {tpl['name']} ({fmt})")
        if not coords:
            st.warning("⚠️ Coordinate non impostate per questo formato")

    if coords and st.button("👁️ Genera Preview", type="primary", use_container_width=True):
        with st.spinner("Compositing..."):
            graphic = Image.open(sel_graphic)
            result = composite_image(graphic, tpl["path"], coords, scale)
            st.image(result, caption=f"{sel_graphic_name} → {fmt}/{tpl['name']}", use_container_width=True)

            # Download singolo
            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=92)
            st.download_button("⬇️ Scarica questa preview", buf.getvalue(), f"preview_{sel_graphic_name}_{tpl['name']}.jpg", "image/jpeg")

# ── TAB 3: EXPORT ──────────────────────────────────────────────────────────
with tab_export:
    if not ss.graphics:
        st.info("Carica le grafiche dalla sidebar")
        st.stop()

    # Summary
    valid_formats = {fmt: ss.coords_map[fmt] for fmt in FORMATS if fmt in ss.coords_map and fmt in ss.templates}
    all_templates = [(fmt, tpl) for fmt, tpls in ss.templates.items() for tpl in tpls if fmt in valid_formats]
    total_jobs = len(ss.graphics) * len(all_templates)

    col1, col2, col3 = st.columns(3)
    col1.metric("Grafiche", len(ss.graphics))
    col2.metric("Template validi", len(all_templates))
    col3.metric("Immagini da generare", total_jobs)

    if not valid_formats:
        st.error("Nessun formato con coordinate configurate. Vai su **Calibra Zone** prima.")
        st.stop()

    # Formato selezione grafiche
    st.markdown("**Seleziona grafiche da includere:**")
    graphic_sel = {}
    cols = st.columns(4)
    for i, g in enumerate(ss.graphics):
        with cols[i % 4]:
            graphic_sel[g.name] = st.checkbox(g.name, value=True, key=f"gsel_{i}")

    selected_graphics = [g for g in ss.graphics if graphic_sel.get(g.name, True)]

    st.markdown("---")

    if st.button(f"📦 Esporta ZIP ({len(selected_graphics)} grafiche × {len(all_templates)} template = {len(selected_graphics)*len(all_templates)} immagini)", type="primary", use_container_width=True):
        if not selected_graphics:
            st.error("Seleziona almeno una grafica")
            st.stop()

        progress = st.progress(0)
        status = st.empty()
        zip_buf = io.BytesIO()
        total = len(selected_graphics) * len(all_templates)
        done = 0
        errors = []

        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for g in selected_graphics:
                graphic_name = Path(g.name).stem
                try:
                    graphic_img = Image.open(g)
                except Exception as e:
                    errors.append(f"{g.name}: {e}")
                    continue

                for fmt, tpl in all_templates:
                    coords = valid_formats[fmt]
                    scale = ss.scale_map.get(fmt, 90)
                    status.text(f"⚙️ {graphic_name} → {fmt}/{tpl['name']}")
                    try:
                        result = composite_image(graphic_img, tpl["path"], coords, scale)
                        img_buf = io.BytesIO()
                        ext = Path(g.name).suffix.lower()
                        if ext == ".png":
                            result.save(img_buf, format="PNG", optimize=True)
                            zip_name = f"{graphic_name}/{fmt}/{tpl['name']}.png"
                        else:
                            result.save(img_buf, format="JPEG", quality=92)
                            zip_name = f"{graphic_name}/{fmt}/{tpl['name']}.jpg"
                        zf.writestr(zip_name, img_buf.getvalue())
                    except Exception as e:
                        errors.append(f"{tpl['name']}: {e}")
                    done += 1
                    progress.progress(done / total)

        status.text("✅ Export completato!")
        progress.progress(1.0)

        if errors:
            with st.expander(f"⚠️ {len(errors)} errori"):
                for e in errors:
                    st.text(e)

        st.download_button(
            label=f"⬇️ Scarica ZIP ({done} immagini)",
            data=zip_buf.getvalue(),
            file_name=f"mockup-export.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary"
        )
