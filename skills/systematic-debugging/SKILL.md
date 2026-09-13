---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes. Enforces root-cause-first debugging through four phases: investigate, pattern-match, hypothesize, then fix — no fixes without a root cause.
---

# Systematic Debugging

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).

## Purpose

Find the root cause before attempting fixes. Symptom fixes are failure. This skill runs in four sequential phases; you must complete each before proceeding to the next.

## Workflow

### Phase 1 — Root Cause Investigation (mandatory before any fix)

1. **Read error messages carefully.** Do not skip warnings. Read stack traces completely — line numbers, file paths, error codes often contain the exact solution.
2. **Reproduce consistently.** Trigger it reliably and note the exact steps. If it is not reproducible, gather more data — do not guess.
3. **Check recent changes.** `git diff`, recent commits, new dependencies, config or environment differences.
4. **Gather evidence at component boundaries.** For multi-component systems, add temporary diagnostic logging at each boundary: what data enters, what data exits, whether env/config propagates. Run once, find the failing component, then investigate only that component.
5. **Trace data flow backward.** If the error is deep in a call stack, follow [references/root-cause-tracing.md](references/root-cause-tracing.md): find the immediate cause, then ask "what called this with that value?" and keep tracing up until you reach the original trigger. Fix at the source, never at the symptom.

### Phase 2 — Pattern Analysis

1. Find similar working code in the same codebase.
2. Read any reference implementation completely — do not skim.
3. List every difference between working and broken, however small.
4. Map dependencies: config, environment, assumptions the code makes.

### Phase 3 — Hypothesis and Testing

1. State one clear hypothesis: "I think X is the root cause because Y."
2. Test with the smallest possible change, one variable at a time.
3. Confirmed → Phase 4. Disconfirmed → form a NEW hypothesis. Do not stack fixes.
4. If you do not understand something, say so and research or ask — do not pretend.

### Phase 4 — Implementation

1. Create a failing test reproducing the bug first (follow the `test-driven-development` skill).
2. Implement ONE fix addressing the root cause. No bundled refactoring or "while I'm here" changes.
3. Verify: test passes, nothing else broke, the original issue is actually resolved. Flaky-timing problems: replace arbitrary sleeps with condition polling per [references/condition-based-waiting.md](references/condition-based-waiting.md). Bugs caused by invalid data: add validation at every layer per [references/defense-in-depth.md](references/defense-in-depth.md).
4. If the fix does not work, count attempts. If < 3, return to Phase 1 with the new information. If ≥ 3 fixes have failed, **stop** — that pattern signals a wrong architecture, not a wrong hypothesis. Discuss fundamentals with the user before any further attempts.

## Operating Rules

- Under time pressure is exactly when this process is most required — systematic is faster than guess-and-check thrashing.
- Never propose "one more fix attempt" after 2+ failures without returning to Phase 1.
- Stop and question fundamentals when: each fix reveals new problems in different places, fixes require massive refactoring, or each fix creates new symptoms elsewhere.
- If investigation proves the issue is genuinely environmental, timing-dependent, or external: document what you investigated, implement appropriate handling (retry, timeout, clear error), and add monitoring — but 95% of "no root cause" cases are incomplete investigation.
- No fixes without a failing reproduction test.

## Output Contract

A debugging engagement returns:

- **Root cause:** the traced chain from symptom to original trigger (file:line chain, data flow).
- **Evidence:** reproduction steps, relevant error output/logs, the hypothesis that was confirmed.
- **Fix:** what changed at the source and why it fixes the cause rather than the symptom; the failing-then-passing test that proves it.
- **Verdict on process:** if 3+ fix attempts failed, a statement that the architecture is in question and a recommendation for next steps — not another fix.
