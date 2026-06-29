# CLAUDE.md: Figma to Klaviyo (team orchestrator)

This project turns an approved Figma email design into a verified, mobile-first Klaviyo
template, via the `/figma_to_klaviyo` skill. This file is your standing guide for operating
it every session.

## First time on this machine?
If the skill's readiness check fails (no `python3` / `node` / Pillow, the guard does not block a
test call, or `klaviyo.py list` cannot find the key), this machine is not set up yet. Run the
one-time routine in **`SETUP.md`** (you execute it; the human only copies in the `.env` file and
completes any password prompts; there is **no GitHub login**, the repo is public). The working
folder is named `<person>-Figma-to-Klaviyo`. Once a machine is set up, skip this.

## To build a template
1. The user gives a **Figma email node link** (optionally a brand slug and a real CTA link;
   the template name is `<brand>_<template>_<lang>` e.g. `acme_welcome_en`, default CTA link `https://mach33media.com/`).
2. Invoke **`/figma_to_klaviyo`** with that link. The skill does the whole pipeline: read the
   design, classify each region (live text vs image slice vs native button), slice + compress,
   upload, build the Klaviyo `SYSTEM_DRAGGABLE` template, and verify the render at mobile (390)
   + desktop (600) + dark mode.
3. Output: a Klaviyo template id and a verified render. Give the user the id and editor link.

## Multi-language replicas
On request, the skill builds one template per language by cloning the Figma design and
translating only the words. See the skill's translation flow (`references/translation.md`).

## Standing rules (the skill enforces these, do not override)
- **No deletion in Figma, ever.** A guard hook blocks destructive calls; reversible writes are
  allowed and ALWAYS restored. If the guard self-test ever fails, stop all Figma writes and
  re-run `SETUP.md` (a broken guard is fail-open).
- **Reproduce the approved design exactly**: never change its colors; keep live text editable
  in the Klaviyo editor.
- Sign in to Claude Code with the **shared Claude account**; the Figma connection rides on it.
- The Klaviyo keys live in the `.env` at the repo root (given to each teammate separately, never
  committed; scripts read the FILE, not a shell variable). Besides the shared dummy `KLAVIYO_API_KEY`,
  the `.env` holds one client account per store (`KLAVIYO_STORE_<SLUG>_*`). **Push to a real store
  with `--store <slug>`; resolve the store (or STOP) before any upload — see the skill's Multi-store
  section. Real store keys CANNOT be rotated; never print or commit one** (scripts mask keys;
  `.gitignore` + `.githooks/pre-commit` are the backstop).
- Working files (slices, renders) go in `builds/<brand_slug>/` under the repo root, never a
  machine-specific path; for a real-store run the `<brand_slug>` IS the store slug. The default
  `KLAVIYO_API_KEY` is a DUMMY account (safe to rotate); the per-store keys are REAL and cannot be.

## Cross-platform (macOS + Windows)
Runs on both. Setup guarantees `python3`, `node`, and `git` on PATH (Windows gets a `python3`
shim). Use `python3 imaging.py dims` (not macOS `sips`); stop the local preview server by PID
(`kill` / `taskkill`), never `pkill`.

## Client-facing text
Anything a client reads (delivery notes, messages, emails): plain and direct. No em-dashes, no
AI filler words (leverage, seamless, robust, streamline, comprehensive, etc.).

## Where the detail lives
The full pipeline and rulebook are in the skill: `.claude/skills/figma_to_klaviyo/`
(`SKILL.md` + `references/`). Read those for the slicing, dark-mode, translation, and Klaviyo
specifics. Setup is `SETUP.md`. This file orients you; the skill does the work.
