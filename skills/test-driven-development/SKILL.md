---
name: test-driven-development
description: Use when implementing any feature or bugfix, before writing implementation code. Enforces red-green-refactor: write a failing test, run it and confirm it fails for the right reason, then write minimal code to pass.
---

# Test-Driven Development

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).

## Purpose

Write the test first. Watch it fail. Write minimal code to pass. If you did not watch the test fail, you do not know it tests the right thing.

**Iron law: no production code without a failing test first.** Code written before the test is deleted and re-implemented fresh from tests — never kept as "reference" or "adapted."

## Workflow

1. **RED — write one failing test.** One behavior, clear name, real code (no mocks unless unavoidable). Before writing the body, name the production change that would make this test fail. If you cannot name one, redesign around an observable behavior. See [references/test-rules.md](references/test-rules.md) for the full test-quality rules.
2. **Verify RED — watch it fail.** Run the test command via `muse.exec` (e.g. `npm test path/to/test.test.ts`) and read the output. Confirm: the test **fails** (does not error), the failure message is the expected one, and it fails because the feature is missing — not because of a typo. If it passes, you are testing existing behavior: fix the test. If it errors, fix the error and re-run until it fails correctly.
3. **GREEN — minimal code.** Write the simplest code that passes the test. No extra features, no "while I'm here" refactors.
4. **Verify GREEN — watch it pass.** Re-run via `muse.exec`. Confirm: the new test passes, all other tests still pass, and output is pristine (no errors, warnings).
5. **REFACTOR — clean up.** Only after green: remove duplication, improve names, extract helpers. Keep tests green. Do not add behavior.
6. **Repeat** for the next behavior.

**Exceptions (need an explicit user OK):** throwaway prototypes, generated code, config files.

## Operating Rules

- Thinking "skip TDD just this once" is rationalization. Do not skip it.
- Assert on real behavior, never on mock behavior. Derive expectations by hand (literals, hand-checked fixtures) — never compute expected values with the code under test.
- No change detectors: if a test can fail only through an intentional decision (constant value, exact wording, private structure), test the behavior that depends on the decision instead.
- Bug found? Write a failing test reproducing it first, then run the TDD cycle. Never fix bugs without a test.
- Before marking work complete, run the mutation check: mentally mutate the production code (wrong constant, wrong branch, missing side effect, empty return, missing validation) — at least one test should fail for each realistic mutation. A mutation nothing catches marks a behavior as unprotected.
- Test-first answers "what should this do?"; tests written after are biased by the code you already wrote. That is why the order is mandatory.

## Output Contract

A TDD-compliant change delivers:

- **Tests** for every new function/method, each verified to fail before its implementation existed, committed alongside the code.
- **A green run** — full suite output with no errors or warnings (paste the command output summary in your report).
- **Confirmation** that each failing-then-passing test failed for the expected reason (feature missing, not typo), and that mock usage was unavoidable where used.

Red flags that mean stop and restart the cycle: code before test, test added "later," test passes immediately, "already manually tested," keeping pre-written code as reference.
