#!/usr/bin/env python3
"""Deterministic one-shot builder: plan.json + a color export PNG -> a live Klaviyo template.

This collapses the whole back half of the pipeline (slice -> compress -> upload -> spec ->
create/patch -> render) into ONE call with NO model thinking in the loop. The agent's job is
to produce a correct plan.json (the single analysis pass) and to run the export + the final
verify; everything between is mechanical and runs here, with compression parallelized.

Usage:
  python3 build.py plan.json
  python3 build.py plan.json --skip-render          # build+create only, verify separately
  python3 build.py plan.json --dry-run              # slice+compress locally, no upload/create

plan.json schema (see references/klaviyo_api.md "plan.json"):
{
  "name": "brand_template_en",
  "width": 600,
  "builddir": "builds/brand",         # slices/, final/, manifest, spec.json, payload.json, render.html land here
  "export": "color.png",              # COLOR/filled export PNG (opaque fallback source), rel to builddir or abs
  "export_transparent": "transparent.png",  # TRANSPARENT export PNG (default source for cutouts); omit only for
                                             # a dark-base-native design where every image block is "fill": true
  "store": null,                       # or "<slug>" for a real store
  "target": {"mode": "create"},        # or {"mode":"patch","id":"<templateId>"}
  "blocks": [
    {"role":"image","name":"card","range":[0,1020],"fmt":"png","bg":"#e9ede4","alt":"...","href":null},
    {"role":"image","name":"hero","range":[1020,1800],"fmt":"jpg","bg":"#e9ede4","alt":"..","fill":true},
    {"role":"text","content":"<p>..</p>","bg":"#e9ede4","pad":[44,20,40,40]},
    {"role":"button","label":"..","fill":"#4f6036","color":"#ffffff","block_bg":"#e9ede4",
     "radius":36,"font_family":"'Poppins', ..","font_size":18,"weight":"600","letter_spacing":1,
     "pad":[22,40],"href":""},
    {"role":"image","name":"footer","range":[4875,5193],"fmt":"png","bg":"#e9ede4","alt":".."}
  ]
}
- image blocks: `range` [y0,y1] into the export (1.5x px). DARK METHOD: a block is a TRANSPARENT
  cutout by DEFAULT (sliced from `export_transparent`, alpha kept, PNG) so Klaviyo re-themes the
  base under it in dark; add `"fill": true` to slice from the COLOR export and flatten OPAQUE onto
  `bg` -- for an own-background photo or a region whose transparent cutout came out weird/angled.
  `fmt` jpg|png applies to a FILLED block (jpg photo/gradient, png flat); a cutout is always PNG.
  `bg` = base hex -> block_background_color on EVERY block. asset_id/src/height filled in after upload.
- text/button blocks: passed straight through to build_def (no slice/upload). (button `fill` = its
  pill color, unrelated to an image block's `fill` flag.)
"""
import sys, os, json, time, subprocess, argparse
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGING = os.path.join(HERE, "imaging.py")
KLAVIYO = os.path.join(HERE, "klaviyo.py")
BUILD_DEF = os.path.join(HERE, "build_def.py")
PY = sys.executable or "python3"

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("cmd failed: %s\nSTDOUT:%s\nSTDERR:%s" % (" ".join(cmd), r.stdout, r.stderr))
    return r.stdout

