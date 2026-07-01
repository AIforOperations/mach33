#!/usr/bin/env python3
"""Imaging helpers for the figma_to_klaviyo skill (PIL only).

Subcommands:
  compress <in> <out> [--quality 82] [--format auto|jpg|png] [--max-bytes N]
       auto: alpha OR flat/few-color (<=4096 colors: text, graphics, flat fills) -> PNG;
       photographic / many-color (no alpha) -> JPEG q.
       png path: a HARD-edge cutout (logo/text/icons) quantizes to 256 colors (FASTOCTREE).
       a SMOOTH-alpha cutout (soft glow / drop shadow / feathered edge — a big swathe of
       partial alpha) takes a TRUECOLOR path instead: quantize RGB only, keep 8-bit alpha,
       downscale to fit a byte cap (default 250KB) — a 256-color palette would BAND the
       alpha gradient into visible rings. --max-bytes steps JPEG quality down / sets the
       smooth-alpha PNG cap.
  detect <image> [--frac 0.5] [--y0 N] [--y1 N]
       find light "pill" bands (native-button candidates); merges bands split by dark
       label text. Per pill prints: band, pill hex, text hex, region color above/below,
       and content-cut lines (where an image above/below the pill should end/start).
  gap <image> [--lo 0.30] [--hi 0.65]
       flattest full-width background row in a y fraction range (a split line). Prints y.
       --lo/--hi accept a FRACTION (<=1) or an ABSOLUTE pixel (>1); clamped to the image.
  crop <image> <out> <y0> <y1>
  overview <image> [--out PATH] [--max 1900]      downscale to fit max height (for Read)
  shots <render.png> <outdir>                     overview + white-seam scan (prints white bands)
  dims <image>                                    print "W H" (cross-platform; replaces macOS sips)
"""
import sys, os, argparse, statistics as st
from PIL import Image

def rgb(path):
    im = Image.open(path).convert("RGB"); return im, im.size[0], im.size[1], im.load()

def hx(c): return "#%02x%02x%02x" % tuple(c)

def _dist(a, b): return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])

def edge_color(px, w, y):
    xs = [px[x, y] for x in list(range(0, min(24, w))) + list(range(max(0, w - 24), w))]  # clamp (no negative index on a <24px-wide image)
    return tuple(int(st.mean([p[c] for p in xs])) for c in range(3))

def run_len(px, w, y, T=70):
    # longest contiguous run of pixels whose color differs from THIS row's background.
    # Polarity-agnostic: finds a pill whether it is lighter OR darker than the bg
    # (white pill on blue, or blue pill on white). Label text on the pill does NOT
    # split the run, because the text also differs from the bg.
    bg = edge_color(px, w, y); best = cur = 0
    for x in range(w):
        if _dist(px[x, y], bg) > T: cur += 1; best = cur if cur > best else best
        else: cur = 0
    return best

def bands(px, w, h, frac, y0, y1):
    thr = int(w * frac); out = []; inb = False; s = 0
    for y in range(y0, y1):
        wide = run_len(px, w, y) >= thr
        if wide and not inb: inb = True; s = y
        elif not wide and inb: inb = False; out.append([s, y - 1])
    if inb: out.append([s, y1 - 1])
    merged = []
    for b in out:
        if merged and b[0] - merged[-1][1] <= 24: merged[-1][1] = b[1]  # merge pill halves split by label text
        else: merged.append(b)
    return [b for b in merged if b[1] - b[0] >= 12]  # drop tiny noise bands

def sample_pill(px, w, bt, bb):
    # dominant color in the band = pill fill; most-distinct common color = label text.
    from collections import Counter
    cnt = Counter()
    for y in range(bt, bb + 1):
        for x in range(0, w, 3): cnt[px[x, y]] += 1
    common = [c for c, _ in cnt.most_common(40)]
    pill = common[0]
    text = max(common, key=lambda c: _dist(c, pill))
    return pill, text

def gap_scan(px, w, y, h, step):
    # walk in `step` direction until a near-background (flat) row
    while 0 < y < h - 1 and run_len(px, w, y) > 10: y += step
    return y

