---
name: "deal_hunter"
description: "Hunt clothing and shoe deals matched to a user's exact brands, sizes, price ceilings, and fabric rules. Builds a shopping profile (with a purchase-history or favorites on-ramp), suggests vetted sources, runs scheduled deal scans and single-item price watches, and reports only genuine finds. Use when someone asks to watch items or sales for deals, set up deal hunting, or get sale-scan recommendations."
---

# Deal Hunter

## Purpose

Turn a person's real shopping data into a quiet, accurate deal-hunting pipeline: profile → vetted sources → scheduled scans → reported finds only.

## Workflow

### 1. Onboard the profile

Follow `references/onboarding_script.md`. Capture sizes, price ceilings, fabric/fit rules, the brand map, and exclusions into the profile file. Use the **purchase-history on-ramp** (order history via saved retailer logins) or the **favorites on-ramp** (wishlists / saved lists) when the user offers them — both infer real sizes and paid-price bands. When neither exists, a minimum viable profile is sizes + price ceilings + one liked brand. Present the draft profile for correction; the user's corrections are the verdict — apply them instantly to the profile file, never patch copies.

### 2. Define the watches

One scheduled scan per category (e.g. footwear, menswear, designer/runway), each with its own source list and eligibility rules. Sources must be **vetted first**: legitimacy, real sale cadence, and shipping to the user's region. Never recommend an unvetted site. Optional: **single-item price watches** for specific product URLs — watched for drops, restocks, and size availability.

### 3. Schedule

Daily, early morning in the user's timezone (after typical overnight sale-launch windows), all scans synchronized. Notify **only on new qualifying finds, meaningful price drops, or restocks**. Never send "nothing new" messages.

### 4. Run a scan

Execute per `references/scan_prompt_template.md`. Check vetted sources, community signals (e.g. relevant subreddits), and marketplace listings with explicit distance/recency filters. Dedup against the watermark files. Enforce every profile rule silently; exclude fast fashion, weak house brands, and off-fiber items without noise.

### 5. Report

Per `references/reporting.md`: each find gets the item/sale URL, current vs. original price, exact size in stock, fabric composition, and one honest caveat — nothing else. Cap ~10 items per scan.

## Output Contract

- **Profile:** written to the user's goal/workspace directory, matching `references/profile_schema.md`. That file is the single source of truth; every scan reads it at runtime.
- **Scan job:** a scheduled job whose instruction file is the source of truth for that job's criteria.
- **Report:** only genuine finds in the reporting format, or silence.

## Auth

- Retailer logins use the platform's saved-login / secure-credential flows. Never ask for raw passwords, API keys, or codes in chat.
- Some retailers sign in by email code instead of password — support that flow when the user offers it.
- One-time sign-in codes: ask in chat when the site's flow needs them.

## Operating Rules

1. Profile corrections from the user apply instantly to the single source-of-truth file; never patch each copy.
2. Link only actual item or sale pages in reports — never news, articles, lookbooks, or category pages.
3. A rejected suggestion is recorded as a standing "never suggest this" preference and honored permanently.
4. Suggest new watches or sources only after vetting them; never invent proactive standing watches from adjacent interests.
5. Never repeat a watermarked find without a material price or stock change.
6. The profile's standing exclusions (brands, fabrics, quality tiers) are hard filters, not soft signals.