def log(m): sys.stderr.write(m + "\n"); sys.stderr.flush()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--skip-render", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="slice+compress only; no upload/create/render")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    t0 = time.time()
    plan = json.load(open(a.plan, encoding="utf-8"))
    builddir = plan["builddir"]
    store = plan.get("store")
    store_args = (["--store", store] if store else [])
    export = plan["export"]                       # COLOR / filled export (opaque fallback source)
    if not os.path.isabs(export): export = os.path.join(builddir, export)
    if not os.path.exists(export): sys.exit("ERROR: color export PNG not found: %s" % export)
    trans = plan.get("export_transparent")        # TRANSPARENT export (default source for cutouts)
    if trans:
        if not os.path.isabs(trans): trans = os.path.join(builddir, trans)
        if not os.path.exists(trans): sys.exit("ERROR: transparent export PNG not found: %s" % trans)
    slices_dir = os.path.join(builddir, "slices")
    final_dir = os.path.join(builddir, "final")
    os.makedirs(slices_dir, exist_ok=True); os.makedirs(final_dir, exist_ok=True)

    blocks = plan["blocks"]
    imgs = [b for b in blocks if b.get("role") == "image"]
    for b in imgs:
        if not b.get("name") or not b.get("range"):
            sys.exit("ERROR: image block missing name/range: %r" % b)
        # DARK METHOD: a TRANSPARENT cutout on a re-themeable block_bg is the DEFAULT (Klaviyo darkens
        # the base in a dark inbox and the cutout rides on top). "fill": true uses the OPAQUE color
        # export instead -- for an own-background photo, or a region whose transparent cutout came
        # out weird/angled/broken. Every block still gets bg = base hex (block_background_color).
        b["_fill"] = bool(b.get("fill"))
        if not b["_fill"] and not trans:
            sys.exit("ERROR: block %s is a transparent cutout but the plan has no 'export_transparent'. "
                     "Add the transparent export, or mark the block \"fill\": true to bake it opaque." % b["name"])
        b["_src"] = export if b["_fill"] else trans

    # 1) SLICE image bands, grouped by source export (transparent vs color) ---------------
    h600 = {}
    for srcpath in sorted(set(b["_src"] for b in imgs)):
        grp = [b for b in imgs if b["_src"] == srcpath]
        ranges = ",".join("%d:%d" % (b["range"][0], b["range"][1]) for b in grp)
        names = ",".join(b["name"] for b in grp)
        out = run([PY, IMAGING, "slice", srcpath, slices_dir, "--ranges", ranges, "--names", names])
        # parse: "slices/<name>.png\t[y0:y1]\tWxH\theight600=N"
        for line in out.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 4: continue
            nm = os.path.splitext(os.path.basename(parts[0]))[0]
            h600[nm] = int(parts[3].split("=")[1])
    for b in imgs:
        if b["name"] not in h600: sys.exit("ERROR: slice produced no output for %s" % b["name"])
        b["_slice"] = os.path.join(slices_dir, b["name"] + ".png")
        b["_height"] = h600[b["name"]]
    log("sliced %d bands (%d transparent cutout, %d filled)  (+%.1fs)"
        % (len(imgs), sum(1 for b in imgs if not b["_fill"]), sum(1 for b in imgs if b["_fill"]), time.time()-t0))

    # 2) COMPRESS all slices in PARALLEL (the old serial PNG-quantize was the bottleneck) --
    def compress(b):
        # transparent cutout (default) -> PNG keeping alpha, so Klaviyo's block_background_color
        # re-themes the base under it in dark mode. filled ("fill": true) -> flatten onto the base
        # hex -> guaranteed OPAQUE (own-bg photo, or a weird/angled cutout baked back on its base).
        if b["_fill"]:
            ext = "jpg" if b.get("fmt", "jpg") == "jpg" else "png"
        else:
            ext = "png"  # a cutout MUST keep alpha -> always PNG
        outp = os.path.join(final_dir, b["name"] + "." + ext)
        cmd = [PY, IMAGING, "compress", b["_slice"], outp, "--format", ext]
        if ext == "jpg": cmd += ["--quality", str(b.get("quality", 82))]
        if b["_fill"] and b.get("bg"):
            cmd += ["--flatten", b["bg"]]
        run(cmd)
        b["_final"] = outp
        return outp
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(compress, imgs))
    sizes = {b["name"]: os.path.getsize(b["_final"]) for b in imgs}
    log("compressed %d  (+%.1fs)  max=%dKB" % (len(imgs), time.time()-t0, max(sizes.values())//1024))

    # 2b) STRUCTURAL DARK CHECK (deterministic; replaces the unreliable dark-recolor screenshot):
    # a bake block must be OPAQUE, a cutout block must carry alpha. Mismatch = a real dark-mode bug.
    try:
        from PIL import Image
        warns = []
        for b in imgs:
            im = Image.open(b["_final"])
            has_a = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            opaque = (not has_a) or im.convert("RGBA").getchannel("A").getextrema()[0] >= 250
            b["_opaque"] = opaque
            if b["_fill"] and not opaque:
                warns.append("%s: filled block has transparency (should be opaque)" % b["name"])
            elif not b["_fill"] and opaque:
                warns.append("%s: transparent-cutout block came out OPAQUE (won't re-theme in dark) -- "
                             "if it's an own-bg photo mark it \"fill\": true; else the cutout is missing alpha" % b["name"])
        log("dark: %d transparent cutouts (alpha, re-theme), %d filled (opaque)  -- every block bg = base hex"
            % (sum(1 for b in imgs if not b["_fill"]), sum(1 for b in imgs if b["_fill"])))
        for w in warns: log("DARK-CHECK WARNING: " + w)
    except Exception as e:
        log("opacity check skipped: %s" % e)

    if a.dry_run:
        log("dry-run: stopping before upload.");
        for b in imgs: print("%s\t%s\t%dpx\th600=%d\t%dB" % (b["name"], b["_final"], b["range"][1]-b["range"][0], b["_height"], sizes[b["name"]]))
        return

    # 3) UPLOAD all finals (parallel, capped at 3 for the 3/s Klaviyo limit). Parse each upload's
    #    stdout ("name id url") for asset_id+url and match back BY ORDER (ex.map preserves it).
    #    Do NOT pass --manifest to the concurrent uploads: klaviyo.py appends to it in "a" mode, so
    #    3 concurrent appends interleave and corrupt lines. Write the manifest once, single-threaded.
    brand = plan["name"].rsplit("_", 1)[0]
    def upload(b):
        nm = "%s_%s" % (brand, b["name"])  # brand-prefixed asset name
        out = run([PY, KLAVIYO] + store_args + ["upload", b["_final"], "--name", nm])
        line = [l for l in out.strip().splitlines() if l.strip()][-1]
        parts = line.split()
        if len(parts) < 3 or not parts[-2].isdigit():
            raise RuntimeError("unexpected upload output for %s: %r" % (nm, line))
        return (parts[-2], parts[-1])  # (asset_id, url)
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(upload, imgs))
    manifest = os.path.join(builddir, "manifest")
    with open(manifest, "w", encoding="utf-8") as f:
        for b, (aid, src) in zip(imgs, results):
            b["_asset_id"], b["_src"] = aid, src
            f.write("%s_%s\t%s\t%s\n" % (brand, b["name"], aid, src))
    log("uploaded %d  (+%.1fs)" % (len(imgs), time.time()-t0))

    # 4) ASSEMBLE build_def spec (role -> type; inject asset info) ------------------------
    spec_blocks = []
    for b in blocks:
        r = b.get("role")
        if r == "image":
            spec_blocks.append({"type": "image", "asset_id": b["_asset_id"], "src": b["_src"],
                                "height": b["_height"], "alt": b.get("alt"),
                                "href": b.get("href"), "bg": b.get("bg")})
        elif r == "text":
            spec_blocks.append({"type": "text", "content": b["content"], "bg": b.get("bg"), "pad": b.get("pad", [0,0,0,0])})
        elif r == "button":
            nb = {k: v for k, v in b.items() if k != "role"}; nb["type"] = "button"
            spec_blocks.append(nb)
        else:
            sys.exit("ERROR: unknown block role %r" % r)
    spec = {"name": plan["name"], "width": plan.get("width", 600),
            "blocks": spec_blocks, "target": plan.get("target", {"mode": "create"})}
    if plan.get("headings"): spec["headings"] = plan["headings"]
    if plan.get("styles_override"): spec["styles_override"] = plan["styles_override"]
    spec_path = os.path.join(builddir, "spec.json")
    json.dump(spec, open(spec_path, "w"), indent=2)

    # 5) build_def -> payload -------------------------------------------------------------
    payload = run([PY, BUILD_DEF, spec_path])
    payload_path = os.path.join(builddir, "payload.json")
    open(payload_path, "w").write(payload)

    # 6) create or patch ------------------------------------------------------------------
    tgt = spec["target"]
    if tgt.get("mode") == "patch":
        tid = tgt["id"]
        run([PY, KLAVIYO] + store_args + ["patch", tid, payload_path])
    else:
        tid = run([PY, KLAVIYO] + store_args + ["create", payload_path]).strip().splitlines()[-1].strip()
    log("template %s %s  (+%.1fs)" % (tid, tgt.get("mode", "create"), time.time()-t0))

    # 7) render ---------------------------------------------------------------------------
    render_path = os.path.join(builddir, "render.html")
    if not a.skip_render:
        run([PY, KLAVIYO] + store_args + ["render", tid, "--out", render_path])
    log("DONE  template=%s  render=%s  total=%.1fs" % (tid, render_path, time.time()-t0))
    print(json.dumps({"template_id": tid, "render": render_path, "spec": spec_path,
                      "blocks": len(spec_blocks), "images": len(imgs),
                      "seconds": round(time.time()-t0, 1)}))

if __name__ == "__main__":
    main()
