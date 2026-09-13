---
name: subagent-driven-development
description: Executes an implementation plan by dispatching a fresh subagent per task, reviewing each task (spec compliance + code quality), and finishing with a whole-branch review. Use when you have a written plan with mostly independent tasks and can dispatch child agents in the current session.
---

# Subagent-Driven Development

## Purpose

Execute a plan with isolated, focused workers and hard review gates: fresh subagent per task, a two-verdict task review (spec compliance, then code quality) after each, a bounded fix loop, and a broad final review — all progress tracked in a ledger file so recovery survives context loss.

## Workflow

### Setup

1. Work in an isolated workspace — use the using-git-worktrees skill to create one or verify the existing one. Never start on main/master without explicit user consent.
2. Run this skill's `bin/sdd-workspace <plan-file>` to resolve the plan's artifact directory (task briefs, reports, review packages, ledger). Each plan owns one directory; never read or write another plan's.
3. Create the ledger at `<workspace>/progress.md` with the first line `# SDD ledger — plan: <plan file path>`. After any context loss, trust the ledger and `git log` over your own recollection. If the first line names your plan, tasks with a `Task <N>: complete` line are DONE — resume at the first task without one. A task whose last line is a fix round is mid-loop: resume the loop at the next round.
4. Read the plan once, note its context and Global Constraints. If it names a spec, read that too — the spec is the binding authority; plan conflicts resolve against it. Record BASE (`git rev-parse HEAD`) before dispatching Task 1.
5. Pre-flight conflict scan: for every pair of tasks sharing a file or interface, record what one produces against what the other consumes; for every task, check its own text agrees with itself (tests vs. code, files created vs. files touched). Write the table to the ledger and rule on every finding before execution begins.

### Model selection

Use the least capable model that can handle each role. Always specify the model explicitly in every dispatch — an omitted model silently inherits the most expensive one.

- Mechanical implementation (isolated functions, complete spec, 1-2 files): cheapest tier.
- Multi-file integration, debugging, pattern matching: mid tier.
- Design judgment, broad codebase understanding: most capable tier.
- Task reviewers: cheap-to-mid tier, scaled to the diff's size, complexity, and risk.
- Final whole-branch review: most capable tier.
- Fix-loop rounds 4-5: one tier above the implementer that got stuck.

### The task loop

**Batch small same-shape work:** several small independent same-kind edits (one-line fix repeated across files) go in ONE dispatch brief to a single subagent, reviewed as one unit. Reserve one-dispatch-per-task for work needing its own judgment, tests, or review surface.

Never dispatch multiple implementation subagents in parallel — they conflict. Never fix findings yourself in the controller session — your context stays clean and controller fixes skip review. Hand artifacts over as files, never pasted: everything pasted into a dispatch or printed back stays in your context all session.

1. **Dispatch the implementer** (template: `references/implementer-prompt.md`). First run this skill's `bin/task-brief <plan-file> <N>` to extract the task text to a file; the dispatch carries (1) one line on where the task fits, (2) the brief path as the requirements ("read this first — exact values to use verbatim"), (3) interfaces and decisions from earlier tasks the brief can't know, (4) your resolution of any ambiguity, (5) the report-file path (`task-N-report.md` next to the brief) and the report contract. Exact values appear only in the brief — never make a subagent read the whole plan. The dispatch carries the no-subagents contract: the implementer never spawns subagents, especially not reviewers. Record the implementer's identity for fix-round resumes.
2. **Handle the report** — DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED:
   - DONE: build the review package (`bin/review-package <plan-file> <BASE> <HEAD>`, printed path) and dispatch the task reviewer. BASE is the commit recorded before dispatching — never `HEAD~1`, which silently truncates multi-commit tasks.
   - DONE_WITH_CONCERNS: read the concerns first; correctness/scope concerns get resolved before review, observations get noted and you proceed.
   - NEEDS_CONTEXT: provide the missing context, re-dispatch.
   - BLOCKED: if it's a context problem, provide more context and re-dispatch same model; if it needs more reasoning, a more capable model; if the task is too large, split it; if the plan is wrong, rule on the correction, ledger it, re-dispatch with the ruling. Never ignore an escalation or force a retry without changes. If the implementer asks questions, answer fully before it implements.
