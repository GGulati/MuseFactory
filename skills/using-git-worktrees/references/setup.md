# Setup notes (using-git-worktrees)

## Detection edge cases

- `GIT_DIR != GIT_COMMON` inside a **submodule** is a false positive. Always run `git rev-parse --show-superproject-working-tree` first; if it prints a path, treat the repo as a normal checkout.
- Detached HEAD inside a worktree usually means the harness or a tool checked out a commit directly. Report it; the finishing-a-development-branch skill has a reduced menu for this state.
- If `git rev-parse` fails entirely, you are not in a git repo at all — say so and work in place.

## Directory selection order

1. An explicit worktree-location preference in the task or standing instructions — always wins.
2. An existing `.worktrees/` directory in the project root.
3. An existing `worktrees/` directory.
4. Default: create `.worktrees/` at the project root (and gitignore it).

## Per-language setup notes

- **Node:** use the lockfile (`npm ci` when `package-lock.json` exists and you want a reproducible install).
- **Python:** if both `requirements.txt` and `pyproject.toml` exist, use the one the project README points to; avoid double-installing. Prefer a virtualenv (`python3 -m venv .venv`) inside the worktree when the project does not pin one.
- **Rust/Go:** `cargo build` / `go mod download` only — full test compile happens at the baseline step.
- **No manifest found:** skip dependency install and go straight to the baseline step; report "no test command detected" if you cannot identify a suite.

## Baseline testing

- Run the suite the way the project documents it (README, package.json `scripts.test`, `Makefile test`). A generic guess is only a fallback.
- Record the baseline (pass/fail, count) in your report — it disambiguates later failures.
