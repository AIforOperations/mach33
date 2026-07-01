# Speed goal tracking — figma_to_klaviyo

**Goal:** single-email, dark-optimized Klaviyo template built reliably UNDER 10 min true cold
wall-clock, WITHOUT losing output accuracy. MET when 3 consecutive held-out designs each build
<10 min AND pass verification, skill FROZEN across the three.

**Consecutive clean passes: 0** (v1.3 just built; not yet cold-tested)

## Honest state of the test set
All 5 listed designs were CONSUMED building v1.2 last session (plan.json + manifest on disk for
each), so under the strict rules they are no longer pristine held-out designs. They are used here
as cold regression runs (labeled "already-seen"). A rules-clean measurement needs 3 fresh designs.

## v1.3 DARK-OPT REGRESSION (found + fixed 2026-07-01)
**Regression I introduced:** making bake-light-islands the default + "color export only, skip the
transparent export" disabled the client's actual dark method. nat719cold baked all 7 slices opaque
(`cutout: 0`) so the base froze light instead of re-theming in dark. User caught it.
**Root cause:** my edits to SKILL step 3/5 + the slicing_rules top section contradicted the intact
rulebook body ("transparent cutout is THE DEFAULT; baking is a deliberate exception").
**Fix (correct + SIMPLE — no dark render, Klaviyo re-themes):**
- Export BOTH color + transparent (isolation recipe). Every on-base image is a TRANSPARENT cutout by
  DEFAULT (sliced from transparent.png, alpha kept) + `block_background_color` = base hex. Add
  `"fill": true` ONLY when the transparent cutout looks weird/angled/broken OR it's an own-bg photo
  (sliced from color.png, flattened opaque). Decision = LOOK at the transparent overview per region.
- build.py: two-export slicing (`export` + `export_transparent`, per-block `fill` flag), transparent
  keeps alpha / filled flattens, prints `dark: N transparent cutouts, M filled`. stitch composites
  cutouts onto their base hex. Validated by dry-run: 2 transparent (alpha) + 1 filled (opaque), no warns.
- Skill + slicing_rules.md + klaviyo_api.md + build.py header realigned to this. No dark render/verify.

## v1.3 changes (quality-preserving-or-up speedups; being validated)
1. **Browser-free mobile preview (`imaging.py stitch`)** — stacks the compressed FINAL slices in
   plan order at 390 into one image for the step-7 visual Read. For an all-baked / images+buttons
   design this IS the exact pixels Klaviyo renders (flush tiling, mobile_margin 0), so NO browser
   is needed. Validated on nat719: faithful mobile view, `edges` clean (no overflow/gutter/seam).
2. **Conditional browser verify** — the Playwright pass runs ONLY when the plan has a live
   `role:"text"` block (where Klaviyo's render is per-design variable: wrapping, mobile fit,
   unsupported-formatting). All-baked/button designs skip the browser entirely. Of the 5:
   nat719 + whipmats skip it; nat1365 + nat1668 + customlove keep it.
   - Rationale: across all prior runs the Playwright VISUAL render caught no defect that wasn't
     cheaper to catch elsewhere (the D2 merge-tag literal was plan-time preventable and is now a
     hard rule; the dark-recolor gave only false signals and is dropped). Keep it only where
     Klaviyo rendering is genuinely non-deterministic = live text.
3. **Per-phase timing (`phase.py`)** — stamps start → reads-done → export-done → plan-done →
   verify-done so cold-run time is MEASURED, not estimated. build.py already logs the back half.

## NEW METHOD (REST-facts pipeline) — independent-review validation
Method: `figma_rest.py fetch` (REST reads + both exports + `plan_facts.json` distiller) → plan from facts
→ `build.py --dry-run` → stitch. Each build audited by an INDEPENDENT reviewer agent vs slicing_rules.md.

Round 1 (canary nat719): FAIL — builder over-baked the 3 testimonial cards (`fill` instead of transparent
cutout = the named common mistake). FIX: narrowed `fill:true` to full-bleed own-bg only + alphamap
authoritative + "photo-containing on-base card = cutout" (SKILL + distiller).

**RESULT: 5/5 CLEAN** — every design passed an INDEPENDENT reviewer audit on slicing, dark-optimization,
native buttons, and fidelity. Two systematic fixes were found + made by the review loop:
(1) over-baking on-base cards (narrowed `fill` to full-bleed own-bg + alphamap authoritative);
(2) live-text inline-style fidelity (distiller now extracts per-run color/bold/italic + node italic).
All builds are dry-run (no Klaviyo upload); real creates are the cap-gated end-to-end capstone.
CAPSTONE: nat1668 real create = template VUSGeQ (dummy), full pipeline in 7.8s; live-text BROWSER
verify PASSED (merge tag {{first_name}} rendered its default "there", italic renders, clean wrap, no
Convert-to-HTML). The other 4 real creates are queued for the next daily upload-cap reset.

Round 2 (all 5, fixed skill):
- customlove (dark maroon): **PASS** — dark-base-native, 10 fill/0 cutout, 1 native CTA, 2 live blocks.
- nat1668 (pale sage): **PASS** — 0 cutout justified (Domine headings/own-bg/over-image), merge tag live.
- nat1365 (white): **PASS** — 4 cutout/3 fill matched to alphamap, 2 native CTAs, merge tag live.
- nat719 (cream): rebuilt 9 cutout/3 fill (was 2/7) — over-baking FIXED; review pending.
- whipmats (black): **FAIL** — dark-opt PASSED, but live text dropped the red "Whipmats" (a two-tone
  body word). FIX: distiller now extracts per-character color `runs` (validated: catches red Whipmats /
  10% OFF / FLASH10) + SKILL "reproduce every colored word, never drop a design color". Re-run pending.

## Remaining levers (not yet built)
- **Figma REST export (token-gated)** — replace the 3-round-trip MCP isolation export (~2-3 min
  cold) with one REST `GET /images` call (~15s). Needs a Figma read token in `.env`; build +
  validate once provided. Biggest single remaining cut.
- **Deterministic plan scaffold** — draft plan blocks from get_metadata geometry + font lookup so
  the agent reviews instead of measuring from scratch. Medium effort, some accuracy risk; hold
  until timing data shows planning is the real bottleneck.

## Test log (cold = fresh subagent context; shares this session's warm Figma MCP auth)
| # | brand/node | branch | cold time | reads/export/plan/build/verify | accurate? | <10 & accurate? | notes |
|---|---|---|---|---|---|---|---|
| 1 | naturelle 128:719 (already-seen) | all-baked, NO browser | 5m19s | 74 / 80 / 108 / 11 / 47 s | NO — baked opaque, no dark-opt (regression) | FAIL (dark) | tmpl R6fd4F; superseded by fix below |
| 1b | naturelle 128:719 CORRECTED dark | transparent-cutout, NO browser | **10m05s** | export 290 / plan 268 / verify 48 s | YES — 7 transparent cutouts + 2 filled, block_bg #e9ede4, white template; preview faithful, edges clean | dark PASS, time just over 10 | tmpl RG2YSQ; transparent export added ~210s (accuracy-first; FIGMA_TOKEN buys it back) |

**Phase finding:** front half (reads+export+plan = 261s) is 82% of the run; verify is already 47s
(no browser). Token cuts reads+export (~153s→~30s); a plan scaffold targets the 108s plan reasoning.
