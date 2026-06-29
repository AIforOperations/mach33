#!/usr/bin/env python3
"""Expand a compact block-spec JSON into a full Klaviyo SYSTEM_DRAGGABLE payload.

Usage:
  python3 build_def.py spec.json > payload.json
  (then: klaviyo.py create payload.json   OR   klaviyo.py patch <id> payload.json)

Spec format: see references/klaviyo_api.md. Produces a clean definition with NO id/data_id
(safe for both create and patch). `target.mode` = "create" (default) or "patch" (+ id).
"""
import sys, os, json

# Klaviyo rejects non-integer values for these style numerics (e.g. letter_spacing
# 1.36 -> HTTP 400). line_height / mobile_line_height are floats and are NOT here.
INT_STYLE_KEYS = {"letter_spacing", "font_size", "mobile_font_size", "border_radius", "border_width",
                  "margin_top", "margin_bottom", "margin_left", "margin_right",
                  "inner_padding_top", "inner_padding_bottom", "inner_padding_left", "inner_padding_right",
                  "mobile_margin", "mobile_padding_top", "mobile_padding_bottom",
                  "mobile_padding_left", "mobile_padding_right", "width", "max_width", "height"}

def coerce_ints(styles):
    for k, v in list(styles.items()):
        if k in INT_STYLE_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
            styles[k] = int(round(v))
    return styles

def section(block):
    return {"content_type": "section", "type": "section",
            "data": {"properties": {}, "display_options": {}, "styles": {}},
            "rows": [{"data": {"styles": {"column_layout": "1-column-full-width"}},
                      "columns": [{"data": {}, "blocks": [block]}]}]}

def img_block(b):
    # No per-block inner_padding: the global base-styles already zero it (full-bleed,
    # slices tile flush); real SYSTEM_DRAGGABLE image blocks omit it too.
    s = {"width": b.get("width", 600), "max_width": b.get("width", 600), "height": b["height"]}
    if b.get("bg"): s["block_background_color"] = b["bg"]  # transparent-cutout dark-opt: themeable block bg = design fill color
    coerce_ints(s)
    return {"content_type": "block", "type": "image", "data": {
        "properties": {"dynamic": False, "alt_text": b.get("alt"), "asset_id": str(b["asset_id"]),
                       "href": b.get("href"), "src": b["src"]},
        "display_options": {},
        "styles": s}}

def _pad(p, n, what):
    # Normalize a padding list to exactly n values so a short/over-long `pad` gives a
    # clean warning + sane result instead of an uncaught IndexError.
    p = list(p) if isinstance(p, (list, tuple)) else [p]
    if len(p) != n:
        sys.stderr.write("warning: %s pad expected %d values, got %r; adjusted to %d\n" % (what, n, p, n))
        p = (p + [0, 0, 0, 0])[:n]
    return p

def text_block(b):
    pad = _pad(b.get("pad", [0, 0, 0, 0]), 4, "text")
    s = {"inner_padding_top": pad[0], "inner_padding_bottom": pad[1],
         "inner_padding_left": pad[2], "inner_padding_right": pad[3]}
    if b.get("bg"): s["block_background_color"] = b["bg"]
    coerce_ints(s)
    return {"content_type": "block", "type": "text",
            "data": {"content": b["content"], "display_options": {}, "styles": s}}

def button_block(b):
    pad = _pad(b.get("pad", [18, 50]), 2, "button")
    # Defaults are neutral FALLBACKS (the spec sets these per design). font_family
    # leads with a web-safe stack that carries bold and is account-agnostic; set
    # the account's hosted family in the spec when you want the brand font.
    s = {"background_color": b.get("fill", "#f5f5f1"),
         "block_background_color": b.get("block_bg", "#ffffff"),
         "border_radius": b.get("radius", 30), "color": b.get("color", "#000000"),
         "font_family": b.get("font_family", "Helvetica, Arial, sans-serif"),
         "font_size": b.get("font_size", 16), "font_style": "normal",
         "font_weight": str(b.get("weight", "700")),
         "letter_spacing": b.get("letter_spacing", 1),
         "inner_padding_top": pad[0], "inner_padding_bottom": pad[0],
         "inner_padding_left": pad[1], "inner_padding_right": pad[1],
         "mobile_stretch_content": True}
    coerce_ints(s)
    return {"content_type": "block", "type": "button", "data": {
        "content": b["label"], "properties": {"href": b.get("href")}, "display_options": {},
        "styles": s}}

BUILDERS = {"image": img_block, "text": text_block, "button": button_block}
REQUIRED = {"image": ["asset_id", "src", "height"], "text": ["content"], "button": ["label"]}

