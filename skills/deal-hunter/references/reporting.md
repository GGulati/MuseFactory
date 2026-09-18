# Reporting

## Silence rule

Deal scans stay silent unless something was actually found: a genuinely new qualifying item, a meaningful price drop, or a restock. Never send "nothing new" messages. A quiet watch is a working watch.

## Find format

Every reported find carries exactly these, no fluff:

1. The actual item or sale page URL (never news, articles, lookbooks, or category pages).
2. Current price vs. original price (and the discount depth).
3. Exact size confirmed in stock, matched to the profile.
4. Fabric composition / construction details.
5. One honest caveat (fit quirk, final-sale, shipping cost, limited size run, quality concern, etc.).

For shirts, sleeve length (long vs. short) belongs in the headline facts, not the caveat.

## Dedup / watermarks

- Each watch keeps a watermark file (e.g. `<watch>_seen.json`) recording every reported find: URL, price, size, date.
- Never repeat a watermarked item without a material price or stock change.
- Check legacy watermark files too when they exist — duplicates across old and new watches are still duplicates.
- Cap reports at roughly 10 items per scan; prefer the strongest matches.

## Marketplace conventions

- Explicit distance radius and recency window per user (e.g. 30 miles, ≤3 days old).
- Condition stated on every listing; new/like-new flagged first.
- Archive/secondhand finds must be clearly labeled when the profile normally excludes used.

## Suggestion boundaries

- Suggest new sources or watches only after vetting: legitimacy, real sale cadence, shipping to the user's region.
- Never invent proactive standing watches from adjacent interests — a declined suggestion is recorded as a standing "never suggest this" preference and honored permanently.
- Proactive moves are welcome only when they extend a watch the user already runs.
