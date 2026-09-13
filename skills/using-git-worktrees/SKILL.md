---
name: using-git-worktrees
description: Sets up an isolated git worktree for feature work under the project checkout. Use before starting any implementation that should not touch the current working tree — detect existing isolation first, create the worktree under `.worktrees/` only with approval, then run setup and a clean test baseline.
---

# Using Git Worktrees

## Purpose

Do implementation work in an isolated workspace so the main checkout stays clean. Worktrees live under the project checkout (never in temp dirs), and every setup ends with a verified clean test baseline.

## Workflow

1. **Detect existing isolation.** Run via `muse.exec`:
   ```bash
   GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
   GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
   git rev-parse --show-superproject-working-tree 2>/dev/null  # non-empty = submodule, not a worktree
   ```
   - If `GIT_DIR != GIT_COMMON` and not a submodule: you are already in a worktree. Report the path and branch, then skip to step 4.
   - If detached HEAD: report it; branch creation happens at finish time.
2. **Get consent.** Unless a worktree preference is already declared in the task, ask: "Set up an isolated worktree? It keeps your current branch untouched." If declined, work in place and go to step 4.
3. **Create the worktree** (consent given or preference declared):
   ```bash
   LOCATION=".worktrees"   # default; use the declared preference if one exists
   mkdir -p "$LOCATION"
   git check-ignore -q "$LOCATION" || { echo "$LOCATION/" >> .gitignore && git add .gitignore && git commit -qm "Ignore $LOCATION"; }
   git worktree add "$LOCATION/<branch-name>" -b <branch-name>
   cd "$LOCATION/<branch-name>"
   ```
   If `git worktree add` fails with a permission error, report that the sandbox blocked worktree creation and work in the current directory instead.
4. **Project setup.** Auto-detect and install dependencies:
   ```bash
   [ -f package.json ] && npm install
   [ -f Cargo.toml ] && cargo build
   [ -f requirements.txt ] && pip install -r requirements.txt
   [ -f pyproject.toml ] && poetry install
   [ -f go.mod ] && go mod download
   ```
5. **Verify clean baseline.** Run the project's test suite (`npm test` / `cargo test` / `pytest` / `go test ./...`). If it fails, report the failures and ask whether to proceed or investigate — never start on a dirty baseline silently.

## Operating Rules

- Never create a worktree if already in one; never create one inside another worktree's checkout.
- The worktree directory MUST be gitignored before use; commit the `.gitignore` change.
- One worktree per branch; name the directory exactly after the branch.
- A failing baseline test suite is the user's call, not yours — report and wait.
- Cleanup (removing a worktree) belongs to the finishing-a-development-branch skill, not this one.

## Output Contract

```
Worktree ready at <full-path>
Branch: <branch-name>
Baseline: <N> tests passing, 0 failures
```

See `references/setup.md` for detection edge cases and per-language setup notes.

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).
