# Klaviyo API + SYSTEM_DRAGGABLE schema

Validated against the dummy account (revision `2026-04-15`). Auth header on every request: `Authorization: Klaviyo-API-Key <pk_...>` + `revision: 2026-04-15` + `Accept: application/vnd.api+json`. `scripts/klaviyo.py` wraps all of this.

## Endpoints
- **Upload image (multipart):** `POST /api/image-upload`. Fields: `file` (binary), `name`, `hidden` (optional). Returns `data.id` (asset_id) + `data.attributes.image_url` (CDN url). 201 on success. (Multipart is `image-upload`, NOT `/api/images`, which is import-from-url/base64.)
- **Create template:** `POST /api/templates/` body `{data:{type:"template",attributes:{name, editor_type:"SYSTEM_DRAGGABLE", definition}}}`. 201 returns `data.id`.
- **Update template:** `PATCH /api/templates/{id}/` body `{data:{type:"template", id:"{id}", attributes:{definition}}}`. 200. Same editor URL.
- **Render template:** `POST /api/template-render/` body `{data:{type:"template",attributes:{id:"{id}", context:{...merge vars...}}}}` → `data.attributes.html`. Renders a SAVED template by id; do NOT send `definition`/`editor_type` (400). ~3/s.
- **List templates:** `GET /api/templates/?page[size]=10` (max 10 per page; paginate via `links.next` to scan more — `klaviyo.py list` returns only the first page). `GET /api/templates/{id}/` returns the full `definition` (useful to copy real block schemas).

## Limits / gotchas
- **Image WRITE limits: 3/s burst + 100/min + 100/DAY, and the daily bucket is PER-ENDPOINT.** `/api/image-upload` and `/api/images` have separate 100/day buckets (~200/day combined). Fixed daily window (resets at a fixed account time). GET endpoints aren't daily-capped. 5MB/file, JPEG/PNG/GIF, ≤600–1000px wide, <2000px tall.
  - Mitigation: every uploaded slice's CDN `image_url` is PERMANENT + reusable in unlimited templates/sends — re-sending, duplicating, or editing copy costs ZERO new uploads. So reuse manifest urls; `klaviyo.py upload` now skips a re-upload when the same (name + content-hash) is already in the manifest, so a re-run does not burn the cap. The two write endpoints have SEPARATE daily buckets (`/api/image-upload` vs `/api/images`) for ~2x combined headroom, but `klaviyo.py` only uses `/api/image-upload`; reach for `/api/images` (or ask Klaviyo support to raise the cap) only if you actually exhaust it. `klaviyo.py` retries a burst 429 but surfaces a daily-cap 429 (Retry-After > 30s) instead of futile retries.
  - Draggable image blocks require a Klaviyo `asset_id` AND a matching Klaviyo `src` — an external CDN `src` (Cloudinary/S3) is rejected, so you are locked to Klaviyo-hosted images.
- **No API compression.** The "Use compressed" UI setting does NOT apply to API uploads; compress before upload (see slicing_rules + imaging.py).
- Generated HTML clipping: keep under ~85KB (Klaviyo risk) / ~102KB (Gmail hard-clip). Fewer, well-chosen blocks beat many tiny ones.
- 1000-template cap per account; one private key per account.
- Free/dummy accounts append a "klaviyo" branding footer in the render (on white). Ignore; a paid account replaces it with the real unsubscribe footer.
- Duplicate upload names get a numeric suffix; read `data.attributes.name` back if you rely on names.
- Style numerics must be INTEGERS: `letter_spacing: 1.36` returns 400. Round (use `1`).