def cmd_compress(a):
    im = Image.open(a.infile)
    real_alpha = False
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        real_alpha = im.convert("RGBA").getchannel("A").getextrema()[0] < 250  # a pixel is actually transparent
    fmt = a.format
    if fmt == "auto":
        # alpha -> PNG; flat / few-color (text, graphics, flat fills) -> PNG; photographic -> JPEG
        fmt = "png" if (real_alpha or im.convert("RGB").getcolors(maxcolors=4096) is not None) else "jpg"
    if fmt == "png":
        if real_alpha:
            rgba = im.convert("RGBA")
            ab = rgba.getchannel("A").tobytes()
            soft = sum(1 for v in ab if 12 < v < 243) / max(1, len(ab))  # fraction of partial-alpha px
            # A broad SMOOTH-alpha swathe (>8%) is a glow / soft shadow that FASTOCTREE would
            # band into visible rings -> truecolor path. A hard-edge cutout (even a detailed
            # logo) sits well under 8% partial alpha, so it stays FASTOCTREE (tiny file).
            if soft > 0.08:
                # SMOOTH-alpha cutout (soft glow / drop shadow / feathered photo edge): a 256-color
                # palette quantizes the alpha gradient into ~8-16 steps -> visible concentric RINGS.
                # Keep alpha at full 8-bit, quantize ONLY the RGB, emit a TRUECOLOR RGBA PNG. The
                # alpha gradient is heavy, so bound size by downscaling (default cap 250KB).
                cap = a.max_bytes or 250_000
                w0, h0 = rgba.size
                for scale in (1.0, 0.9, 0.8, 0.72, 0.64, 0.56, 0.5):
                    src = rgba if scale == 1.0 else rgba.resize((max(1, round(w0 * scale)), max(1, round(h0 * scale))), Image.LANCZOS)
                    r, g, b, al = src.split()
                    rgb_q = Image.merge("RGB", (r, g, b)).quantize(colors=256, method=Image.MEDIANCUT).convert("RGB")
                    Image.merge("RGBA", (*rgb_q.split(), al)).save(a.outfile, "PNG", optimize=True)
                    if os.path.getsize(a.outfile) <= cap: break
            else:
                # HARD-edge cutout (logo/text/icons/flat shapes): FASTOCTREE keeps alpha, tiny file
                rgba.quantize(colors=256, method=Image.FASTOCTREE).save(a.outfile, "PNG", optimize=True)
        else:
            im.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT).save(a.outfile, "PNG", optimize=True)
    else:
        if real_alpha:
            sys.stderr.write("warning: --format jpg on a transparent image flattens alpha onto BLACK; use png/auto for a cutout.\n")
        q = a.quality; im = im.convert("RGB")
        im.save(a.outfile, "JPEG", quality=q, optimize=True, progressive=False)
        while a.max_bytes and os.path.getsize(a.outfile) > a.max_bytes and q > 50:
            q -= 6; im.save(a.outfile, "JPEG", quality=q, optimize=True, progressive=False)
    print("%s -> %s  %d B (%s)" % (a.infile, a.outfile, os.path.getsize(a.outfile), fmt))

def cmd_detect(a):
    im, w, h, px = rgb(a.image)
    y0 = a.y0 or 0; y1 = a.y1 or h
    y0 = max(0, min(y0, h - 1)); y1 = max(y0 + 1, min(y1, h))   # clamp to the image (no IndexError on --y1 > h)
    bb = bands(px, w, h, a.frac, y0, y1)
    print("image %dx%d | pill bands: %s" % (w, h, bb))
    for bt, bm in bb:
        pill, dk = sample_pill(px, w, bt, bm)
        cut_above = max(0, gap_scan(px, w, bt, h, -1) - 3)
        cut_below = min(h, gap_scan(px, w, bm, h, 1) + 3)
        print("PILL [%d:%d] h=%d | pill=%s text=%s | above=%s below=%s"
              % (bt, bm, bm - bt, hx(pill), hx(dk), hx(edge_color(px, w, max(0, cut_above - 2))), hx(edge_color(px, w, min(h - 1, cut_below + 2)))))
        print("   content cut: image-above ends y=%d ; image-below starts y=%d (pill becomes a native button)" % (cut_above, cut_below))

def cmd_gap(a):
    im, w, h, px = rgb(a.image)
    lo = int(h * a.lo) if a.lo <= 1 else int(a.lo)   # accept a FRACTION (<=1) OR an absolute pixel (>1)
    hi = int(h * a.hi) if a.hi <= 1 else int(a.hi)
    lo = max(0, min(lo, h - 2)); hi = max(lo + 1, min(hi, h - 1))   # clamp to the image (no IndexError)
    rv = lambda y: st.pstdev([sum(px[x, y]) for x in range(0, w, 4)])
    best = min(range(lo, hi), key=lambda y: (run_len(px, w, y), rv(y)))
    print("split y=%d  (flattest background row in [%d:%d])" % (best, lo, hi))

