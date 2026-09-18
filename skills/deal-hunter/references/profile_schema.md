# Profile Schema

The shopping profile is the single source of truth for every scan. Store it as markdown in the user's goal/workspace directory. Scans read it at runtime; user corrections edit this file directly.

```yaml
# Sizes — exact; verify conversions per brand/last, never default blindly
tops: S            # e.g. S, M; note fit preferences (slim, regular)
pants: 28x32      # waist x inseam; note preference order (e.g. 28x32 over 28x30)
jackets: 36S      # suits/blazers; note short/regular/long
shoes: US 8 medium # note brand-specific variance, e.g. "8.5 in some lasts, UK 7-7.5 equivalents"

# Price ceilings by category (sale targets, not retail)
price_ceilings:
  casual_shirts: 25
  nice_shirts: 50
  casual_pants: 50
  nice_pants: 100
  blazers: 100
  suits: 250
# ...extend as needed; seek roughly 50-70% off typical retail

# Fabric / construction rules
fabric:
  natural_fiber_minimum: 95%      # e.g. "2% elastane acceptable"
  always_exclude: [corduroy, velvet]
  construction: [Goodyear-welted or equivalent, full-grain leather]  # for footwear

# Brand map — liked, excluded, and policy notes
brands:
  liked: [J.Crew, COS, Club Monaco]
  excluded: [Mango]               # fast fashion, weak house brands, celebrity labels
  policy_notes:
    - "Ralph Lauren: Purple Label/RLRL and RLX only; never Polo"
    - "Established/proven brands only"
    - "New merchandise on deep sale preferred; factory seconds acceptable for footwear"

# Category-specific rules
category_rules:
  footwear:
    targets: [brown boots, black combat boots]
    exclude_types: [chukkas, brogueing, loafers, derbies, oxfords, sneakers]
  runway:
    exclude_types: [sweatshirts, hoodies, sweat basics]

# Reporting preferences
report_format:
  max_items_per_scan: 10
  fields: [item/sale URL, current vs original price, exact size in stock, composition, one honest caveat]
  shirt_rule: "state long- vs short-sleeve up front"
  link_policy: "item or sale pages only — never news or articles"
```

Rules:
- Empty sections are fine; fill what the onboarding captures. Unknown fields are questions for the user, never guesses.
- Extend with user-specific sections as needed, but keep one canonical home per fact.
