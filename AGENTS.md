# AGENTS.md — MuseFactory setup & operating contract

You are a Muse agent. Your user wants the MuseFactory system installed in their workspace from scratch, using this repo as the source. Do exactly what this file says, in order. Ask the user only when a step names a decision that is theirs.

## What you're installing

- **12 skills** (`skills/`): the engineering procedure library. Eleven are adapted from obra/superpowers (MIT, attribution inside each file); `develop` composes them into the end-to-end loop: orient → brainstorm → plan → dual plan review (product + technical) → isolate in a worktree → execute with TDD → debug → code review → finish/PR.
- **1 saved workflow** (`workflows/dev-factory.js`): deterministic orchestration that reads a backlog markdown doc, triages items, runs each through the `develop` skill, and reports.

## Prerequisites

Verify each; install or ask the user where you can't:

- `git`, `gh` (GitHub CLI), `python3`, `node`, `npm` — needed for the loop's verification steps.
- A Chromium browser available to the agent (for browser verification phases).
- The user must be logged into GitHub: `gh auth status`. If not, ask them to run `gh auth login`.

## Step 1 — Install the skills

Copy every directory under this repo's `skills/` into the user's `~/workspace/skills/` (create it if missing), preserving structure including `references/` and `bin/` subdirectories. Each skill directory must contain `SKILL.md` with YAML frontmatter (`name`, `description`). Verify the copy: 12 directories, each with `SKILL.md`.

## Step 2 — Install the workflow

1. Read this repo's `workflows/dev-factory.js` in full.
2. Register it with `workflow.create`, passing `name: "dev-factory"` and the file's entire contents as `script`. (The script's first statement must be the `export const meta = {...}` line — keep it verbatim.)
3. Verify with `workflow.list` — `dev-factory` must appear with phases `intake, triage, develop, report`.

## Step 3 — Wire the first project

For each project the user wants on the factory:

1. **Backlog doc (source of truth).** Create `~/workspace/your_files/<project>-backlog/<project>-backlog.md`. It appears in the user's Library as an editable doc. Seed it with their current bullets if they have any. Conventions to tell the user:
   - Top-level bullets are backlog items; sub-bullets are detail at any depth; order is priority.
   - The factory re-reads it live at the start of every run — edits and reorders are picked up automatically.
   - Items are removed only after their work is fully merged. Don't rename an item mid-flight (branch matching uses the slugified title).
2. **Repo checkout.** Clone or locate the project repo (record the path; the workflow assumes the main branch is named `main` — adjust the script if it isn't).
3. **Project side chat.** Create one side chat per project. Runs are launched from there and all questions/approvals land there.
4. **Launch.** Call the `dev-factory` workflow with `{project, backlog_path, repo_path}`. `concurrency` defaults to 1 — raise it only when the user explicitly wants parallel streams.

## Operating contract (keep this behavior)

- **Collaboration:** planning and architecture are highly collaborative — product direction, game design, and technical forks go to the user. Small implementation choices run on autopilot (decide, log, move on). The bar: ask when a wrong guess wastes real work.
- **Gates are mandatory:** end of design (Phase 1), end of plan (Phase 3), push/PR (Phase 8). Never skip.
- **Safety:** workers never push, merge, or delete branches. PR creation needs explicit user approval.
- **Factory questions:** workers return blocked/question envelopes; the workflow groups them per item in one report. The user answers in the project side chat; relaunch resumes (intake skips removed items and resumes active branches instead of redoing them).

## Optional — Claude Code plugin setup

The skills are plain markdown with frontmatter, so they also work as a Claude Code plugin:

1. In a copy of this repo, add `.claude-plugin/plugin.json`:
   ```json
   {
     "name": "musefactory",
     "description": "Backlog-to-PR engineering loop: brainstorm, plan, dual review, TDD, code review",
     "version": "1.0.0",
     "skills": "./skills"
   }
   ```
2. Ensure every `skills/<name>/SKILL.md` has `name` and `description` frontmatter (they do).
3. Install: `Muse plugin add <path-or-marketplace>` in the user's project, or point a plugin marketplace at this repo.
4. The `dev-factory` workflow is Muse-specific (it uses the workflow runtime); under Claude Code, replicate its phases — intake/triage/develop/report — as an agent instruction or a slash command that drives the `develop` skill per backlog item.

## Notes

- Never commit licensed/third-party project assets to a public repo; the factory's transfer path for those is direct download or private links, not git.
- `workflows/dev-factory.js` is the single source of the workflow script; if you change the saved workflow, copy the updated script back here.
