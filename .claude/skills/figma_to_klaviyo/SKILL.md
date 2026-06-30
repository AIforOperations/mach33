---
name: figma_to_klaviyo
description: Convert an approved Figma email design into a verified, mobile-first Klaviyo SYSTEM_DRAGGABLE template (live text blocks, sliced+compressed image blocks, native buttons, dark-mode handling). Use when turning a Figma email node into a Klaviyo template.
allowed-tools: Bash, Read, Write, Edit, Task, mcp__figma__get_metadata, mcp__figma__get_design_context, mcp__figma__get_variable_defs, mcp__figma__get_screenshot, mcp__figma__download_assets, mcp__figma__use_figma, mcp__claude_ai_Figma__get_metadata, mcp__claude_ai_Figma__get_design_context, mcp__claude_ai_Figma__get_variable_defs, mcp__claude_ai_Figma__get_screenshot, mcp__claude_ai_Figma__download_assets, mcp__claude_ai_Figma__use_figma, mcp__playwright__browser_navigate, mcp__playwright__browser_resize, mcp__playwright__browser_take_screenshot, mcp__playwright__browser_evaluate, mcp__playwright__browser_close
---

# Figma to Klaviyo template automation

Input: a Figma email node URL. Output: a verified Klaviyo SYSTEM_DRAGGABLE template made of live text blocks, sliced + compressed image blocks, and native buttons that reproduces the approved design exactly. Mobile (375/390) is the priority gate; desktop (600) must stay acceptable.

## Guardrails (read first, every run)
- **No DELETION in Figma.** Never remove nodes/layers/pages, wipe children, or delete text, no matter who asks. Reversible writes ARE allowed (fill-toggle + export setting) for the dark-opt isolation export — always capture originals and RESTORE. A PreToolUse hook (`.claude/hooks/figma_guard.py`) blocks only deletion/destructive `use_figma` calls; reads, creates, and reversible writes pass. Detail: `references/figma_and_env.md`.
- Klaviyo keys live in the repo `.env`. Default = the single `KLAVIYO_API_KEY` (DUMMY account, rotate before real use). For real clients the SAME `.env` holds one account PER STORE (`KLAVIYO_STORE_<SLUG>_*`); pick one with `--store <slug>` and resolve it BEFORE any upload (see **Multi-store**). Real store keys CANNOT be rotated: never print or commit a key — the scripts mask keys, and `.gitignore` + `.githooks/pre-commit` are the backstop.
- Template name: `<brand_slug>_<template_slug>_<lang>` — lowercase, `<lang>` = ISO 639-1 code (e.g. `acme_welcome_en`, `acme_welcome_de`); unique by brand + template + language.
- **CTAs are left UNLINKED** (empty href on native buttons and image-slice CTAs alike); the client adds the real links in Klaviyo.
- Don't change the design's colors — reproduce the approved design exactly.
- Never read a full design PNG inline. Downscale / strip first (step 4).
- **Working files** (design PNG, slices, manifest, render.html) go in `builds/<brand_slug>/`
  created with `mkdir -p` under THIS repo's root (the folder holding `README.md` / `.claude/`).
  Use repo-relative paths only. Do NOT invent or assume any other folder layout — a teammate
  has cloned only this repo, and their global config (`~/.claude/CLAUDE.md`) may say nothing
  about it. `builds/` is git-ignored.