def cmd_crop(a):
    im = Image.open(a.image); w, h = im.size
    y0 = max(0, a.y0); y1 = min(h, a.y1)
    if y1 <= y0: sys.exit("crop: y1 (%d) must be > y0 (%d) within a %dpx-tall image" % (a.y1, a.y0, h))
    out = im.crop((0, y0, w, y1)); out.save(a.outfile)
    print("cropped [%d:%d] -> %s %s" % (y0, y1, a.outfile, out.size))

def cmd_dims(a):
    w, h = Image.open(a.image).size  # cross-platform replacement for macOS `sips -g pixelWidth -g pixelHeight`
    print("%d %d" % (w, h))

def cmd_overview(a):
    im = Image.open(a.image).convert("RGB"); w, h = im.size
    sc = min(1.0, a.max / h); ov = im.resize((max(1, int(w * sc)), max(1, int(h * sc))))
    out = a.out or (os.path.splitext(a.image)[0] + "_overview.png"); ov.save(out)
    print("%dx%d -> %s %s" % (w, h, out, ov.size))

def cmd_shots(a):
    os.makedirs(a.outdir, exist_ok=True)
    im = Image.open(a.image).convert("RGB"); w, h = im.size; px = im.load()
    sc = min(1.0, 1900 / h); ov = im.resize((max(1, int(w * sc)), max(1, int(h * sc))))
    ovp = os.path.join(a.outdir, os.path.splitext(os.path.basename(a.image))[0] + "_overview.png"); ov.save(ovp)
    step = 3; cols = len(range(0, w, step)); white = []
    for y in range(h):
        # >250 = the #FFFFFF canvas specifically, NOT a cream/off-white design base
        # (a #faf8f6 base has a channel < 250, so it is not flagged as a seam).
        c = sum(1 for x in range(0, w, step) if px[x, y][0] > 250 and px[x, y][1] > 250 and px[x, y][2] > 250)
        if c / cols > 0.5: white.append(y)
    wb = []
    for y in white:
        if wb and y == wb[-1][1] + 1: wb[-1][1] = y
        else: wb.append([y, y])
    print("%dx%d overview -> %s | white-row bands (seams if mid-email): %s"
          % (w, h, ovp, [(s, e, e - s + 1) for s, e in wb]))