def default_styles(content_bg):
    return [
        {"style_type": "base-styles", "properties": {"currency": "en-US-u-nu-latn_USD_US_USD", "currency_set_on_template": False, "disable_websafe_fonts": False, "mobile_optimizations": True, "tip_tap_enabled": True}, "styles": {"background_format": "auto", "background_position": "left-top", "background_repeat": True, "border_color": "#aaaaaa", "border_radius": 0, "content_background_color": content_bg, "inner_padding_bottom": 0, "inner_padding_left": 0, "inner_padding_right": 0, "inner_padding_top": 0, "margin_top": 0}},
        {"style_type": "text-styles", "styles": {"color": "#373F47", "font_family": "Helvetica", "font_size": 16, "font_style": "normal", "font_weight": "400", "letter_spacing": 0, "line_height": 1.3, "mobile_font_size": 14, "mobile_line_height": 1.3, "text_align": "left"}},
        {"style_type": "link-styles", "styles": {"color": "#49A0E7", "font_style": "normal", "font_weight": "normal", "text_decoration": "underline"}},
        {"style_type": "heading-1-styles", "styles": {"color": "#373F47", "font_family": "Helvetica", "font_size": 48, "font_style": "normal", "font_weight": "400", "letter_spacing": 0, "line_height": 1.1, "margin_bottom": 20, "mobile_font_size": 40, "mobile_line_height": 1.1, "text_align": "left"}},
        {"style_type": "heading-2-styles", "styles": {"color": "#373F47", "font_family": "Helvetica", "font_size": 32, "font_style": "normal", "font_weight": "700", "letter_spacing": 0, "line_height": 1.1, "margin_bottom": 0, "mobile_font_size": 22, "mobile_line_height": 1.1, "text_align": "center"}},
        {"style_type": "heading-3-styles", "styles": {"color": "#373F47", "font_family": "Helvetica", "font_size": 24, "font_style": "normal", "font_weight": "700", "letter_spacing": 0, "line_height": 1.1, "margin_bottom": 12, "mobile_font_size": 18, "mobile_line_height": 1.1, "text_align": "left"}},
        {"style_type": "heading-4-styles", "styles": {"color": "#373F47", "font_family": "Helvetica", "font_size": 20, "font_style": "normal", "font_weight": "700", "letter_spacing": 0, "line_height": 1.1, "margin_bottom": 9, "mobile_font_size": 16, "mobile_line_height": 1.1, "text_align": "left"}},
        {"style_type": "mobile-styles", "properties": {}, "styles": {"mobile_margin": 0, "mobile_padding_bottom": 0, "mobile_padding_left": 0, "mobile_padding_right": 0, "mobile_padding_top": 0}},  # mobile_margin 0 = full-bleed on mobile (else a 10px white canvas gutter shows down both sides on any non-white design)
    ]

def main():
    if len(sys.argv) < 2: sys.exit("usage: build_def.py spec.json > payload.json")
    if sys.argv[1] in ("-h", "--help"): print(__doc__.strip()); sys.exit(0)
    path = sys.argv[1]
    if not os.path.exists(path): sys.exit("ERROR: spec not found: %s" % path)
    try:
        spec = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit("ERROR: bad JSON in %s: %s" % (path, e))
    blocks = spec.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        sys.exit("ERROR: spec has no 'blocks' (expected a non-empty list).")
    for i, b in enumerate(blocks):
        t = b.get("type")
        if t not in BUILDERS:
            sys.exit("ERROR: block %d: unknown type %r (image|text|button)." % (i, t))
        miss = [k for k in REQUIRED[t] if b.get(k) in (None, "")]
        if miss:
            sys.exit("ERROR: block %d (%s): missing %s." % (i, t, ", ".join(miss)))
    no_bg = sum(1 for b in blocks if b.get("type") in ("image", "text") and not b.get("bg"))
    if no_bg:
        sys.stderr.write("note: %d image/text block(s) have no 'bg' (no dark-opt theming; "
                         "white may show through on a colored design).\n" % no_bg)
    no_href = sum(1 for b in blocks if b.get("type") == "button" and not b.get("href"))
    if no_href:
        sys.stderr.write("warning: %d button(s) have no 'href' -- every CTA must be linked.\n" % no_href)
    no_alt = sum(1 for b in blocks if b.get("type") == "image" and not b.get("alt"))
    if no_alt:
        sys.stderr.write("note: %d image(s) have no 'alt' (set alt text, or \"Loading...\" if decorative).\n" % no_alt)
    width = spec.get("width", 600)
    # HARD RULE (Ari): template + content background are ALWAYS white. The design's real
    # base tint (even an off-white like #f9f5f2, or a dark color) is supplied by each text
    # block's block_background_color + the full-width slices, NEVER by the canvas. The spec's
    # background_color / content_background_color are IGNORED on purpose so this can't regress.
    styles = default_styles("#FFFFFF")
    # apply heading / style overrides by style_type
    overrides = {}   # deep-merge per style_type so `headings` + `styles_override` keys both apply (no silent drop)
    for src in (spec.get("headings", {}), spec.get("styles_override", {})):
        for st, vals in src.items():
            overrides.setdefault(st, {}).update(vals)
    for sd in styles:
        if sd["style_type"] in overrides:
            sd["styles"].update(overrides[sd["style_type"]])
        # HARD RULE: the content background is ALWAYS white; an override cannot defeat it.
        if sd["style_type"] == "base-styles":
            sd["styles"]["content_background_color"] = "#FFFFFF"
        coerce_ints(sd["styles"])  # a fractional override (e.g. line via letter_spacing) would 400
    sections = [section(BUILDERS[b["type"]](b)) for b in blocks]
    body = {"properties": {"css_class": "root-container"},
            "styles": {"background_color": "#FFFFFF", "width": width},  # HARD RULE: always white canvas
            "sections": sections}
    defn = {"body": body, "styles": styles}
    target = spec.get("target", {"mode": "create"})
    attrs = {"definition": defn}
    if target.get("mode") == "create":
        attrs["name"] = spec.get("name", "ari-test-template")
        attrs["editor_type"] = "SYSTEM_DRAGGABLE"
        payload = {"data": {"type": "template", "attributes": attrs}}
    else:
        payload = {"data": {"type": "template", "id": target.get("id"), "attributes": attrs}}
    print(json.dumps(payload))

if __name__ == "__main__":
    main()