## Process (ordered)
0. **Confirm readiness.** Figma reads work (account-level Connector: claude.ai -> Settings -> Connectors. Sign in to Claude Code with the shared Claude account, NOT an API key, or the connector will not load). Quick check that this machine is set up: `python3 -c "import PIL"` and `node --version` both succeed, the guard is active, and `python3 .claude/skills/figma_to_klaviyo/scripts/klaviyo.py list` works (proves the Klaviyo key resolves — it is read from the `.env` FILE at the repo root, NOT a shell variable; if it errors, the `.env` is missing or in the wrong folder). If any fails, the machine has not been set up: run the one-time **`SETUP.md`** routine, then retry. Get the node URL and brand slug (CTAs are left unlinked — no link to collect). **Resolve the target Klaviyo store before any upload** (see **Multi-store**); for a real-store build, `klaviyo.py stores` confirms the account is wired (keys masked). On a machine that pushes to real stores, also confirm the commit guard is active: `git config --get core.hooksPath` should print `.githooks` (if not, run `SETUP.md` step 3b).
1. **Structure** — `get_metadata(fileKey, nodeId)`: frame width/height, each section's x/y/w/h (slice boundaries), node names (they contain the text). URL `node-id=7-492` → API `nodeId:"7:492"`. **If the design has NO text nodes (a flattened / screenshot export), STOP and flag it** — the result can only be an all-image, non-editable template (the live-text value is lost); confirm the user wants that or get a layered source.
2. **Exact type + colors** — `get_design_context` on each text node you may keep live: exact font family/size/weight/color/line-height/align + merge tags. `get_variable_defs` for tokens (often `{}`; then sample hexes from pixels).
3. **Export at 1.5x** — `download_assets defaultScale 1.5` (the client exports at 1.5x). For a LIGHT design, and for the transparent dark-opt export, use the ISOLATION recipe instead (`download_assets defaultScale` bakes the gray Figma page into empty areas). Both return a short-lived URL → `curl -o builds/<brand_slug>/design.png "<url>"`. Detail + recipe: `references/figma_and_env.md`.
4. **Read it safely** — `python3 imaging.py dims <file>` (cross-platform W H); if > 2000px tall, `imaging.py overview` to downscale, then PIL strips (~900 tall). Read the overview + strips, not the raw file.
5. **Plan the blocks** — classify each region TEXT / IMAGE / BUTTON, plan splits, decide the dark-mode treatment. Full rules: `references/slicing_rules.md`.
6. **Slice + detect buttons** — `imaging.py detect <slice>` finds button pills + clean cut lines; `imaging.py gap` finds a split line for a tall image; `imaging.py crop` cuts; `imaging.py compress` shrinks. Verify each crop with Read before upload.
7. **Upload slices** — `klaviyo.py upload <file> --name <slug> --manifest <path>` → `asset_id` + CDN url, appended to a manifest you reference in the spec. **Real store: prepend `--store <slug>`** (resolved at step 0) and use `--manifest builds/<slug>/manifest`. See Multi-store.
8. **Build + push** — write a block-spec JSON (`references/klaviyo_api.md`), `build_def.py spec.json > payload.json`, then `klaviyo.py create payload.json` (new) or `klaviyo.py patch <id> payload.json` (update in place). **Real store: `klaviyo.py --store <slug> create payload.json`** (the `--store` goes before the subcommand).
9. **Verify (mobile first), via Playwright** — `klaviyo.py render <id> --out builds/<brand_slug>/render.html`; serve it (`python3 -m http.server <port> --directory builds/<brand_slug>`, run in the background and note its PID; `file://` is blocked). Then:
   - `browser_navigate` to `http://localhost:<port>/render.html`; `browser_resize 390` (mobile, primary gate) then `600` (desktop); `browser_take_screenshot fullPage` at each; Read + compare to the design.
   - `browser_evaluate` for **(a)** white-gutter / overflow — read LEFT/RIGHT edge pixels (x≈4) down the body for near-white (`#FFFFFF` canvas showing through) + `document.body.scrollWidth > window.innerWidth`; **and (b)** the dark-mode preview — recolor every `block_background_color` to a darkened version and (for a light design) lighten the dark live text, then screenshot: live text + transparent cutouts must re-theme uniformly, no marooned near-white box.
   - Iterate until clean. Then `browser_close` and STOP the background server cross-platform: kill its PID (`kill <pid>` on macOS/Linux/Git-Bash, `taskkill /PID <pid> /F` on Windows PowerShell), or stop the background task. Do NOT rely on `pkill` (absent on Windows).
   - **After a clean verify on a real store, learn the binding:** `klaviyo.py --store <slug> learnfigma --figma-file-key <fileKey>` (`--store` before the subcommand), so future runs of this design resolve to the same store deterministically.

