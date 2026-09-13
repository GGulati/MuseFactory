---
name: develop
description: End-to-end feature development loop. Use when the user asks to develop, implement, or build a feature — trigger phrases include "/develop", "develop this", "implement", "build this feature". Runs orient → plan → dual-angle plan review (product + technical) → isolate → execute with TDD → debug → code review → finish/PR, with mandatory approval gates and verification throughout.
---

# Develop

## Purpose

Turn a rough feature idea into a merged PR through a disciplined, gated loop. Composes the [obra/superpowers](https://github.com/obra/superpowers) skills (MIT, © 2025 Jesse Vincent — installed separately, see the MuseFactory AGENTS.md) into one procedure: `brainstorming`, `writing-plans`, `using-git-worktrees`, `subagent-driven-development`, `test-driven-development`, `systematic-debugging`, `requesting-code-review`, `receiving-code-review`, `finishing-a-development-branch`, `dispatching-parallel-agents`. Approval gates keep the user in control; verification is mandatory at every step.

Procedure composed from the obra/superpowers skills (MIT, © 2025 Jesse Vincent), installed separately per the MuseFactory AGENTS.md.

## Workflow

### Phase 0 — Orient

Read the project's operating contract first (`AGENTS.md` or equivalent), source-of-truth docs, and current repo state (branch, test baseline, open issues). Check for project-local skills (e.g. `.agents/skills/`) and use them where they apply. Never ask the user a question the repo or contract can answer. Output: brief orientation note (stack, commands, constraints, relevant local skills).

### Phase 1 — Plan

One phase, one doc: the design and the task breakdown live together, not in separate documents. Start by following the `brainstorming` skill. This is deliberately collaborative, not a solo exercise: explore alternatives *with* the user as the design takes shape — especially product direction, game design (core loop, mechanics, feel, tuning targets), and architecture. Present the design in sections for validation as you go; do not batch every decision into one final review. For game projects, treat game-design calls as product decisions that need the user's taste: propose with reasoning, don't just decide. Then follow the `writing-plans` skill: break the design into bite-sized tasks, each with exact file paths, code sketches, and verification steps. The task breakdown must be decision-complete: an implementer must not need to choose file locations, interfaces, data flow, test scope, or migration strategy.

Save the plan as one HTML file to the project's `plans/` directory. It holds the full design — problem, goals, non-goals, requirements and success criteria, user/system flow, state model and persisted schema, failure handling and recovery, security and privacy, observability, rollout and rollback, test strategy, rejected alternatives with tradeoffs — followed by the task breakdown. Include mermaid diagrams for the core architecture (component structure, state model, key sequences/flows) and anything else that materially aids understanding — render them via the mermaid CDN so they display when the file is opened — plus diagrams wherever they clarify the plan itself (task dependencies, rollout sequencing, data flow). The HTML must read cleanly in both light and dark mode (`prefers-color-scheme`; never hard-code light-only colors).

While planning, flag genuine technical forks (two or more viable directions with real tradeoffs — e.g. state management, rendering strategy, data-model shape) instead of silently picking one: note the options and your recommendation, and let the user choose before the plan is finalized. Do not write code.

### Phase 2 — Plan review (two angles)

Spawn two independent reviewer subagents with fresh context — each gets only the plan doc and its review prompt, never your working history — in parallel when possible. Each reviewer returns severity-ranked findings (critical / major / minor) with task references, plus a verdict of approve or revise.

- Product review (prompt in `references/plan-review-product.md`): goal alignment, scope correctness, behavior/UX implications, testable success criteria, explicit non-goals.
- Technical review (prompt in `references/plan-review-technical.md`): architecture fit, interfaces and data flow, non-functional requirements (performance, scalability, reliability, security, observability), edge cases and failure modes, test strategy, migration and rollback.

Phases 1–2 are a mini loop (plan → review → revise → re-review) that repeats until the user approves. Re-attach the updated plan doc on every iteration that goes to the user, so approval is always given against the current doc. Any critical finding in either angle sends the plan back for revision; re-review the changed parts — but only when the revision is meaningful. A trivial wording fix or a single small accepted tweak does not need a fresh review round; use judgment and say what you skipped. After the user approves the plan, it is approved: never send it back for re-review unless the plan is later meaningfully revised. Reviewers must call out remaining forks explicitly: a major finding that is really a fork goes to the user for a decision even when reviewers lean one way — the plan is not approved until forks are resolved. When both angles are clean, approval gate 1: user approves the plan — attach the plan doc file to the approval message so the user opens the doc itself, never just a summary.

### Phase 3 — Isolate

Follow `using-git-worktrees`: new branch in a git worktree, run project setup, verify a green test baseline before writing any code.

### Phase 4 — Execute

Follow `subagent-driven-development`: one fresh subagent per task with the exact task brief; enforce `test-driven-development` (RED-GREEN-REFACTOR: failing test first, minimal code, watch it pass, commit). Two-stage review per task (spec compliance, then code quality). Fan independent tasks out with `dispatching-parallel-agents`.

### Phase 5 — Debug

On any failure, follow `systematic-debugging`: reproduce, root-cause, fix, verify. Never guess-and-patch.

### Phase 6 — Code review

Follow `requesting-code-review` on the full diff against the plan — it spawns a fresh-context reviewer subagent; never review your own diff in-session: severity-ranked findings, critical issues block progress. Handle user feedback per `receiving-code-review` (verify before implementing; push back with reasons when warranted).

### Phase 7 — Finish

Follow `finishing-a-development-branch`: full verification (tests, typecheck/build, browser checks where relevant), write a progress-log entry with a verification line, then present options: open PR, keep branch, or discard. Push and PR creation require explicit user approval. Clean up the worktree afterward.

## Operating Rules

1. Do not mutate plans or code while the user is still discussing decisions — wait for an explicit go.
2. Approval gates are mandatory: end of Phase 2 (plan), Phase 7 (push/PR). Never skip a gate.
3. Every task carries verification steps; every completion writes a progress entry with a verification line.
4. Follow the collaboration contract below: ask on product calls, game-design decisions, technical forks, and costly ambiguity — autopilot everything smaller.
5. User-owned scratchpads and notes are read-only unless the user asks for changes.
6. Child agents never push, merge, or delete branches.
7. Factory worker mode: when running as a factory worker (e.g. a `dev-factory` workflow agent) where subagent dispatch is unavailable, execute the subagent-driven phases inline instead of dispatching — Phase 4 follows the `executing-plans` skill step-by-step. Reviews are the exception: reviewers must always be fresh-context subagents, so the worker never reviews in-session. Phase 2 and Phase 6 return the plan/diff as a `needs-review` blocked item, and the review is run by a fresh agent outside the worker. Record the substitution wherever the plan records rulings.
8. Reviewers are always fresh-context subagents — plan reviewers (Phase 2), code reviewers (Phase 6), and any ad-hoc review pass. A reviewer receives only the artifact under review plus its review brief, never your session history. Never review your own work in-session.

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
- Plan doc (design + task breakdown) in the project's `plans/`.
- Progress-log entries with verification lines.
- PR opened only after explicit user approval.