## Fonts (what actually renders in the SEND)
Klaviyo embeds the account's hosted fonts via `@import url(https://static-forms.klaviyo.com/fonts/api/v1/<ACCOUNT>/custom_fonts.css)` in the rendered HTML. To render a brand font in live text, set `font_family` to the EXACT hosted family name (curl that CSS to read the `@font-face` names — for this account it is `Poppins-Klaviyo-Hosted`); the generic name (`Poppins`) does NOT match and silently falls back to web-safe. The editor's "web based fonts" list (DM Sans, Inter…) previews in the editor but is NOT embedded in the send, so it falls back to web-safe — which is fine for live copy and is NOT a reason to slice text. Mach33 decision: do not upload fonts; accept the web-safe fallback and keep copy live.
- **Weighted live text (bold/italic) needs a font that actually carries the weight.** A NON-hosted font (e.g. the design's DM Sans) loads in the editor at a single weight, so `<b>` shows NO visible bold and the design's Light/Medium/SemiBold nuances vanish — `<b>` only renders bold once it falls back to web-safe in the real send. So do NOT lead the stack with the design's brand font just because it is the brand font, if it isn't hosted. LEAD with a font that has the weight: the HOSTED font (`'Poppins-Klaviyo-Hosted', …` carries 400 + 700 → `<b>` renders real bold in editor AND send) or a web-safe font (Arial/Helvetica bold is always available). Curl `custom_fonts.css` to confirm which weights the hosted font has. ALWAYS open the render and confirm bold/italic actually show — don't assume `<b>` worked.

## SYSTEM_DRAGGABLE `definition` schema
`definition = {body, styles}`. **Scrub every `id` / `data_id` / `template_id` recursively before create/patch** (keep `asset_id`). `build_def.py` builds clean definitions with no ids.

- `body = {properties:{css_class:"root-container"}, styles:{background_color, width:600}, sections:[...]}`
- Nesting: `section → rows → columns → blocks`.
  - section: `{content_type:"section", type:"section", data:{properties:{},display_options:{},styles:{}}, rows:[...]}`
  - row: `{data:{styles:{column_layout:"1-column-full-width"}}, columns:[...]}`
  - column: `{data:{}, blocks:[...]}`
- Block types:
  - **image:** `data.properties:{dynamic:false, alt_text, asset_id, href(null for a plain slice), src}`, `data.styles:{width:600, max_width:600, height}` (height = sliceHeight × 600 / sliceWidth).
  - **text:** `data.content` = HTML string; `data.styles:{block_background_color (REQUIRED on colored designs; the body bg does NOT color text sections), inner_padding_top/bottom/left/right}`. Drive base appearance (font, size, line-height, alignment) from the global `text-styles`/`heading-N-styles`, and the block bg/padding from `data.styles`. **Styling rule: the block must stay visually editable in the Klaviyo editor — it must not trip the "unsupported formatting" notice (which forces a Convert-to-HTML block, no visual editing).** Inline styling that survives this is allowed: `<b>`, `<i>`, `<br>`, `<span style="color:#hex">` (per-word color, incl. two-tone headings), and `text-align`. Use the global heading styles for heading font-SIZE so mobile scaling works (an inline font-size disables it).
  - **button:** `data.content` = label; `data.properties:{href}`; `data.styles:{background_color (pill fill), block_background_color, border_radius (~30), color (text), font_family, font_size, font_weight, font_style, letter_spacing, inner_padding_top/bottom/left/right (the pill's padding), mobile_stretch_content:true}`. `display_options:{}` = show everywhere (do NOT use `{show_on:"desktop"}`).
- **`block_background_color`** lives in each block's `data.styles` — the SAME key for image, text, and button blocks; it is the CSS color the inbox dark/light engine re-themes (the dark-opt lever; see `slicing_rules.md`). `build_def.py` sets it on all three block types from a spec `bg` / `block_bg` field. To set it on an EXISTING template: GET the template → write `block_background_color` onto each block's `data.styles` → scrub read-only ids (keep `asset_id`) → PATCH.
- `styles` = array of global style objects (build_def.py supplies these; override per design): `base-styles` (`content_background_color`, `margin_top:0`, `mobile_optimizations:true`), `text-styles`, `link-styles`, `heading-1-styles`..`heading-4-styles`, `mobile-styles`. Heading styles carry both `font_size` (desktop) and `mobile_font_size` (mobile-only; not valid per-block) → Klaviyo emits `h2{...}` + `@media(max-width:480px){h2{...!important}}`.

## Block-spec format (author this, feed to build_def.py)
```json
{
  "name": "ari-test-<slug>",
  "width": 600,
  "headings": {
    "heading-2-styles": {"color":"#0c2b3e","font_family":"'Poppins-Klaviyo-Hosted', Helvetica, Arial, sans-serif",
      "font_size":36,"mobile_font_size":24,"font_weight":"600","letter_spacing":2,
      "text_align":"center","line_height":1.15,"margin_bottom":0}
  },
  "styles_override": {
    "text-styles": {"color":"#000000","font_family":"'Poppins-Klaviyo-Hosted', Helvetica, Arial, sans-serif",
      "font_size":18,"mobile_font_size":16,"text_align":"center","line_height":1.55}
  },
  "blocks": [
    {"type":"image","asset_id":"0000000000","src":"https://.../x.jpeg","height":331,
      "alt":"Acme - Example Tagline","href":null,"bg":"#0973a1"},
    {"type":"text","content":"<h2>YOUR HEADLINE <span style=\"color:#198fbf\">IN TWO TONES</span></h2><p>Plain copy on the solid fill.</p>",
      "bg":"#e8f6ff","pad":[20,24,36,36]},
    {"type":"button","label":"SHOP NOW","href":"https://mach33media.com/",
      "fill":"#198fbf","color":"#ffffff","block_bg":"#e8f6ff","radius":30,
      "font_size":16,"font_family":"'Poppins-Klaviyo-Hosted', Helvetica, Arial, sans-serif","weight":"600",
      "letter_spacing":1,"pad":[14,48]}
  ],
  "target": {"mode":"create"}
}
```
- `target` = `{"mode":"create"}` or `{"mode":"patch","id":"<template_id>"}`.
- `pad` on text = `[top,bottom,left,right]`; on button = `[vertical, horizontal]`.
- `background_color`/`content_background_color` in the spec are IGNORED (build_def hard-codes the white canvas) — don't set them.
- Run: `python3 scripts/build_def.py spec.json > payload.json` then `python3 scripts/klaviyo.py create payload.json` (or `patch <id> payload.json`).
