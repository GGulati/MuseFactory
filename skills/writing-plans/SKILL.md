---
name: writing-plans
description: Writes a detailed, bite-sized implementation plan from a spec or requirements before any code is touched. Use when you have requirements for a multi-step task and need a plan a fresh executor can follow without the original context.
---

# Writing Plans

## Purpose

Turn a spec (or clear requirements) into a comprehensive implementation plan written for an executor with zero context on the codebase: which files to touch per task, the exact code, the tests, the commands, how to verify. Small tasks, full detail, no placeholders.

## Workflow

1. **Announce:** "I'm using the writing-plans skill to create the implementation plan."
2. **Scope check.** If the spec covers multiple independent subsystems that weren't decomposed during brainstorming, propose splitting into one plan per subsystem. Each plan must produce working, testable software on its own.
3. **Map the file structure first.** Before defining tasks, list every file created or modified and what each is responsible for — this is where decomposition decisions get locked in. Design units with clear boundaries and well-defined interfaces; each file gets one clear responsibility. Split by responsibility, not by technical layer. In existing codebases, follow established patterns (if a file you're modifying has grown unwieldy, including a split in the plan is reasonable).
4. **Right-size the tasks.** A task is the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate: fold setup, config, scaffolding, and docs into the task whose deliverable needs them; split only where a reviewer could meaningfully reject one task while approving its neighbor. Each task ends with an independently testable deliverable. Keep steps bite-sized — one action each: write the failing test → run it, see it fail → write minimal code → run tests, see them pass → commit.
5. **Write the plan file** using the template in `references/plan-template.md`. Every step contains the actual content the executor needs: real code blocks, exact commands, expected outputs. The "No Placeholders" rules below are plan failures — never write them.
6. **Self-review the plan** against the spec (inline, no subagent): spec coverage (can you point to a task for each requirement? list gaps), placeholder scan (search for the red flags below and fix), type consistency (do signatures, types, and names used in later tasks match what earlier tasks defined?). Fix issues inline; if a spec requirement has no task, add the task.
7. **Execution handoff.** Save the plan to the project's `plans/` directory (or the workflow working dir) as `YYYY-MM-DD-<feature-name>.md`, then ask: "Plan complete and saved to `<path>`. Two execution options:
   1. **Subagent-driven** (recommended) — I dispatch a fresh subagent per task with review between tasks; fast iteration.
   2. **Inline execution** — I execute tasks in this session step by step with review checkpoints.
   Which approach?" Then follow the subagent-driven-development skill or the executing-plans skill respectively.

## Operating Rules

- Assume the executor is skilled but knows nothing about your toolset or problem domain; assume weak test-design instincts and show exactly how to test.
- Never write these plan failures: "TBD", "TODO", "implement later", "fill in details"; "add appropriate error handling / validation / edge cases" without showing it; "write tests for the above" without actual test code; "similar to Task N" (repeat the code — executors may read tasks out of order); steps that describe what to do without showing how; references to types, functions, or methods defined in no task.
- Interfaces between tasks are explicit: each task lists what it Consumes from earlier tasks (exact signatures) and Produces for later tasks (exact names, parameter and return types). An implementer sees only their own task; this block is how they learn the names their neighbors use.
- Every task's requirements implicitly include the plan's Global Constraints (version floors, dependency limits, naming rules, platform requirements — exact values copied verbatim from the spec).
- DRY. YAGNI. TDD. Frequent commits.

## Output Contract

A saved plan file with the header, file map, and bite-sized tasks from `references/plan-template.md`, self-reviewed against the spec, plus the execution-choice question. For large plans, use the reviewer prompt in `references/plan-review-prompt.md` instead of relying solely on self-review.

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).
