---
name: requesting-code-review
description: Use after completing a task, a major feature, or before merging to get an independent review. Spawns a reviewer subagent with a self-contained review brief, severity-ranked findings, and blocks progress on critical issues until they are fixed.
---

# Requesting Code Review

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).

## Purpose

Dispatch an independent reviewer subagent to catch issues before they cascade. The reviewer gets precisely crafted context — description, requirements, and diff — never your session's history.

## Workflow

1. **Define the review scope.** Capture:
   - **Description:** brief summary of what was built.
   - **Requirements:** what it should do (plan file path, task text, or acceptance criteria).
   - **Scope:** a git range (`BASE_SHA`..`HEAD_SHA` via `git rev-parse`) or, for uncommitted work, the list of changed file paths.
2. **Spawn the reviewer subagent.** Give it a self-contained brief built from [references/reviewer-brief.md](references/reviewer-brief.md) with your scope values filled in. Include this exact instruction: *the review is read-only — do not mutate the working tree, index, HEAD, or branch state; use `git show`/`git diff` to inspect.* The reviewer must do the review itself and must not spawn sub-reviewers.
3. **Require structured findings.** The brief instructs the reviewer to return strengths, severity-ranked issues (Critical / Important / Minor with file:line, what is wrong, why it matters, how to fix), recommendations, and a merge assessment (`Yes | No | With fixes`).
4. **Act on feedback:**
   - **Critical** (bugs, security issues, data-loss risks, broken functionality): fix immediately. **Blocked — do not proceed with any further work until Critical findings are resolved.**
   - **Important** (architecture problems, missing features, poor error handling, test gaps): fix before proceeding.
   - **Minor** (style, optimization, polish): note for later.
   - If the reviewer is wrong: push back with technical reasoning — show the code or tests that prove it.
5. **Re-verify.** After fixes, confirm tests pass (follow `test-driven-development` for any behavior change). For significant rework, re-run the reviewer on the new range.

## Operating Rules

- Request review **mandatorily**: after each task in subagent-driven development, after a major feature, and before merging. Also valuable: when stuck (fresh perspective), before refactoring (baseline check), after fixing a complex bug.
- Never skip review because "it's simple." Never ignore Critical issues. Never proceed with unfixed Important issues.
- Reviewer quality decays with diff size: if the change is large, review in stages and say so. A wall-of-noise review is a scope problem, not a reviewer problem.
- Calibrate severity by actual impact. Not everything is Critical — accurate praise and honest calibration build trust in the feedback loop.

## Output Contract

Each review produces (from the reviewer brief's report format):

- **Strengths** — what was done well, stated specifically.
- **Issues** — Critical / Important / Minor, each with file:line, the problem, why it matters, and a fix (where not obvious).
- **Recommendations** — quality, architecture, or process improvements.
- **Assessment** — `Ready to merge: Yes | No | With fixes` plus 1–2 sentences of technical reasoning.

The coordinator's duty: return **blocked** if any Critical finding is unresolved, or if the reviewer returned an unclear verdict — do not proceed downstream.
