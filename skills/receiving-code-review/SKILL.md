---
name: receiving-code-review
description: Use when receiving code review feedback — from a reviewer subagent, the user, or an external reviewer — before implementing any suggestion. Enforces verify-before-implement: technical evaluation, reasoned pushback, and one-at-a-time implementation, not performative agreement.
---

# Receiving Code Review

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).

## Purpose

Code review requires technical evaluation, not emotional performance. Verify each item against the codebase before implementing anything; push back with technical reasoning when the feedback is wrong; implement one item at a time, testing each.

## Workflow

1. **READ** the complete feedback without reacting.
2. **UNDERSTAND** — restate each item in your own words. If any item is unclear: **STOP and ask for clarification before implementing anything.** Partial understanding means wrong implementation; items may be related.
3. **VERIFY** each item against the codebase reality (see verification checklist below).
4. **EVALUATE** — for each item decide: accept, push back, or clarify. For "implement it properly" suggestions on unused code: grep for actual usage first — if nothing calls it, propose removal (YAGNI) rather than polishing it.
5. **RESPOND** — technical acknowledgment or reasoned pushback. No performative agreement ("Great point!", "You're absolutely right!"). Actions speak: state the fix, then make it. See [references/response-examples.md](references/response-examples.md) for good/bad phrasings.
6. **IMPLEMENT** — in this order: blocking issues (breaks, security) → simple fixes (typos, imports) → complex fixes (refactoring, logic). One item at a time; test each individually; verify no regressions.

### Verification checklist (per item, before implementing)

- Technically correct for THIS codebase and stack?
- Breaks existing functionality?
- Is there a reason for the current implementation (legacy, compatibility, a prior decision)?
- Works on all supported platforms/versions?
- Does the reviewer understand the full context?
- If you cannot verify it: say so explicitly — "I can't verify this without [X]. Should I [investigate / ask / proceed]?" — and do not implement it anyway.

## Operating Rules

- External feedback is treated skeptically but checked carefully — skepticism does not mean dismissal.
- If feedback conflicts with a prior decision the user made, stop and discuss with the user first.
- If you pushed back and verification proves you were wrong: state it factually ("You were right — I checked [X] and it does [Y]. Implementing now.") and move on. No long apologies.
- When replying to review threads (e.g. inline comments), reply in the thread, not as a top-level comment.
- YAGNI: never build a "professional" version of a feature nothing uses.

## Output Contract

After processing feedback, report per item:

- **Accepted** — `[item]: fixed. [brief description of what changed, file:line]`
- **Pushing back** — `[item]: [technical reasoning], [evidence: code/tests proving current approach works]`
- **Need clarification** — `[item]: [specific question]` — and **blocked** on all implementation until the unclear items are resolved.

Then the verification summary: each implemented fix tested individually, full suite still green, no regressions introduced.
