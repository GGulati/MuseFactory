---
name: develop
description: End-to-end feature development loop. Use when the user asks to develop, implement, or build a feature — trigger phrases include "/develop", "develop this", "implement", "build this feature". Runs orient → brainstorm → plan → dual-angle plan review (product + technical) → isolate → execute with TDD → debug → code review → finish/PR, with mandatory approval gates and verification throughout.
---

# Develop

## Purpose

Turn a rough feature idea into a merged PR through a disciplined, gated loop. Composes the workspace dev-loop skills (`brainstorming`, `writing-plans`, `using-git-worktrees`, `subagent-driven-development`, `test-driven-development`, `systematic-debugging`, `requesting-code-review`, `receiving-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`) into one procedure. Approval gates keep the user in control; verification is mandatory at every step.

Procedure composed from workspace dev-loop skills adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).

## Workflow

### Phase 0 — Orient

Read the project's operating contract first (`AGENTS.md` or equivalent), source-of-truth docs, and current repo state (branch, test baseline, open issues). Check for project-local skills (e.g. `.agents/skills/`) and use them where they apply. Never ask the user a question the repo or contract can answer. Output: brief orientation note (stack, commands, constraints, relevant local skills).

### Phase 1 — Brainstorm

Follow the `brainstorming` skill. This phase is deliberately collaborative, not a solo exercise: explore alternatives *with* the user as the design takes shape — especially product direction, game design (core loop, mechanics, feel, tuning targets), and architecture. Present the design in sections for validation as you go; do not batch every decision into one final review. For game projects, treat game-design calls as product decisions that need the user's taste: propose with reasoning, don't just decide. Save the design doc to the project's `plans/` directory. Do not write code. Ends at approval gate 1: user approves the design.

### Phase 2 — Plan

Follow the `writing-plans` skill: break the approved design into bite-sized tasks, each with exact file paths, code sketches, and verification steps. The plan must be decision-complete: an implementer must not need to choose file locations, interfaces, data flow, test scope, or migration strategy. Save to `plans/`. While planning, flag genuine technical forks (two or more viable directions with real tradeoffs — e.g. state management, rendering strategy, data-model shape) instead of silently picking one: note the options and your recommendation, and let the user choose before the plan is finalized.

### Phase 3 — Plan review (two angles)

Run two independent reviewer passes over the plan, in parallel when possible. Each reviewer returns severity-ranked findings (critical / major / minor) with task references, plus a verdict of approve or revise.

- Product review (prompt in `references/plan-review-product.md`): goal alignment, scope correctness, behavior/UX implications, testable success criteria, explicit non-goals.
- Technical review (prompt in `references/plan-review-technical.md`): architecture fit, interfaces and data flow, non-functional requirements (performance, scalability, reliability, security, observability), edge cases and failure modes, test strategy, migration and rollback.

Any critical finding in either angle sends the plan back for revision; re-review the changed parts. Reviewers must call out remaining forks explicitly: a major finding that is really a fork goes to the user for a decision even when reviewers lean one way — the plan is not approved until forks are resolved. When both angles are clean, approval gate 2: user approves the plan.

### Phase 4 — Isolate

Follow `using-git-worktrees`: new branch in a git worktree, run project setup, verify a green test baseline before writing any code.

### Phase 5 — Execute

Follow `subagent-driven-development`: one fresh subagent per task with the exact task brief; enforce `test-driven-development` (RED-GREEN-REFACTOR: failing test first, minimal code, watch it pass, commit). Two-stage review per task (spec compliance, then code quality). Fan independent tasks out with `dispatching-parallel-agents`.

### Phase 6 — Debug

On any failure, follow `systematic-debugging`: reproduce, root-cause, fix, verify. Never guess-and-patch.

### Phase 7 — Code review

Follow `requesting-code-review` on the full diff against the plan: severity-ranked findings, critical issues block progress. Handle user feedback per `receiving-code-review` (verify before implementing; push back with reasons when warranted).

### Phase 8 — Finish

Follow `finishing-a-development-branch`: full verification (tests, typecheck/build, browser checks where relevant), write a progress-log entry with a verification line, then present options: open PR, keep branch, or discard. Push and PR creation require explicit user approval. Clean up the worktree afterward.

## Operating Rules

1. Do not mutate plans or code while the user is still discussing decisions — wait for an explicit go.
2. Approval gates are mandatory: end of Phase 1 (design), end of Phase 3 (plan), Phase 8 (push/PR). Never skip a gate.
3. Every task carries verification steps; every completion writes a progress entry with a verification line.
4. Follow the collaboration contract below: ask on product calls, game-design decisions, technical forks, and costly ambiguity — autopilot everything smaller.
5. User-owned scratchpads and notes are read-only unless the user asks for changes.
6. Child agents never push, merge, or delete branches.

## Collaboration contract

**Always ask the user:**
- Product direction or scope is at stake.
- Game-design decisions: mechanics, feel, difficulty, tuning — these need the user's taste.
- A genuine technical fork: two or more viable directions with meaningfully different tradeoffs.
- Ambiguity where a wrong guess wastes real work. Rule of thumb: if you'd bet wrong more than 1 time in 3, or the cost of being wrong exceeds the cost of asking — ask.

**Autopilot (decide, note it in the progress log, move on):**
- Naming, code style, file organization within the plan's bounds.
- Test placement, minor API shapes, small refactors.
- Library choice between near-equivalents; anything the plan already decided.

Questions go to the project's side chat and the loop resumes on the user's answer. In factory runs, workers return questions as blocked items instead of asking directly.

## Output Contract

- Branch with clean, reviewable commits.
- Design doc and plan doc in the project's `plans/`.
- Progress-log entries with verification lines.
- PR opened only after explicit user approval.
