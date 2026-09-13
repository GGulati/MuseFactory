---
name: executing-plans
description: Executes a written implementation plan yourself, step by step, with review checkpoints. Use when you have a plan file to implement and no child-agent support — prefer subagent-driven-development when you can dispatch subagents.
---

# Executing Plans

## Purpose

Take a written implementation plan and execute it inline, in order, exactly as specified — load, critically review, execute every task with its verifications, then report. Prefer the subagent-driven-development skill whenever you can dispatch child agents; use this one when executing yourself.

## Workflow

1. **Load and review the plan.**
   - Work in an isolated workspace: use the using-git-worktrees skill to create one or verify the existing one.
   - Read the plan file, and the spec it points to if one exists.
   - Review critically — identify questions or concerns. If any, raise them with the user before starting. Do not guess through an unclear instruction.
   - If clean: create a tracking entry per task and proceed.
2. **Execute the tasks in order.** For each task: mark in progress → follow each step exactly → run every verification as specified (never skip verifications) → mark complete.
3. **Complete development.** After all tasks are done and verified, hand off to the finishing-a-development-branch skill for final verification and wrap-up.

## Operating Rules

- **Stop executing immediately when:** you hit a blocker (missing dependency, failing test, unclear instruction), the plan has critical gaps, you don't understand an instruction, or verification fails repeatedly. Ask for clarification rather than guessing.
- **Return to the review step when:** the user updates the plan based on your feedback, or the fundamental approach needs rethinking. Don't force through blockers.
- Reference other skills when the plan says to (e.g. test-driven-development for TDD tasks).
- Never start implementation on a main/master branch without explicit user consent.

## Output Contract

All tasks executed and verified per the plan's steps, with per-task status tracked to completion; blockers surfaced to the user immediately rather than worked around.

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).