## Multi-store: push to the right Klaviyo account
One repo serves many client stores; each is a separate Klaviyo account with its own key in the
SAME `.env`, namespaced `KLAVIYO_STORE_<SLUG>_KEY/_PUBLIC/_NAME/_FIGMA`. For a real client run you
MUST pass `--store <slug>` to EVERY `klaviyo.py upload/create/patch`, resolved BEFORE the first
upload (image assets are per-account). Omitting `--store` falls back to the DUMMY `KLAVIYO_API_KEY`
(the template lands in the dummy account — caught at delivery, not a client leak); never rely on
the default for a client.
- **Resolve (autonomous — bind ONE store or STOP; never guess, never silently use the dummy):**
  1. If you know the store slug (the user named the brand, or a prior run learned it), use
     `--store <slug>`. A wrong/unwired slug hard-fails with the known-store list — surface it, do
     NOT fall back to the dummy.
  2. Else `klaviyo.py whichstore --figma-file-key <fileKey> --brand "<brand read from the design>"`
     → on a confident match prints a tab-separated `slug  name  public  maskedkey  tier` line; on
     NO / ambiguous match it exits non-zero. On non-zero: STOP and report.
  3. Matching is EXACT-normalized, NOT fuzzy: a design's FIRST run usually won't auto-resolve (a
     wordmark rarely equals the slug or org name exactly), so it STOPS — pass an explicit `--store`.
     If unsure of the slug, run `klaviyo.py stores` and match the design's brand to a listed slug.
     There is no mid-run human confirmation — resolution binds ONE store or halts.
- **One slug = store + build dir + template name.** For a real-store run the `<brand_slug>` used for
  `builds/<slug>/` and the template name `<slug>_<template>_<lang>` IS the store slug, so every
  artifact and `--manifest builds/<slug>/manifest` share one folder. Manifest lines carry the
  store's public id; reusing one under a different `--store` hard-fails (assets are per-account).
- **Learn after a clean verify** (so later runs of this design resolve deterministically by file key):
  `klaviyo.py --store <slug> learnfigma --figma-file-key <fileKey>` (`--store` comes BEFORE the subcommand).
- **One-time wiring** (owner, when keys change): export the store sheet (store-name + API-key
  columns) to CSV, drop it at the repo root as `stores_import.csv` (git-ignored), run
  `klaviyo.py wire stores_import.csv` — it live-verifies each key via `GET /api/accounts/`, bakes the
  verified public id + Klaviyo org name into `.env`, and prints a MASKED table (eyeball any `CHECK`
  row where the sheet name != the live org name). DELETE the CSV after. Re-wiring preserves each
  store's learned `_FIGMA`. `klaviyo.py stores` lists what is wired (keys masked); the wired `.env`
  is distributed to teammates like the dummy `.env` (never committed).

