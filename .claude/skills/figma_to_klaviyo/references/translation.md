# Translation: English design → faithful per-language replica

Build a REPLICA of an approved Figma email (or flow) with only the WORDS changed, one
replica per target language, named `<source name> - <Language>`. Translation happens at
the Figma TEXT layer, so copy that later becomes an image slice is translated before the
pipeline bakes it. The English source is NEVER mutated (only the clone is edited; the figma
guard blocks deletion). Each replica then runs through the normal Figma→Klaviyo pipeline,
one template per language.

Languages are an input (the user names them, or read them from the brand's Klaviyo
markets/locales when connected). **Preconditions (check BEFORE a run):**
- **Script:** this method retexts an LTR clone in place. For an RTL language (Arabic,
  Hebrew) or a complex-shaping / CJK script, STOP and flag — direction and shaping are not
  handled. The supported set is Latin-script European languages.
- **Glyph coverage:** confirm the design's fonts (e.g. Sofia Sans, Roboto, Bebas Neue) carry
  the target language's glyphs (umlauts, ø/å, accents) before translating; if a glyph is
  missing, flag it (a substitute font or design change is needed), and re-check in verify.

## Hard principles (do not regress)
- **Meaning is preserved IN FULL. Never drop or alter meaning to make copy fit.** The
  layout (box geometry + position) is fixed; fit full-meaning copy to it by, in order:
  (1) a more concise NATURAL phrasing, (2) re-distributing words across the SAME line
  breaks, (3) font-size / line-height / letter-spacing / full-width use. Cutting a clause
  to fit (e.g. "Your 5% Off Is Here" → "5% off") is a fidelity BUG. Worked example: keep
  "is here" by re-breaking the hero as "Her er din / 5 % rabatt" (Here is your / 5%
  discount), not by deleting it.
- **Natural, native, conversational** target copy, never word-for-word. The translator runs
  the prompt in `translation/prompt.md` (careful with false friends, word order, articles,
  gendered nouns, idioms, compound words, cultural nuance, conjugation/tense).
- **Never translate:** coupon/discount codes, brand names, glossary-locked product/SKU
  names, `{{ merge_tags }}`, URLs, and bare numerals and `%` (keep the VALUE; locale number
  FORMATTING below still applies).
- **Locale typography:** apply the target locale's conventions — percent spacing with a
  NON-BREAKING space ("5 %" in de/nb/sv/da/fr, so it can't wrap before `%`), locale
  decimal/thousands separators (e.g. "1,000" → "1.000" in de) even though the numeral value
  is locked, correct articles + gendered agreement, compounds, quotation marks.

## Where things live (per brand; designed to not bloat)
- `translation/prompt.md` — the translator prompt. Loaded every run.
- `translation/glossaries/<brand>.json` — small, curated, durable: locked tokens,
  product-name map + policy, register per language, `memorize_only` tags. Loaded every run.
- `translation/memory/<brand>/<lang>.jsonl` — append-only source→target pairs, one JSON per
  line, keyed by source string. **QUERIED per email, never loaded whole** — pass only the
  current email's matches to the translator. Normalize on lookup (trim, collapse spaces,
  straighten curly quotes, case-fold) so a near-identical source still hits; on append, a
  newer pair supersedes an older one for the same key. Memorize ONLY reusable strings (cta,
  eyebrow, heading, tagline, badge, code_line, footer_badge); skip one-off body paragraphs
  (they do not recur, so they bloat memory with no consistency gain). Per-brand files keep
  context bounded by the email, not the corpus. **Precedence:** the glossary product-name
  map WINS over a memory pair if they disagree (the glossary is the curated source of truth).

## Process (per language)
1. **Map the source.** `get_metadata` + a read-only `use_figma` dump of every text node's
   styled segments, traversing with **`source.findAll(n => n.type === 'TEXT')`** (the SAME
   call/order that step 5 uses on the clone, so the table index and the retext index line
   up): `{id, characters, inInstance, segs:[{ch, hex, fam, sty, sz}]}` via
   `getStyledTextSegments(['fills','fontName','fontSize'])`. This is the source table; note
   which runs are emphasized (red/bold/size) and which tokens are locked. Record the count.
