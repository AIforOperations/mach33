# Translation prompt

The translator (subagent `translator`, or inline) receives: target language, the source
table (each string split into styled segments), the brand glossary, and any memory matches
for strings in this email. It returns the target table only.

## Prompt

> Translate the following text into natural and smooth **{LANGUAGE}**, the way real native
> speakers actually talk, staying true to the tone, style, and marketing intent of the
> original. This is NOT a word-for-word translation; it should read as if originally written
> in {LANGUAGE}. Be very careful with: **false friends, word order, definite and indefinite
> articles, gendered nouns, idiomatic expressions, compound words, cultural nuances, and
> conjugation and tense.**
>
> **Preserve the full meaning. Never drop or shorten meaning to make text fit.** The layout
> is fixed and the copy is fit to it separately (by re-breaking lines and adjusting size), so
> always return the COMPLETE meaning. If a segment is tight, prefer a shorter natural synonym
> that keeps the whole meaning; do not delete a clause (e.g. never turn "your 5% off is here"
> into "5% off").
>
> **Register:** use the register named in the glossary for this language (default: informal
> second person for DTC consumer brands). Polished and persuasive, not formal or stiff.
>
> **Never translate (copy verbatim):** coupon/discount codes, brand names, the glossary's
> locked product/SKU names, anything matching `{{ ... }}`, URLs, and bare numerals and `%`.
>
> **Reuse:** if a source string has an approved memory translation, use it exactly. Apply the
> glossary's product-name map exactly.
>
> **Locale typography:** apply {LANGUAGE} conventions — percent spacing with a NON-BREAKING
> space ("5 %" in de/nb/sv/da/fr and most European languages, so it cannot wrap before `%`),
> locale decimal/thousands separators (the numeral VALUE stays locked, only its formatting
> localizes), correct articles and gendered agreement, compounds, and quotation marks.
>
> **Footprint:** each segment has a `maxChars` budget from its box width. Stay within it
> WITHOUT losing meaning (shorter synonym / natural phrasing). If nothing natural fits, return
> the best full-meaning option and set `overflow:true` with a note so the builder can re-break
> or resize. Never exceed silently; never cut meaning.
>
> **Segments & emphasis:** keep the segment count and order, EXCEPT you may split a segment to
> isolate a locked token or an emphasized run. Set `emphasis:true` on each output segment that
> should carry the source's emphasis (color/bold/size) after any {LANGUAGE} word-order change;
> false on the rest (all false if the source had no emphasis; more than one may be true).
>
> **Output:** deterministic JSON only, one entry per source index; each segment is
> `{text, locked, emphasis}` (the builder lands the source's emphasis style on every
> `emphasis:true` segment after word-order changes):
> `{ "index": n, "segments": [ { "text": "...", "locked": false, "emphasis": false } ], "overflow": false, "note": null }`.
> No prose, no explanation.

## Notes for the orchestrator (not the translator)
- Source casing can differ from rendered text when a node has `textCase` TITLE/UPPER (e.g.
  "sind da" renders "Sind Da"). Translate casing-agnostic; the node's transform handles it.
- The replica's text is applied by traversal index (clone preserves order), not by matching
  source characters.
- The builder owns final fit: re-break across the design's existing lines, then resize font /
  spacing. Meaning is never cut to fit.
