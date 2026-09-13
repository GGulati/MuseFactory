---
name: brainstorming
description: Turns an idea into a validated design before any implementation. Use when about to do creative work — adding features, building components, changing behavior — or when a request's intent, requirements, or design are not yet pinned down.
---

# Brainstorming

## Purpose

Classify how much process a request needs, explore it collaboratively with the user, and produce a validated design — before a single line of implementation. The ceremony scales with the task; the approval gate never does.

## Workflow

1. **Classify and announce the path** before your first question. Say it out loud so the user can override it. When in doubt between two paths, take the heavier one. The ratchet is one-way: hidden complexity discovered mid-task upgrades the path — stop, say so, and step up. Nothing downgrades mid-task.
   - **Spike** — a feasibility question ("can we...", "quick and dirty is fine") whose output is an answer, not code to keep. Present the question and what you'll probe in 2-3 sentences, get a nod, investigate as cheaply as correctness allows. Report findings as a recommendation; anything built stays labeled throwaway.
   - **Bounded** — a well-scoped change to code that already exists in this repo: a new flag, a small endpoint, a one-file fix. Bounded means the flow you are changing is already here to read — if there is no existing flow to change, the task is not bounded. Ask the clarifying questions that matter, present a short design **in chat** (a few sentences to a few short paragraphs), and STOP.
   - **Architectural** — new projects, new subsystems, changes that restructure how components fit together or alter interfaces others depend on. Full process: questions → approaches → sectioned design → written spec → writing-plans.
2. **Explore project context** — check files, docs, recent commits. Before detailed questions, assess scope: if the request describes multiple independent subsystems, flag it immediately and help decompose into sub-projects, each getting its own spec → plan → implementation cycle. Never spend questions refining a project that needs decomposition first.
3. **Ask clarifying questions** — one at a time, one per message. Prefer multiple-choice when it fits. Focus on purpose, constraints, and success criteria. On the architectural path, the first time a question would genuinely be clearer shown than told (a real mockup/layout/diagram question — not merely a UI *topic*), offer visual mockups via the `widget` tool in its own message; see `references/visual-mockups.md`.
4. **Propose 2-3 approaches** (architectural) — with trade-offs, lead with your recommendation and why. YAGNI ruthlessly: strip unrequested features from every approach and design.
5. **Present the design** — scaled to complexity (a few sentences to ~200-300 words per section). Cover architecture, components, data flow, error handling, testing. Get approval after each section. Design for isolation: each unit has one clear purpose, communicates through well-defined interfaces, and is understandable and testable independently.
6. **Get explicit approval — then stop.** The gate is the approval, not the design's length. A bounded task's chat design gets the same hard gate as an architectural spec. Present the design and wait for a yes in the same turn is skipping the gate.
7. **Architectural only: write the spec file**, run the spec self-review, and get the user's review of the written spec before handing off to writing-plans.
   - Write the validated design to the project's `plans/` directory (or the workflow working dir), named `YYYY-MM-DD-<topic>-design.md`. Use the project's own spec location if one exists.
   - **Spec self-review** (inline, no subagent): placeholder scan (TBD/TODO/vague requirements), internal consistency (sections contradict each other?), scope check (one plan's worth?), ambiguity check (any requirement interpretable two ways — pick one and make it explicit). Fix issues inline, no re-review needed.
   - Ask the user to review the written spec file before proceeding. Apply changes they request and re-run the self-review.
8. **Hand off.** Architectural → the writing-plans skill. Bounded → implementation proceeds directly through the normal development workflow after approval (no plan document). Spike → terminal state is the reported recommendation. Never invoke an implementation skill other than writing-plans after brainstorming.

## Operating Rules

- **Hard gate:** do not write code, scaffold a project, or take any implementation action until you have stated your intent and the user has approved it. This applies to every task on every path.
- "Simple" means a short design, not no design. Two sentences in chat, then approval.
- Reaching for a label to skip work IS the doubt — take the heavier path.
- "It's obvious, I'll start while they read it" is skipping the gate. Present, then stop until yes.
- "I understand this kind of app" does not make a task bounded; bounded measures the repo, not your familiarity. A new project has no existing flow — it is architectural.
- A spike's output is an answer. Keeping the code is a new request — classify it.
- It grew but you're almost done → still re-classify. Stop and say so.
- Each task gets its own classification and its own approval — a spike's nod does not approve the follow-up change.
- In existing codebases, follow established patterns. Include targeted improvements to code you're touching that affects the work; never propose unrelated refactoring.

## Output Contract

- **Spike:** 2-3 sentence probe plan approved → investigation → chat report with a recommendation; built artifacts labeled throwaway.
- **Bounded:** clarifying questions → short in-chat design (approach, files touched, testing) → explicit user approval → proceed without a plan document.
- **Architectural:** sectioned design approved per-section → spec file written + self-reviewed → user reviews the file → hand off to the writing-plans skill with the spec path.

See `references/spec-review-prompt.md` for a reviewer-subagent prompt you can use when the spec is too large for a reliable self-review. See `references/visual-mockups.md` for the just-in-time visual offer procedure.

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).