3. **Review the task** (template: `references/task-reviewer-prompt.md`). The reviewer gets three paths — brief, report, review package — plus the plan's Global Constraints copied verbatim as its attention lens (exact values, formats, component relationships; process rules already live in the template). Never dispatch a reviewer without a diff file. Both verdicts are required: spec compliance AND task quality. Implementer self-review never replaces the task review. Never pre-judge findings in the reviewer prompt — no "do not flag", "at most Minor", "the plan chose". ⚠️ "cannot verify from diff" items you confirm as real gaps enter the fix loop as failed spec reviews.
4. **The fix loop** (triggers on spec ❌, any Critical/Important finding, or a confirmed ⚠️ gap). Max 5 rounds; one round = one fix dispatch + one scoped re-review:
   - Minor findings never enter the loop — ledger them as `Task <N>: minor (deferred): <one-liner>` and point the final review at that list.
   - A finding the plan's text mandates, or that conflicts with the plan, is yours to rule on: weigh it against the plan text, decide with the spec as binding authority, ledger the ruling before acting.
   - Rounds 1-3: resume the original implementer with the open findings verbatim. Rounds 4-5: fresh implementer on a more capable model with the brief, report path, and findings ("A prior implementer attempted this [N] times; you own it now"). Each round the implementer appends a fix report (changes, covering tests, command, output) and re-runs the covering tests.
   - **Re-review is scoped** (template: `references/re-review-prompt.md`): `bin/review-package <plan-file> <FIX_BASE> <HEAD>` where FIX_BASE is the head the previous review saw. The re-reviewer verdicts each finding ADDRESSED/NOT ADDRESSED and flags new breakage in the fix diff only. New Critical/Important breakage joins the open findings; out-of-scope observations go to the ledger as deferred minors — they never extend the loop.
   - After each round, ledger: `Task <N>: fix round <R>/5 (<X> addressed, <Y> open — <finding one-liners>; commits <a7>..<b7>)`.
   - **The breaker:** after round 5 with findings still open, stop dispatching and adjudicate each yourself: reviewer wrong/contestable or real-but-nothing-downstream-builds-on-it → park (`Task <N>: parked — <finding> — Ruling: <why the code stands>`); real and load-bearing → rule the smallest unblocking change, ledger `Task <N>: Ruling: <finding> — <what you decided and why>`, carry it into the next task's dispatch. Stop only when every path forward is a guess.
5. **Complete the task.** Ledger `Task <N>: complete (commits <base7>..<head7>, review clean)` or `Task <N>: complete (commits <base7>..<head7>, <K> parked)`. Never move on while open Critical/Important issues are neither fixed nor parked-with-ruling at the cap.

### Final review

Run `bin/review-package <plan-file> <MERGE_BASE> <HEAD>` (MERGE_BASE = the commit the branch started from, e.g. `git merge-base main HEAD`) and dispatch a final reviewer on the most capable tier using the task-reviewer template at branch scope, pointing it at the ledger's deferred-minor and parked lines to triage what must be fixed before merge. If it returns findings: dispatch ONE fix subagent with the complete findings list (not one fixer per finding), then exactly one scoped re-review over the fix range, then adjudicate residuals as in the breaker's rules. There is no second fix wave — residual load-bearing findings surface to the user at wrap-up.

### Finish

Before deleting anything, collect every ledger line containing `Ruling:` — preflight rulings, parked findings, breaker adjudications — into the final message under "Rulings I made", in order, each with what it costs if wrong. A ruling that dies with the workspace was a decision made in secret.

When the final review is clean, delete the plan's workspace (`rm -rf <workspace>`) — the git history is the record now. Leave sibling plan directories alone. Hand off to the finishing-a-development-branch skill.

## Operating Rules

- **Rulings, not stalls.** A running plan does not wait on the user. Conflicts, ambiguities, plan defects — you decide them; the spec is the binding authority, the plan is its argument, your judgment settles the rest. Record every decision in the ledger as `Ruling: <what you decided> — <why> — <what it costs if wrong>` and keep going. Only four things stop you: an irreversible/destructive operation; a security-sensitive action; a side effect outside the workspace that norms say you ask about first (merge, push to a shared branch, publish); a plan so broken every path forward is a guess. For those, stop and ask.
- The ledger is what survives context loss. Bookkeeping is not overhead — controllers without a ledger have re-dispatched entire completed task sequences.
- While waiting on dispatched workers, keep doing local work (ledger updates, packaging the next review, reading reports); child results arrive on their own. When genuinely idle, wait in bounded stretches and reconcile: list live children and chase any that finished without reporting.
- Narrate at most one short line between tool calls — the ledger and tool results carry the record.
- Never start on main/master without explicit user consent. Never delete another plan's workspace.

## Output Contract

All tasks complete or parked-with-ruling, ledger closed out, workspace deleted after a clean final review, and a final message listing every ruling made. Use `references/implementer-prompt.md`, `references/task-reviewer-prompt.md`, and `references/re-review-prompt.md` for the three dispatch templates, and `bin/` for the workspace, brief-extraction, and review-packaging helpers.

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).
