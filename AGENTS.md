# AGENTS.md — MuseFactory setup & operating contract

You are a Muse agent. Your user wants the MuseFactory system installed in their workspace from scratch, using this repo as the source. Do exactly what this file says, in order. Ask the user only when a step names a decision that is theirs.

## What you're installing

- **The `develop` skill** (`skills/develop` in this repo): the end-to-end engineering loop — orient → brainstorm → plan → dual plan review (product + technical) → isolate in a worktree → execute with TDD → debug → code review → finish/PR. It composes the upstream [obra/superpowers](https://github.com/obra/superpowers) skills (MIT), which you install separately in Step 1 — they are a dependency, not vendored here.
- **1 saved workflow** (`workflows/dev-factory.js`): a pure task worker — one backlog item to a typed terminal envelope, then it exits. It never loops over the backlog, never relaunches itself, never edits the backlog.
- **The runtime scripts** (`scripts/`): the serialized mutation layer — mutex, checkpoint state machine, terminal-envelope reconciliation, notification queue, launch protocol (prepare/confirm/adopt), and the liveness tick. All shared-state mutations go through these scripts, never through the workflow or the supervisor directly.
- **The supervisor runbook** (`SUPERVISOR.md`): the turn protocol for the LLM supervisor that applies terminal envelopes, handles replies and directives in the project side chat, and restarts workers.

## Prerequisites

Verify each; install or ask the user where you can't:

- `git`, `gh` (GitHub CLI), `python3`, `node`, `npm` — needed for the loop's verification steps.
- A Chromium browser available to the agent (for browser verification phases).
- The user must be logged into GitHub: `gh auth status`. If not, ask them to run `gh auth login`.

## Step 1 — Install the base skills (obra/superpowers)

The `develop` skill composes these upstream skills: `brainstorming`, `writing-plans`, `executing-plans`, `subagent-driven-development`, `test-driven-development`, `systematic-debugging`, `requesting-code-review`, `receiving-code-review`, `finishing-a-development-branch`, `using-git-worktrees`, `dispatching-parallel-agents`.

1. Clone upstream (MIT licensed): `git clone --depth 1 https://github.com/obra/superpowers /tmp/superpowers`
2. Install into the workspace: `mkdir -p ~/workspace/skills && cp -r /tmp/superpowers/skills/* ~/workspace/skills/` (copy at least the 11 listed above; copying all of them is fine).
3. Verify: each of the 11 directories under `~/workspace/skills/` contains a `SKILL.md`.

## Step 2 — Install the MuseFactory skill

Run `scripts/sync-skills.sh` from this repo. It copies every skill in `skills/` (each `SKILL.md` plus its `references/`) into `~/workspace/skills/<name>` via rsync --delete and verifies the install. Override the target with `MUSE_WORKSPACE=/path/to/workspace` if your workspace lives elsewhere.

### Keeping skills in sync (repo is the source of truth)

- Never edit the installed copy under `~/workspace/skills/develop` directly. Make the change in this repo, then re-run `scripts/sync-skills.sh`.
- After every `git pull`, re-run `scripts/sync-skills.sh` so the installed copy matches the repo exactly (the sync deletes files that no longer exist in the repo).
- To check for drift without changing anything: `scripts/sync-skills.sh --check` (exits non-zero and shows the diff when the copies differ).

## Step 3 — Install the workflow

1. Read this repo's `workflows/dev-factory.js` in full.
2. Register it with `workflow.create`, passing `name: "dev-factory"` and the file's entire contents as `script`. (The script's first statement must be the `export const meta = {...}` line — keep it verbatim.)
3. Verify with `workflow.list` — `dev-factory` must appear with phases `orient, implement, verify, report`.

## Step 4 — Wire the first project

For each project the user wants on the factory:

1. **Register the project.** Run `scripts/register-project.sh --project <project> --repo <repo-path> --worktree <worktree-path> --base-branch <branch> --chat <side-chat-id>`. It creates `~/workspace/dev-factory/projects/<project>/` with `project.json`, `backlog.md`, `user-replies/`, `checkpoints/`, `tombstones/`, `handled_run_ids`, and the notification queue. Conventions to tell the user:
   - Top-level bullets in `backlog.md` are backlog items; sub-bullets are detail at any depth; order is priority.
   - The backlog is the message queue: items are appended/removed by the envelope scripts only, never edited by workers. Don't rename an item mid-flight (branch matching uses the slugified title).
2. **Project side chat.** Create one side chat per project. Runs are launched from there; all questions/approvals land there; replies in it are the real-time resume event.
3. **Tick cron.** Create a per-project cron `dev-factory-tick-<project>` firing every 2 minutes, with delivery to the project side chat. The tick detects silent death, crash loops, and stalls — it never does supervision work.
4. **Launch.** Call the `dev-factory` workflow with `{project, item_id, backlog_path, repo_path, worktree_path, base_branch}`. One run = one item; when a `done` envelope reconciles and the backlog still has open items, the tick (or the supervisor turn) launches the next one.

## Operating contract (keep this behavior)

- **Collaboration:** planning and architecture are highly collaborative — product direction, game design, and technical forks go to the user. Small implementation choices run on autopilot (decide, log, move on). The bar: ask when a wrong guess wastes real work.
- **Gates are mandatory:** plan review (product + technical), code review, and push/PR each need explicit user approval. Never skip. Ambiguous replies get a one-line confirmation question — never an implicit approval.
- **Safety:** workers never push, merge, or delete branches. PR creation needs explicit user approval.
- **Terminal envelopes:** the worker's top-level return is exactly the envelope (`done` / `awaiting-approval` / `blocked` / `failed`). The supervisor turn applies it via `scripts/apply-envelope.sh` (exactly-once via the `handled_run_ids` ledger), and unanswered questions are asked again byte-identically. A reply in the project side chat resumes inline in that chat turn.
- **Reviews are fresh-context:** workers never review in-session. A `needs-review` blocked envelope routes to a fresh reviewer subagent, whose findings are recorded and fed back to the worker.
- **Crash-only:** a crash at any point converges on re-run. Mutations are idempotent, ledger-checked, and guarded by the project mutex + CAS preconditions. The tick's liveness sweep is the backstop for silent death, orphaned checkpoints, and stalled stops.

## Optional — Claude Code plugin setup

The `develop` skill is plain markdown with frontmatter, so it also works as a Claude Code plugin alongside the superpowers plugin:

1. In a copy of this repo, add `.claude-plugin/plugin.json`:
   ```json
   {
     "name": "musefactory",
     "description": "Backlog-to-PR engineering loop: brainstorm, plan, dual review, TDD, code review",
     "version": "1.0.0",
     "skills": "./skills"
   }
   ```
2. Ensure `skills/develop/SKILL.md` has `name` and `description` frontmatter (it does).
3. Install the upstream superpowers plugin first (it provides the 11 base skills), then `Muse plugin add <path-or-marketplace>` for this repo.
4. The `dev-factory` workflow is Muse-specific (it uses the workflow runtime); under Claude Code, replicate its contract — one item to a terminal envelope, phases `orient, implement, verify, report` — as an agent instruction or a slash command that drives the `develop` skill per backlog item.

## Notes

- Never commit licensed/third-party project assets to a public repo; the factory's transfer path for those is direct download or private links, not git.
- `workflows/dev-factory.js` is the single source of the workflow script; if you change the saved workflow, copy the updated script back here.
