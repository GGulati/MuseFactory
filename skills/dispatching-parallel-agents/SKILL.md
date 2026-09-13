---
name: dispatching-parallel-agents
description: Fans out 2+ independent tasks to child agents working concurrently. Use when several tasks can proceed without shared state or ordering — dispatch independent work in parallel via subagents or a workflow's parallel() step, chain dependent tasks sequentially, and give every child a self-contained brief.
---

# Dispatching Parallel Agents

## Purpose

Trade your own context for theirs: dispatch independent tasks to child agents in parallel, then review and integrate. Independent tasks run concurrently; dependent tasks chain sequentially.

## Workflow

1. **Partition the work.** Group tasks by whether they share state or ordering:
   - **Independent** — different subsystems, different files, no ordering (e.g. three test files failing with unrelated root causes). These fan out.
   - **Dependent** — one task needs another's output, or agents would edit the same files. These chain sequentially, each receiving the prior result.
   When in doubt whether failures are related, investigate one together first — fixing one may fix others.
2. **Write a self-contained brief for each child.** A child inherits none of your context; paste everything it needs:
   - **Scope:** exactly one task, with file paths and test/command names.
   - **Background:** the relevant error output or spec, copied in full.
   - **Constraints:** what it must not touch ("do not edit files outside X", "do not push").
   - **Output:** exactly what to return (root cause + change summary, or the artifact).
   - **Approval gate:** children never push to GitHub or open PRs on their own — those steps come back to you for the user's approval. See `references/briefs.md` for a template.
3. **Dispatch.** Fan independent work out in one step:
   - Via subagents: spawn one child per independent task in the same turn (all dispatches in one message run concurrently; one per turn runs sequentially).
   - Via JS workflow orchestration: use `parallel(...)` for the independent set; use `pipeline(...)` (or chained `agent()` calls) for dependent work.
4. **Review and integrate.** For each returning child: read the summary, check whether children touched the same files (conflict risk), then run the full test suite and spot-check the changes — child agents can make systematic errors. Integrate what is good, send back what is not.

## Operating Rules

- One child = one independent problem domain. Never hand a child "fix everything."
- Independent tasks fan out; dependent tasks chain. Agents editing the same files or sharing resources are dependent.
- Children get the full brief up front — do not rely on follow-ups to supply missing context.
- No child pushes, opens PRs, merges, or deletes branches. Integration decisions stay with you and the user.
- Cap parallelism to what you can actually review: if you cannot review N summaries carefully, run fewer.
- When failures are related, exploratory, or require seeing the whole system, do not dispatch — investigate directly.

## Output Contract

- Each child's result: root cause, what changed (file:line or diff summary), and test outcome.
- Your integration step: full test suite green, no conflicting edits, one consolidated summary to the user.

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).