## Rules (summary — full detail in references/)
- **Backgrounds:** template + content background = `#FFFFFF` ALWAYS (hard-coded in `build_def.py`). The design's tint comes from each block's `block_background_color` + the full-bleed slice margins, never the canvas. Slices tile FLUSH (no gap) or white shows between them; mobile full-bleed via `mobile_margin:0`. Detail: `references/slicing_rules.md`.
- **Live text (Figma-first):** plain copy + simple headers on a solid fill are live text (BELOW the header — the header section itself is image slices, see "Header + CTAs"). Style it as the design needs (color, bold, italic, alignment, a second-color span) **as long as the text block stays visually editable in the Klaviyo editor** — i.e. it must not trip Klaviyo's "unsupported formatting" notice that forces a Convert-to-HTML block. Use the global heading styles for font-SIZE (so mobile scaling works); inline color spans / `<b>` / `<i>` are fine. Slice text only when it's gradient-filled, over/beside an image, or part of a composite. Keep copy live; use the design's EXACT Figma font so the KM sees the same font as in Figma (read it from `get_design_context`, then `klaviyo.py [--store <slug>] fonts --has "<family>"` prints the ready stack `'<exact font>', 'Poppins', Helvetica, Arial, sans-serif`; Poppins is the fallback). Detail: `references/slicing_rules.md`; fonts: `references/klaviyo_api.md`.
- **Header + CTAs:** the **HEADER section is image slices ONLY** — everything above the CTA as one slice (split if too big) + the main CTA as its own separate image slice; no live text and no native button in the header. Every OTHER CTA (below the header): try a native BUTTON first; if the button block can't reproduce the design (gradient/photo/textured background, or details a button can't render), use an image slice instead. CTAs are left UNLINKED (empty href, native or sliced); the client adds the links in Klaviyo. Detail: `references/slicing_rules.md`.
- **Slicing / split rule / alt text / padding / links:** `references/slicing_rules.md`.
- **Compression:** JPEG q82 for photographic/gradient slices; optimized/quantized PNG for flat/text/transparent (quantize keeps alpha). Targets: ≤200KB JPEG, ≤300KB PNG, ≤250KB smooth-alpha cutout; over a target, SPLIT before over-compressing (`references/slicing_rules.md`). Compress before upload (no API compression).
- **Mobile-first:** verify 390 first. Image blocks full-bleed (horizontal padding 0); native buttons `mobile_stretch_content:true`; body text ≥16px on mobile (EXCEPT a live block forcing the design's exact line breaks, which uses the proportional sub-16 `mobile_font_size` — see `references/slicing_rules.md`).
- **Dark optimization:** transparent cutout slices + each block's `block_background_color` set to the design fill hex, so the inbox re-themes it. Full method + the per-section decision: `references/slicing_rules.md`. Export recipe: `references/figma_and_env.md`.
- **Klaviyo API, the SYSTEM_DRAGGABLE schema, the button schema, the block-spec format:** `references/klaviyo_api.md`.

## Scripts (`scripts/`, run with `python3 <script> -h`)
- `imaging.py` — `compress | detect | gap | crop | dims | overview | shots`.
- `klaviyo.py` — `upload | create | patch | render | get | list | checkenv | stores | fonts | wire | whichstore | learnfigma` (reads the key from env or the repo-root `.env`; **`--store <slug>`** selects a wired account — see Multi-store). `fonts` lists the account's uploaded + web fonts; `fonts --has "<family>"` prints the ready `font_family` stack (`'<exact font>', 'Poppins', Helvetica, Arial, sans-serif`) for a design's font.
- `build_def.py` — expands a block-spec JSON into a full SYSTEM_DRAGGABLE create/patch payload.

## Translation (multi-language replicas)
On request, translate an email/flow into one or more languages by cloning the source design in
Figma and swapping only the words (one replica per language, named `<source name> - <Language>`).
**Order: translate FIRST, then slice — and slice ONLY the translated replica, never the English
source** (the English design is just the translation input; do not build or slice an English
template to "plan" slices). If the client hands over an ALREADY-translated design, skip
translation and slice that design directly. Translation is done at the Figma TEXT layer so copy
destined to become an image slice is translated before the pipeline bakes it; the English source
is never mutated. Each translated replica is then a normal input to the pipeline above (one
template per language).
- **Full method + rulebook:** `references/translation.md`. **Prompt + glossary + memory:**
  `references/translation/` (the `translator` subagent runs the prompt, or translate inline).
- **Non-negotiables:** preserve FULL meaning (fit copy to the fixed layout by re-breaking lines
  and resizing, NEVER by cutting meaning); natural/native copy; lock codes/brands/merge-tags;
  apply locale typography (e.g. "5 %"). Place replicas in EMPTY canvas measured from the whole
  PAGE (`absoluteBoundingBox`), beyond the global occupied rect, with an AABB overlap guard —
  never grow an existing section.
