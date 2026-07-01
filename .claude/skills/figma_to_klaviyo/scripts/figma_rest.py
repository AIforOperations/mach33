#!/usr/bin/env python3
"""Figma REST front-half for the skill (READ-ONLY, GET only). Replaces the slow MCP reads + isolation
exports with fast REST calls, and distills the node tree into structured PLANNING FACTS so the planner
reasons over exact data (fonts, colors, text, merge tags, fills, geometry) instead of eyeballing pixels.

Commands (needs FIGMA_TOKEN in .env, scope file_content:read):
  fetch  <file_key> <node_id> <builddir> [--scale 1.5] [--fonts "Fam A,Fam B"]
         -> color.png + transparent.png + plan_facts.json   (one node-tree call, one images call)
  export <file_key> <node_id> <builddir> [--scale 1.5] [--place bbox|render]
         -> color.png + transparent.png only
  facts  <file_key> <node_id> <outfile.json> [--scale 1.5] [--fonts "..."]
         -> plan_facts.json only (no render)

Exports (validated pixel-parity vs the MCP isolation recipe):
  color       = render the frame (its own base fill is baked in -> opaque).
  transparent = render the frame's CHILDREN (each transparent) + composite by absoluteBoundingBox,
                SKIPPING SLICE nodes (export-markers that re-capture the background) and any full-frame
                solid background rectangle. bbox placement is stable under clipsContent frames.
MCP stays the fallback for anything REST can't render, and for translation (which needs Figma WRITES).
"""
import os, sys, io, json, time, argparse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

REPO_HINT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
API = "https://api.figma.com/v1"
MAX_MP = 32_000_000
GRAD = ("GRADIENT_LINEAR", "GRADIENT_RADIAL", "GRADIENT_ANGULAR", "GRADIENT_DIAMOND")

# ---------- auth + http ----------
def token():
    for d in (os.getcwd(), REPO_HINT):
        p = os.path.join(d, ".env")
        if os.path.exists(p):
            for line in open(p):
                if line.startswith("FIGMA_TOKEN="):
                    return line.split("=", 1)[1].strip()
    return os.environ.get("FIGMA_TOKEN")

HDR = {"X-Figma-Token": token()}

def _get(url):
    if not HDR["X-Figma-Token"]:
        sys.exit("ERROR: no FIGMA_TOKEN in .env or env (REST needs it; fall back to MCP).")
    # Figma's render edge (/images) is flaky under bursts: it can return 429 AND transient 404/5xx even
    # for a node we already validated via /files/nodes. Retry those with backoff (a real bad node shows
    # up as a null in the /files/nodes map, not a 404, so retrying 404 here never masks a real not-found).
    for attempt in range(6):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=180).read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 404, 500, 502, 503, 504) and attempt < 5:
                ra = e.headers.get("Retry-After")
                time.sleep(float(ra) if ra else 1.5 * (2 ** attempt)); continue
            raise

def _dl(url):
    return urllib.request.urlopen(url, timeout=180).read()

def get_doc(file_key, node_id):
    j = json.loads(_get("%s/files/%s/nodes?ids=%s&geometry=paths" % (API, file_key, node_id)))
    n = j["nodes"].get(node_id)
    if not n:
        sys.exit("ERROR: node %s not found in %s" % (node_id, file_key))
    return n["document"]

# ---------- small node helpers ----------
def _hex(c):
    return "#%02x%02x%02x" % (round(c["r"] * 255), round(c["g"] * 255), round(c["b"] * 255))

def _vis_fills(n):
    return [f for f in n.get("fills", []) if f.get("visible", True)]

def _solid(fills):
    # Figma paints fills bottom->top, so the TOPMOST (last) opaque solid is the visible color.
    # Returning the first would pick a hidden underlay (e.g. a white CTA label stacked over an
    # olive+black underlay renders WHITE, not olive).
    for f in reversed(fills):
        if f.get("type") == "SOLID" and f.get("color"):
            return _hex(f["color"])
    return None

def _radius(n):
    r = n.get("cornerRadius")
    if isinstance(r, (int, float)):
        return r
    rr = n.get("rectangleCornerRadii")
    return max(rr) if rr else 0