2. **Translate.** Load the glossary; look up this email's source strings in memory and pass
   the matches (with each node's `maxChars` budget when known). Run the `translator` subagent
   (prompt + glossary + matches + target language), or translate inline applying `prompt.md`.
   Output: the target table, segment-aware — each segment `{text, locked, emphasis}`, segment
   count/order preserved (a segment may split ONLY to isolate a locked token or an emphasized
   run), `overflow` flagged. The builder reads the emphasis STYLE (color/size/weight) from the
   step-1 source table and applies it to every `emphasis:true` output segment.
3. **Find empty canvas (CRITICAL — measure the PAGE, not a section).** Walk up to the PAGE
   node; read EVERY top-level node's `absoluteBoundingBox`; compute the global occupied
   rect. Reserve a zone BEYOND it: default below (`y = maxY + 1500`) or right
   (`x = maxX + 1500`). NEVER append into or grow an existing section — that pushes the
   replica into neighbouring designs on a dense canvas.
4. **Clone + place.** `src.clone()`, then append the clone to the **PAGE** immediately
   (`page.appendChild(clone)`) so it leaves any auto-layout parent — a clone left inside an
   auto-layout frame reflows that frame and SHIFTS the English source. Position in the
   reserved zone; rename `<source name> - <Language>`. If the file is VIEW-ONLY (the
   `clone`/`use_figma` write fails), STOP and flag it — same as the export recipe; never fake
   a replica. **Overlap
   guard:** AABB-test the clone's absolute box
   against every top-level node; if it intersects any, push further out and re-test, so
   overlap is impossible by construction. (Whole FLOW: a flow is a wrapping SECTION with N
   child email frames — clone the section; loose frames → clone each. Stack languages in
   the reserved zone. Long term these can be slotted into per-locale rows.)
5. **Retext by index.** `clone.findAll(n => n.type === 'TEXT')` is in the SAME order as the
   step-1 source dump → apply the target table by INDEX (robust; char-matching breaks on
   duplicate strings / curly apostrophes). **First ASSERT the clone's TEXT count equals the
   source table length** — if they differ (the clone added/dropped a node, an instance
   swapped), STOP; mapping by index would scramble the copy. Canonical text-edit recipe:
   load each run's font → set `.characters` →
   for mixed-run nodes re-apply per range `setRangeFontName` + `setRangeFontSize` +
   `setRangeFills` (uniform nodes keep their single style automatically). CTAs are component
   INSTANCES; edit ONLY the instance's text override, NEVER the shared main component (that
   would mutate the English source's instances too). If any index fails to apply, report
   which and do NOT hand the replica to the pipeline — a half-translated replica looks
   complete and would ship mixed-language copy.
6. **Fit, don't cut.** If a box overflows (height grew, wrapped, or a fixed box clips):
   re-break across existing lines, pick a shorter synonym that keeps meaning, or shrink that
   node's font/spacing. NEVER drop meaning. Build known-tight elements overflow-aware from
   the start (display heroes, circular badges, fixed-width chips, inline multi-column rows).
7. **Verify.** `get_screenshot` the replica; compare to source for fidelity — emphasis
   colors land on the right words, design line breaks hold, no overflow, no clipped badge.
   Also confirm **no source-language text remains** (a missed node ships mixed-language copy)
   and **no missing-glyph boxes** (the font lacks a target character — see preconditions).
   Fix and re-verify.
8. **Record.** Append new approved REUSABLE pairs to `memory/<brand>/<lang>.jsonl`; add any
   new product-name decisions to the glossary (Mach33 team verifies product/brand calls).

## Edge cases surfaced on real runs
- **Flattened / screenshot emails have NO live text** (findAll(TEXT) == 0) and cannot be
  translated by this method. Flag and route back to design for a layered source.
- **`textCase` TITLE/UPPER** makes rendered casing differ from the table string ("sind da"
  renders "Sind Da") — translate casing-agnostic; the node transform handles display.
- **Auto-layout heroes** grow when text wraps and push siblings (a too-tall hero shoved the
  subhead onto the product photo) — keep the design's line count.

## Hand-off to the Figma→Klaviyo pipeline
Each replica frame URL is a normal pipeline input → one verified template per language.
Slice reuse (optional optimization): run English once to fix the block plan (`spec.json`:
crop geometry + TEXT/IMAGE/BUTTON classification + dark treatment); per language reuse the
crop boxes + classification, swap live-text `content` → translated HTML, translate `alt`.
**Text-free image slices (photos, graphics with NO baked words) are identical across
languages — reuse the English `asset_id` + `src` verbatim, ZERO re-upload.** Only slices
with BAKED TEXT get re-exported from the language frame and re-uploaded. This keeps a
many-language run well under the daily upload cap (re-uploading every slice per language is
the trap).

## use_figma notes
Load `skill://figma/figma-use/SKILL.md` first; pass `skillNames:"resource:figma-use"`.
A multi-mutation plugin script does NOT roll back on a mid-script throw, so do not assume
atomicity: wrap each node edit in its own try/catch (partial success commits, failures
report by index), and any script that MUTATES the source first (none should here, but the
clone is created from it) must RESTORE on throw. Colors are 0–1. Return all created/mutated
node ids.
