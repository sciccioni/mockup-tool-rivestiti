import streamlit as st
from PIL import Image, ImageDraw, ImageOps
import numpy as np
import zipfile, io, re, json
from pathlib import Path

CALIB_FILE = Path(__file__).parent / "calibration.json"

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

# Tipologie riconosciute dal nome file
TYPE_KEYWORDS = ["gallery", "printbox"]
DEFAULT_TYPE = "gallery"

# Pattern per dimensione (es. 20x20, 32x24, 30x30)
DIM_PATTERN = re.compile(r'(\d+)x(\d+)', re.IGNORECASE)

for k, v in {
    "templates": {},       # {fmt: [{"name":..,"img":..,"ext":..,"subtype":..}]}
    "sub_coords": {},      # {f"{fmt}|{subtype}": {"x":..,"y":..,"width":..,"height":..}}
    "sub_scale": {},       # {f"{fmt}|{subtype}": int}
    "tpl_coords": {},      # {fmt: {tpl_name: coords}} per override singolo
    "tpl_scale": {},       # {fmt: {tpl_name: scale}}
    "graphics": [], "step": 1,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v
ss = st.session_state

# ── Persistenza calibrazione ──────────────────────────────────────────────
def save_calibration():
    """Salva coordinate e scale su file JSON."""
    data = {
        "sub_coords": ss.sub_coords,
        "sub_scale": ss.sub_scale,
        "tpl_coords": ss.tpl_coords,
        "tpl_scale": ss.tpl_scale,
    }
    try:
        CALIB_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        st.toast(f"⚠️ Errore salvataggio: {e}", icon="⚠️")

def load_calibration():
    """Carica coordinate e scale da file JSON (solo al primo avvio)."""
    if not CALIB_FILE.exists():
        return
    try:
        data = json.loads(CALIB_FILE.read_text())
        ss.sub_coords = data.get("sub_coords", {})
        ss.sub_scale = data.get("sub_scale", {})
        ss.tpl_coords = data.get("tpl_coords", {})
        ss.tpl_scale = data.get("tpl_scale", {})
    except Exception as e:
        st.toast(f"⚠️ Errore caricamento calibrazione: {e}", icon="⚠️")

# Carica al primo avvio
if "calib_loaded" not in ss:
    load_calibration()
    ss.calib_loaded = True

# Mostra stato calibrazione in sidebar
with st.sidebar:
    n_sub = len(ss.sub_coords)
    n_tpl = sum(len(v) for v in ss.tpl_coords.values())
    if CALIB_FILE.exists():
        st.caption(f"💾 Calibrazione: {n_sub} sotto-tipi, {n_tpl} override")
        st.caption(f"📄 `{CALIB_FILE.name}`")
    else:
        st.caption("💾 Nessuna calibrazione salvata")

# ── Helpers ────────────────────────────────────────────────────────────────
def flatten(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        src = img.convert("RGBA") if img.mode == "P" else img
        bg.paste(src, mask=src.split()[-1])
        return bg
    return img.convert("RGB")

def detect_subtype(filename: str) -> str:
    """Rileva sotto-tipo dal nome file.
    Combina dimensione (se presente) + tipologia.
    Es: '20x20-SALVIA-gallery_web.jpg' → '20x20_gallery'
        '32x24-PEONIA-gallery_web.jpg' → '32x24_gallery'
        'preview-BIANCO-app_printbox.png' → 'printbox'
    """
    low = filename.lower()

    # Rileva tipologia
    file_type = DEFAULT_TYPE
    for kw in TYPE_KEYWORDS:
        if kw in low:
            file_type = kw
            break

    # Rileva dimensione
    dim_match = DIM_PATTERN.search(low)
    if dim_match:
        dim = f"{dim_match.group(1)}x{dim_match.group(2)}"
        return f"{dim}_{file_type}"

    return file_type

def sub_key(fmt: str, subtype: str) -> str:
    return f"{fmt}|{subtype}"

def get_coords(fmt, tpl_name, subtype):
    """Cerca coordinate: override template → default sotto-tipo."""
    ov = ss.tpl_coords.get(fmt, {}).get(tpl_name)
    if ov: return ov, "custom"
    sk = sub_key(fmt, subtype)
    df = ss.sub_coords.get(sk)
    if df: return df, "default"
    return None, None

def get_scale(fmt, tpl_name, subtype):
    ov = ss.tpl_scale.get(fmt, {}).get(tpl_name)
    if ov is not None: return ov, "custom"
    sk = sub_key(fmt, subtype)
    return ss.sub_scale.get(sk, 90), "default"

def auto_detect(img: Image.Image):
    try:
        ow, oh = img.size
        S = 400
        flat = flatten(img)
        arr = np.array(flat.resize((S,S), Image.NEAREST), dtype=float)
        H, W = arr.shape[:2]
        top    = arr[:6, :].reshape(-1, 3)
        bottom = arr[H-6:, :].reshape(-1, 3)
        left   = arr[:, :6].reshape(-1, 3)
        right  = arr[:, W-6:].reshape(-1, 3)
        bg = np.concatenate([top, bottom, left, right]).mean(axis=0)
        mask = np.abs(arr - bg).sum(axis=2) > 22
        ys, xs = np.where(mask)
        if not len(xs): return None
        PAD = 3
        x1 = max(0, int(xs.min()) - PAD)
        x2 = min(W-1, int(xs.max()) + PAD)
        y1 = max(0, int(ys.min()) - PAD)
        y2 = min(H-1, int(ys.max()) + PAD)
        x = max(0, int(x1*ow/S))
        y = max(0, int(y1*oh/S))
        w = min(int((x2-x1)*ow/S), ow - x)
        h = min(int((y2-y1)*oh/S), oh - y)
        return {"x":x,"y":y,"width":w,"height":h}
    except: return None

def draw_overlay(img: Image.Image, coords, scale_pct) -> Image.Image:
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

def get_subtypes(tpls):
    """Ritorna set ordinato dei sotto-tipi presenti nella lista template."""
    subs = sorted(set(t["subtype"] for t in tpls))
    return subs


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
                tpls = []
                for f in files:
                    sub = detect_subtype(f.name)
                    tpls.append({
                        "name": Path(f.name).stem,
                        "img": ImageOps.exif_transpose(Image.open(f)),
                        "ext": Path(f.name).suffix.lower(),
                        "subtype": sub,
                    })
                ss.templates[fmt] = tpls
                # Mostra raggruppati per sotto-tipo
                subs = get_subtypes(tpls)
                for sub in subs:
                    sub_tpls = [t for t in tpls if t["subtype"] == sub]
                    st.success(f"✓ {len(sub_tpls)} × {sub}")
                    tcols = st.columns(min(3, len(sub_tpls)))
                    for i, t in enumerate(sub_tpls[:6]):
                        with tcols[i % 3]:
                            st.image(flatten(t["img"]), caption=t["name"][:14], width=80)
            elif fmt in ss.templates and ss.templates[fmt]:
                tpls = ss.templates[fmt]
                subs = get_subtypes(tpls)
                for sub in subs:
                    cnt = sum(1 for t in tpls if t["subtype"] == sub)
                    st.info(f"✓ {cnt} × {sub}")
    st.markdown("---")
    if sum(len(v) for v in ss.templates.values()) > 0:
        if st.button("Avanti → Calibra 🎯", type="primary", use_container_width=True):
            ss.step=2; st.rerun()

# ══════════════════════════════════════════════════════════════════
# STEP 2: CALIBRATE — per formato × sotto-tipo
# ══════════════════════════════════════════════════════════════════
elif ss.step == 2:
    st.markdown("## 🎯 Step 2 — Calibra le Zone")
    fmt_list = [f for f in FORMATS if f in ss.templates]
    fmt_tabs = st.tabs(fmt_list)

    for tab, fmt in zip(fmt_tabs, fmt_list):
        with tab:
            tpls = ss.templates[fmt]
            subs = get_subtypes(tpls)

            # Tab interno per sotto-tipo
            if len(subs) > 1:
                sub_tabs = st.tabs([f"📦 {s.upper()}" for s in subs])
            else:
                sub_tabs = [tab]  # usa il tab corrente

            for stab, sub in zip(sub_tabs, subs):
                with stab:
                    sk = sub_key(fmt, sub)
                    sub_tpls = [t for t in tpls if t["subtype"] == sub]
                    def_coords = ss.sub_coords.get(sk)
                    def_scale = ss.sub_scale.get(sk, 90)

                    st.markdown(f"#### {fmt} · {sub.upper()} ({len(sub_tpls)} template)")
                    col_cfg, col_img = st.columns([1, 2])

                    with col_cfg:
                        new_scale = st.slider("Scala %", 10, 100, def_scale, key=f"dsc_{sk}")
                        ss.sub_scale[sk] = new_scale

                        if st.button("🔍 Auto-detect", key=f"dad_{sk}", use_container_width=True):
                            det = auto_detect(sub_tpls[0]["img"])
                            if det:
                                ss.sub_coords[sk] = det
                                save_calibration()
                                st.rerun()
                            else:
                                st.error("Non rilevato")

                        with st.form(key=f"dform_{sk}"):
                            dc = def_coords or {}
                            dx = st.number_input("X", value=dc.get("x",0), min_value=0, step=1)
                            dy = st.number_input("Y", value=dc.get("y",0), min_value=0, step=1)
                            dw = st.number_input("W", value=dc.get("width",800), min_value=1, step=1)
                            dh = st.number_input("H", value=dc.get("height",600), min_value=1, step=1)
                            if st.form_submit_button("💾 Salva default", use_container_width=True, type="primary"):
                                ss.sub_coords[sk] = {"x":dx,"y":dy,"width":dw,"height":dh}
                                ss.sub_scale[sk] = new_scale
                                save_calibration()
                                st.rerun()

                        if def_coords:
                            st.markdown(
                                f"<div style='background:#1e1e22;border:2px solid #3ecf8e;border-radius:8px;"
                                f"padding:10px 14px;font-family:monospace;font-size:13px;line-height:2'>"
                                f"<span style='color:#3ecf8e;font-weight:700'>✅ {sub.upper()}</span><br/>"
                                f"<span style='color:#a89eff'>X</span> <span style='color:#fff;font-weight:600'>{def_coords['x']}</span> &nbsp;&nbsp;"
                                f"<span style='color:#a89eff'>Y</span> <span style='color:#fff;font-weight:600'>{def_coords['y']}</span><br/>"
                                f"<span style='color:#a89eff'>W</span> <span style='color:#fff;font-weight:600'>{def_coords['width']}</span> &nbsp;&nbsp;"
                                f"<span style='color:#a89eff'>H</span> <span style='color:#fff;font-weight:600'>{def_coords['height']}</span><br/>"
                                f"<span style='color:#a89eff'>Scala</span> <span style='color:#f5a623;font-weight:600'>{new_scale}%</span>"
                                f"</div>", unsafe_allow_html=True)

                    with col_img:
                        overlay = draw_overlay(sub_tpls[0]["img"], def_coords, new_scale)
                        st.image(overlay, use_container_width=True)
                        if def_coords:
                            ow, oh = sub_tpls[0]["img"].size
                            st.caption(f"Template: {ow}×{oh}px — Zona: ({def_coords['x']},{def_coords['y']}) → ({def_coords['x']+def_coords['width']},{def_coords['y']+def_coords['height']})")

                    # Override per singolo template
                    st.markdown("---")
                    with st.expander(f"⚙️ Override per singolo template ({sub})"):
                        tpl_names = [t["name"] for t in sub_tpls]
                        sel_name = st.selectbox("Template", tpl_names, key=f"osel_{sk}")
                        sel_tpl = next(t for t in sub_tpls if t["name"] == sel_name)
                        ov_coords, ov_src = get_coords(fmt, sel_name, sub)
                        ov_scale, _ = get_scale(fmt, sel_name, sub)

                        st.caption(f"Sorgente: {'🟢 custom' if ov_src=='custom' else '🔵 default ' + sub}")

                        ocol1, ocol2 = st.columns([1, 2])
                        with ocol1:
                            nov_scale = st.slider("Scala %", 10, 100, ov_scale, key=f"ovsc_{sk}_{sel_name}")
                            if st.button("🔍 Auto-detect", key=f"ovad_{sk}_{sel_name}", use_container_width=True):
                                det = auto_detect(sel_tpl["img"])
                                if det:
                                    if fmt not in ss.tpl_coords: ss.tpl_coords[fmt] = {}
                                    ss.tpl_coords[fmt][sel_name] = det
                                    save_calibration()
                                    st.rerun()
                            with st.form(key=f"ovform_{sk}_{sel_name}"):
                                oc = ov_coords or {}
                                ox2 = st.number_input("X", value=oc.get("x",0), min_value=0, step=1)
                                oy2 = st.number_input("Y", value=oc.get("y",0), min_value=0, step=1)
                                ow2 = st.number_input("W", value=oc.get("width",800), min_value=1, step=1)
                                oh2 = st.number_input("H", value=oc.get("height",600), min_value=1, step=1)
                                c1, c2 = st.columns(2)
                                with c1:
                                    if st.form_submit_button("💾 Salva", use_container_width=True, type="primary"):
                                        if fmt not in ss.tpl_coords: ss.tpl_coords[fmt] = {}
                                        ss.tpl_coords[fmt][sel_name] = {"x":ox2,"y":oy2,"width":ow2,"height":oh2}
                                        if fmt not in ss.tpl_scale: ss.tpl_scale[fmt] = {}
                                        ss.tpl_scale[fmt][sel_name] = nov_scale
                                        save_calibration()
                                        st.rerun()
                                    if st.form_submit_button("🗑️ Reset", use_container_width=True):
                                        ss.tpl_coords.get(fmt, {}).pop(sel_name, None)
                                        ss.tpl_scale.get(fmt, {}).pop(sel_name, None)
                                        save_calibration()
                                        st.rerun()

                        with ocol2:
                            ov_overlay = draw_overlay(sel_tpl["img"], ov_coords, nov_scale)
                            st.image(ov_overlay, use_container_width=True)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("← Indietro", use_container_width=True): ss.step=1; st.rerun()
    with c2:
        has_any = any(ss.sub_coords.values()) or any(ss.tpl_coords.values())
        if has_any:
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
        ss.graphics = [{"name":Path(f.name).stem,"img":ImageOps.exif_transpose(Image.open(f)),"ext":Path(f.name).suffix.lower()} for f in uploaded]
    elif ss.graphics:
        st.info(f"✓ {len(ss.graphics)} già caricate")
    if ss.graphics:
        gcols = st.columns(min(5, len(ss.graphics)))
        for i, g in enumerate(ss.graphics):
            with gcols[i % 5]: st.image(flatten(g["img"]), caption=g["name"][:12], width=90)
        if ss.sub_coords or ss.tpl_coords:
            st.markdown("---")
            st.markdown("**👁️ Quick Preview**")
            pc1, pc2, pc3 = st.columns(3)
            with pc1: pg = st.selectbox("Grafica", [g["name"] for g in ss.graphics])
            with pc2:
                # Tutti i formati che hanno almeno un sotto-tipo calibrato
                avail = []
                for f in FORMATS:
                    if f not in ss.templates: continue
                    for t in ss.templates[f]:
                        coords, _ = get_coords(f, t["name"], t["subtype"])
                        if coords:
                            if f not in avail: avail.append(f)
                            break
                pf = st.selectbox("Formato", avail) if avail else None
            with pc3:
                pt = st.selectbox("Template", [t["name"] for t in ss.templates.get(pf, [])]) if pf else None
            if pf and pt and st.button("Genera preview"):
                go = next(g for g in ss.graphics if g["name"] == pg)
                to = next(t for t in ss.templates[pf] if t["name"] == pt)
                coords, _ = get_coords(pf, pt, to["subtype"])
                scale, _ = get_scale(pf, pt, to["subtype"])
                if coords:
                    st.image(composite(go["img"], to["img"], coords, scale), use_container_width=True)
    st.markdown("---")
    c1, c2 = st.columns(2)
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
    all_jobs = []
    for fmt, tpls in ss.templates.items():
        for tpl in tpls:
            coords, src = get_coords(fmt, tpl["name"], tpl["subtype"])
            scale, _ = get_scale(fmt, tpl["name"], tpl["subtype"])
            all_jobs.append({"fmt":fmt, "tpl":tpl, "coords":coords, "scale":scale})
    valid = [j for j in all_jobs if j["coords"]]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🎨 Grafiche", len(ss.graphics))
    c2.metric("🖼️ Template validi", len(valid))
    c3.metric("❌ Senza coords", len(all_jobs) - len(valid))
    c4.metric("📁 Tot.", len(ss.graphics) * len(valid))
    st.markdown("---")
    gcols = st.columns(min(5, len(ss.graphics)))
    gsel = {}
    for i, g in enumerate(ss.graphics):
        with gcols[i % 5]:
            st.image(flatten(g["img"]), width=80)
            gsel[g["name"]] = st.checkbox(g["name"][:12], value=True, key=f"gs_{i}")
    sel_g = [g for g in ss.graphics if gsel.get(g["name"], True)]
    st.markdown("---")
    n = len(sel_g) * len(valid)
    if st.button(f"🚀 Genera {n} immagini → ZIP", type="primary", use_container_width=True, disabled=n==0):
        prog = st.progress(0, text="Avvio...")
        zip_buf = io.BytesIO(); done, errors = 0, []
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for g in sel_g:
                for job in valid:
                    prog.progress(done / n, text=f"⚙️ {g['name']} → {job['fmt']}/{job['tpl']['subtype']}/{job['tpl']['name']}")
                    try:
                        res = composite(g["img"], job["tpl"]["img"], job["coords"], job["scale"])
                        buf = io.BytesIO()
                        res.save(buf, format="PNG" if g["ext"]==".png" else "JPEG", quality=92)
                        zf.writestr(f"{g['name']}/{job['fmt']}/{job['tpl']['subtype']}/{job['tpl']['name']}{g['ext'] or '.jpg'}", buf.getvalue())
                    except Exception as e: errors.append(str(e))
                    done += 1
        prog.progress(1.0, text="✅ Completato!")
        if errors:
            with st.expander(f"⚠️ {len(errors)} errori"): [st.text(e) for e in errors]
        st.download_button(f"⬇️ Scarica ZIP — {done} immagini", zip_buf.getvalue(),
                          "mockup-export.zip", "application/zip", use_container_width=True, type="primary")
    if st.button("← Indietro", use_container_width=True): ss.step=3; st.rerun()