def _style_runs(n, base_c, base_weight, base_italic):
    """Split a TEXT node into style runs (color + bold + italic) via characterStyleOverrides +
    styleOverrideTable, so INLINE styling — a red brand word in white copy, a bold+colored "32,000+",
    a partly-italic line — is surfaced as DATA and the planner reproduces every run with the right
    <span style="color:#hex">/<b>/<i> instead of silently dropping a design color or emphasis.
    Each run carries its ABSOLUTE style. Returns [{t,c,b?,i?}] ONLY when a run differs from the
    node base (else the node-level color/weight/italic already covers it); else None."""
    chars = n.get("characters", "")
    if not chars:
        return None
    cso = n.get("characterStyleOverrides") or []
    tbl = n.get("styleOverrideTable") or {}
    base = (base_c, (base_weight or 400) >= 600, bool(base_italic))
    def sty(i):
        oid = cso[i] if i < len(cso) else 0
        c, w, it = base_c, base_weight, base_italic
        if oid:
            ov = tbl.get(str(oid)) or tbl.get(oid) or {}
            oc = _solid([f for f in ov.get("fills", []) if f.get("visible", True)])
            if oc:
                c = oc
            if ov.get("fontWeight") is not None:
                w = ov.get("fontWeight")
            if ov.get("italic") is not None:
                it = ov.get("italic")
        return (c, (w or 400) >= 600, bool(it))
    runs = []
    for i, ch in enumerate(chars):
        s = sty(i)
        if runs and runs[-1][0] == s:
            runs[-1][1] += ch
        else:
            runs.append([s, ch])
    if all(s == base for s, _ in runs):
        return None
    out = []
    for (c, b, it), t in runs[:16]:
        seg = {"t": t[:60], "c": c}
        if b:
            seg["b"] = True
        if it:
            seg["i"] = True
        out.append(seg)
    return out

def _first_text(n):
    if n.get("type") == "TEXT":
        return n
    for c in n.get("children", []):
        r = _first_text(c)
        if r:
            return r
    return None

def _has_text(n):
    return _first_text(n) is not None

