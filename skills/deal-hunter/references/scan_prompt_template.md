# Scan Prompt Template

Each scheduled scan gets its own instruction file. That file is the source of truth for the job's criteria; the job reads the profile and source list at runtime. Copy this template per watch and fill the brackets.

```
You are running the [watch name] deal scan for [user]. Today is [date].

1. READ the shopping profile at [profile path] — sizes, price ceilings, fabric rules, brand map, exclusions. It is the single source of truth; never guess a rule it states.
2. READ the source list at [source list path] — vetted sites and why each suits the user.
3. CHECK these source categories:
   - Vetted retailer sale/clearance sections (from the source list).
   - Community signals: [e.g. r/goodyearwelt, r/frugalmalefashion] — new posts only, match profile rules.
   - Marketplace: within [distance] of [location], posted within [recency]; state condition; new/like-new first.
4. ELIGIBILITY — a find must:
   - Match an exact size in the profile (verify per brand; never default blindly).
   - Be at or under the profile's price ceiling for its category.
   - Pass all fabric/construction rules and brand exclusions (hard filters).
   - Be genuinely new, a meaningful price drop, or a restock — check the watermark file at [watermark path] and skip anything already reported without a material change.
5. REPORT at most [max, default 10] items in the reporting format. Stay silent — send nothing — if nothing qualifies.
6. NEVER link news, articles, lookbooks, or category pages. Link only actual item or sale pages.
```

Notes:
- The job's delivery target is the user (their chat or a notification surface), not a file — reports are messages, not documents.
- For shirts: state long- vs short-sleeve up front; proactively check long-sleeve variants when asked for "shirts."
- Marketplace listings must state condition; archive/secondhand finds must be clearly labeled as such.
- Price-watch jobs (single product URLs) use the same template with step 3 replaced by: check the item page for price, size availability, and restock against the last recorded value in the watermark file.