def cmd_alphamap(a):
    # Margin-alpha map of the TRANSPARENT export: the dark-opt cutout-vs-bake INPUT.
    # Per y-band, mean alpha of the left+right margins -> TRANSPARENT (on-base -> cutout),
    # OPAQUE (own full-bleed bg -> bake), or MIXED (a section boundary / straddle -> the
    # model decides). This only MEASURES; the bake/cutout call on MIXED stays human judgment.
    im = Image.open(a.image).convert("RGBA"); w, h = im.size; px = im.load()
    m = max(1, min(a.margin, w // 2)); mx = list(range(0, m)) + list(range(w - m, w))
    print("img %dx%d  margin-alpha map (left+right %dpx), band=%d" % (w, h, m, a.band))
    print("y0-y1\tmean_a\tclass")
    y = 0
    while y < h:
        y1 = min(h, y + a.band); tot = n = 0
        for yy in range(y, y1, 4):
            for x in mx:
                tot += px[x, yy][3]; n += 1
        mean = tot / max(1, n)
        cls = "TRANSPARENT" if mean < 30 else ("OPAQUE" if mean > 225 else "MIXED")
        print("%d-%d\t%.0f\t%s" % (y, y1, mean, cls)); y = y1

def _flat_row(px, w, h, c, win):
    lo = max(1, c - win); hi = min(h - 1, c + win)
    if hi <= lo: return max(0, min(c, h))
    return min(range(lo, hi), key=lambda y: (run_len(px, w, y), st.pstdev([sum(px[x, y]) for x in range(0, w, 4)])))

def cmd_slice(a):
    # Crop MANY image ranges in ONE call (replaces N separate `crop` calls) and print each
    # block's height at 600 width (= round(sliceH*600/sliceW)) so the spec needs no in-head math.
    # `--ranges y0:y1,y0:y1,...` lists ONLY the image bands; live-text gaps are simply omitted.
    # `--snap` snaps each interior boundary to the flattest nearby row (reuse gap logic) so a cut
    # never lands on text/a face. 0 and the image height are pinned (no snap on the outer edges).
    im = Image.open(a.image); w, h = im.size
    ranges = []
    for r in a.ranges.split(","):
        r = r.strip()
        if not r: continue
        if ":" not in r: sys.exit("slice: range %r must be y0:y1" % r)
        y0s, y1s = r.split(":", 1); ranges.append([int(y0s), int(y1s)])
    if not ranges: sys.exit("slice: --ranges is empty")
    if a.snap:
        rpx = im.convert("RGB").load()
        for rg in ranges:
            rg[0] = 0 if rg[0] <= 0 else _flat_row(rpx, w, h, rg[0], a.snap_window)
            rg[1] = h if rg[1] >= h else _flat_row(rpx, w, h, rg[1], a.snap_window)
    os.makedirs(a.outdir, exist_ok=True)
    names = [n.strip() for n in a.names.split(",")] if a.names else None
    for i, (y0, y1) in enumerate(ranges):
        y0 = max(0, y0); y1 = min(h, y1)
        if y1 <= y0: sys.exit("slice: empty range [%d:%d]" % (y0, y1))
        nm = names[i] if (names and i < len(names) and names[i]) else "%02d" % (i + 1)
        outp = os.path.join(a.outdir, "%s.png" % nm)
        im.crop((0, y0, w, y1)).save(outp)
        print("%s\t[%d:%d]\t%dx%d\theight600=%d" % (outp, y0, y1, w, y1 - y0, round((y1 - y0) * 600.0 / w)))

def cmd_edges(a):
    # Scripted render-screenshot gate (replaces the per-pixel browser_evaluate): horizontal
    # overflow (screenshot wider than the viewport), white side-gutter (left+right edge columns
    # pure #FFFFFF = the mobile_margin canvas leak), and full-width white bands (a flush-tiling
    # seam if mid-email). Keys on true #FFFFFF (>250) so a cream/off-white base is NOT flagged.
    im = Image.open(a.image).convert("RGB"); w, h = im.size; px = im.load()
    overflow = w > a.width + 1
    step = 3; cols = len(range(0, w, step)); white = []
    for y in range(h):
        c = sum(1 for x in range(0, w, step) if px[x, y][0] > 250 and px[x, y][1] > 250 and px[x, y][2] > 250)
        if c / cols > 0.5: white.append(y)
    bands = []
    for y in white:
        if bands and y == bands[-1][1] + 1: bands[-1][1] = y
        else: bands.append([y, y])
    rows = list(range(0, h, 2)); gut = 0; xr = w - 3
    for y in rows:
        if (px[2, y][0] > 250 and px[2, y][1] > 250 and px[2, y][2] > 250 and
                px[xr, y][0] > 250 and px[xr, y][1] > 250 and px[xr, y][2] > 250):
            gut += 1
    print("edges %dx%d expect_w=%d | h-overflow=%s | edge-white=%.0f%% | full-width-white bands=%s"
          % (w, h, a.width, overflow, 100.0 * gut / max(1, len(rows)), [(s, e, e - s + 1) for s, e in bands]))

def main():
    ap = argparse.ArgumentParser(description="imaging helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compress"); c.add_argument("infile"); c.add_argument("outfile"); c.add_argument("--quality", type=int, default=82); c.add_argument("--format", choices=["auto", "jpg", "png"], default="auto"); c.add_argument("--max-bytes", type=int, default=0)
    d = sub.add_parser("detect"); d.add_argument("image"); d.add_argument("--frac", type=float, default=0.5); d.add_argument("--y0", type=int, default=0); d.add_argument("--y1", type=int, default=0)
    g = sub.add_parser("gap"); g.add_argument("image"); g.add_argument("--lo", type=float, default=0.30); g.add_argument("--hi", type=float, default=0.65)
    cr = sub.add_parser("crop"); cr.add_argument("image"); cr.add_argument("outfile"); cr.add_argument("y0", type=int); cr.add_argument("y1", type=int)
    o = sub.add_parser("overview"); o.add_argument("image"); o.add_argument("--out"); o.add_argument("--max", type=int, default=1900)
    s = sub.add_parser("shots"); s.add_argument("image"); s.add_argument("outdir")
    di = sub.add_parser("dims"); di.add_argument("image")
    am = sub.add_parser("alphamap"); am.add_argument("image"); am.add_argument("--band", type=int, default=120); am.add_argument("--margin", type=int, default=40)
    sl = sub.add_parser("slice"); sl.add_argument("image"); sl.add_argument("outdir"); sl.add_argument("--ranges", required=True); sl.add_argument("--names", default=""); sl.add_argument("--snap", action="store_true"); sl.add_argument("--snap-window", type=int, default=20, dest="snap_window")
    eg = sub.add_parser("edges"); eg.add_argument("image"); eg.add_argument("--width", type=int, default=390)
    a = ap.parse_args()
    {"compress": cmd_compress, "detect": cmd_detect, "gap": cmd_gap, "crop": cmd_crop, "overview": cmd_overview, "shots": cmd_shots, "dims": cmd_dims,
     "alphamap": cmd_alphamap, "slice": cmd_slice, "edges": cmd_edges}[a.cmd](a)

if __name__ == "__main__":
    main()