# ---------- facts distiller ----------
def distill(doc, scale, fonts_available):
    fbb = doc["absoluteBoundingBox"]; fx, fy = fbb["x"], fbb["y"]
    W, H = round(fbb["width"] * scale), round(fbb["height"] * scale)
    base_hex = _solid(_vis_fills(doc))
    avail = set(f.strip().lower() for f in (fonts_available or "").split(",") if f.strip())

    texts, images, buttons = [], [], []

    def box(n):
        b = n["absoluteBoundingBox"]
        return {"y0": round((b["y"] - fy) * scale), "y1": round((b["y"] + b["height"] - fy) * scale),
                "x0": round((b["x"] - fx) * scale), "x1": round((b["x"] + b["width"] - fx) * scale)}

    def is_button(n):
        if not n.get("absoluteBoundingBox") or n.get("type") not in ("FRAME", "RECTANGLE", "INSTANCE", "COMPONENT", "GROUP"):
            return False
        fills = _vis_fills(n)
        if not (_solid(fills) or any(f.get("type") in GRAD for f in fills)):
            return False
        b = n["absoluteBoundingBox"]
        return _radius(n) >= 8 and _has_text(n) and b["height"] * scale < 140 and b["width"] < 0.92 * fbb["width"]

    def collect(n):
        if n.get("type") == "SLICE" or n.get("visible") is False or not n.get("absoluteBoundingBox"):
            return
        fills = _vis_fills(n); ftypes = [f.get("type") for f in fills]
        if is_button(n):
            t = _first_text(n); st = (t or {}).get("style", {})
            grad = any(f.get("type") in GRAD for f in fills)
            buttons.append({**box(n), "id": n["id"], "label": (t or {}).get("characters", "")[:80],
                            "fill": _solid(fills), "gradient": grad, "radius": round(_radius(n)),
                            "text_color": _solid(_vis_fills(t)) if t else None,
                            "font": st.get("fontFamily"), "size": st.get("fontSize"),
                            "weight": st.get("fontWeight")})
            return  # do NOT recurse into a button (its label is not a standalone text)
        if n.get("type") == "TEXT":
            st = n.get("style", {}); chars = n.get("characters", "")
            fam = st.get("fontFamily"); base_c = _solid(fills)
            weight = st.get("fontWeight"); italic = bool(st.get("italic"))
            fact = {**box(n), "id": n["id"], "text": chars[:120].replace("\n", " "),
                    "font": fam, "available": (fam.lower() in avail) if (avail and fam) else None,
                    "size": st.get("fontSize"), "weight": weight, "italic": italic,
                    "align": st.get("textAlignHorizontal"), "color": base_c,
                    "merge_tag": "{{" in chars}
            runs = _style_runs(n, base_c, weight, italic)  # inline color/bold/italic runs (reproduce all)
            if runs:
                fact["runs"] = runs
            texts.append(fact)
            return
        if any(ft == "IMAGE" or ft in GRAD for ft in ftypes):
            b = n["absoluteBoundingBox"]
            kind = "IMAGE" if "IMAGE" in ftypes else "GRADIENT"
            wfrac = b["width"] / fbb["width"]
            images.append({**box(n), "id": n["id"], "fill": kind, "w_frac": round(wfrac, 2),
                           "dark_hint": "fill" if (kind == "IMAGE" and wfrac > 0.6) else "cutout"})
        for c in n.get("children", []):
            collect(c)

    for c in doc.get("children", []):
        collect(c)

    # dedupe image regions sharing an exact bbox (a photo + its wrapper report the same box)
    seen = set(); dedup = []
    for im in images:
        key = (im["y0"], im["y1"], im["x0"], im["x1"])
        if key in seen:
            continue
        seen.add(key); dedup.append(im)
    images[:] = dedup

    # mark a text that sits over an image region (-> composite -> image slice, not live text)
    for t in texts:
        cx, cy = (t["x0"] + t["x1"]) / 2, (t["y0"] + t["y1"]) / 2
        t["over_image"] = any(im["x0"] <= cx <= im["x1"] and im["y0"] <= cy <= im["y1"] for im in images)

    # rough band suggestion (LLM finalizes): group units overlapping in y
    units = [{"y0": u["y0"], "y1": u["y1"], "t": k, "u": u}
             for k, arr in (("text", texts), ("image", images), ("button", buttons)) for u in arr]
    units.sort(key=lambda z: z["y0"])
    bands = []
    for z in units:
        if bands and z["y0"] <= bands[-1]["y1"] + 8:
            bands[-1]["y1"] = max(bands[-1]["y1"], z["y1"]); bands[-1]["members"].append(z)
        else:
            bands.append({"y0": z["y0"], "y1": z["y1"], "members": [z]})
    suggested = []
    for bd in bands:
        kinds = set(m["t"] for m in bd["members"])
        has_img = "image" in kinds
        has_unavail = any(m["t"] == "text" and (m["u"].get("available") is False or m["u"].get("over_image")) for m in bd["members"])
        has_btn = "button" in kinds
        if has_img or has_unavail:
            guess = "image"
        elif has_btn and kinds == {"button"}:
            guess = "button"
        elif "text" in kinds:
            guess = "text"
        else:
            guess = "image"
        suggested.append({"y0": bd["y0"], "y1": bd["y1"], "guess": guess, "kinds": sorted(kinds)})

    return {"frame": {"w": W, "h": H, "base_hex": base_hex},
            "counts": {"texts": len(texts), "images": len(images), "buttons": len(buttons)},
            "texts": texts, "images": images, "buttons": buttons, "suggested_bands": suggested}

# ---------- exports ----------
def _is_bg_rect(child, fw, fh):
    bb = child.get("absoluteBoundingBox") or {}
    covers = bb.get("width", 0) >= 0.98 * fw and bb.get("height", 0) >= 0.98 * fh
    solid = any(f.get("type") == "SOLID" and f.get("visible", True) for f in child.get("fills", []))
    return bool(bb) and covers and solid and not child.get("cornerRadius")

def export_from_doc(doc, file_key, node_id, scale, outdir, place="bbox"):
    fbb = doc["absoluteBoundingBox"]; fx, fy = fbb["x"], fbb["y"]
    Wexp, Hexp = round(fbb["width"] * scale), round(fbb["height"] * scale)
    if Wexp * Hexp > MAX_MP:
        sys.stderr.write("WARN: %dx%d exceeds 32MP; Figma will scale it down.\n" % (Wexp, Hexp))
    kids = doc.get("children", [])
    skipped = [k for k in kids if k.get("type") == "SLICE" or _is_bg_rect(k, fbb["width"], fbb["height"])]
    content = [k for k in kids if k not in skipped]
    ids = [node_id] + [k["id"] for k in content]
    resp = json.loads(_get("%s/images/%s?ids=%s&format=png&scale=%s" % (API, file_key, ",".join(ids), scale)))
    if resp.get("err"):
        sys.exit("ERROR: figma /images err: %s (status %s)" % (resp["err"], resp.get("status")))
    urls = resp["images"]
    if not urls.get(node_id):
        sys.exit("ERROR: no frame render url for %s" % node_id)
    os.makedirs(outdir, exist_ok=True)
    color = os.path.join(outdir, "color.png"); open(color, "wb").write(_dl(urls[node_id]))
    W, H = Image.open(color).size

    def dl(k):
        u = urls.get(k["id"]); return (k, Image.open(io.BytesIO(_dl(u))).convert("RGBA")) if u else (k, None)
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(dl, content))
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for k, im in got:               # children array order == bottom->top z-order
        if im is None:
            continue
        b = (k.get("absoluteRenderBounds") if place == "render" and k.get("absoluteRenderBounds") else k["absoluteBoundingBox"])
        canvas.alpha_composite(im, (round((b["x"] - fx) * scale), round((b["y"] - fy) * scale)))
    trans = os.path.join(outdir, "transparent.png"); canvas.save(trans)
    return color, trans, (W, H), [k.get("name") for k in skipped]

# ---------- commands ----------
def cmd_facts(a):
    doc = get_doc(a.file_key, a.node_id)
    facts = distill(doc, a.scale, a.fonts)
    json.dump(facts, open(a.outfile, "w"), indent=1)
    print("%s  frame=%dx%d base=%s  texts=%d images=%d buttons=%d"
          % (a.outfile, facts["frame"]["w"], facts["frame"]["h"], facts["frame"]["base_hex"],
             facts["counts"]["texts"], facts["counts"]["images"], facts["counts"]["buttons"]))

def cmd_export(a):
    doc = get_doc(a.file_key, a.node_id)
    c, t, sz, sk = export_from_doc(doc, a.file_key, a.node_id, a.scale, a.builddir, a.place)
    print("color.png + transparent.png  %dx%d  skipped=%s" % (sz[0], sz[1], sk))

def cmd_fetch(a):
    t0 = time.time()
    doc = get_doc(a.file_key, a.node_id)
    c, t, sz, sk = export_from_doc(doc, a.file_key, a.node_id, a.scale, a.builddir)
    facts = distill(doc, a.scale, a.fonts)
    fp = os.path.join(a.builddir, "plan_facts.json"); json.dump(facts, open(fp, "w"), indent=1)
    print("fetch DONE  %dx%d  texts=%d images=%d buttons=%d  skipped=%s  (%.1fs)"
          % (sz[0], sz[1], facts["counts"]["texts"], facts["counts"]["images"], facts["counts"]["buttons"], sk, time.time() - t0))
    print("wrote: %s/color.png  %s/transparent.png  %s" % (a.builddir, a.builddir, fp))

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    fe = sub.add_parser("fetch"); fe.add_argument("file_key"); fe.add_argument("node_id"); fe.add_argument("builddir")
    fe.add_argument("--scale", type=float, default=1.5); fe.add_argument("--fonts", default="")
    ex = sub.add_parser("export"); ex.add_argument("file_key"); ex.add_argument("node_id"); ex.add_argument("builddir")
    ex.add_argument("--scale", type=float, default=1.5); ex.add_argument("--place", choices=["bbox", "render"], default="bbox")
    fa = sub.add_parser("facts"); fa.add_argument("file_key"); fa.add_argument("node_id"); fa.add_argument("outfile")
    fa.add_argument("--scale", type=float, default=1.5); fa.add_argument("--fonts", default="")
    a = ap.parse_args()
    {"fetch": cmd_fetch, "export": cmd_export, "facts": cmd_facts}[a.cmd](a)

if __name__ == "__main__":
    main()
