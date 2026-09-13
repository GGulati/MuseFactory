---
name: finishing-a-development-branch
description: Integrates a finished development branch after tests pass. Use when implementation is complete and the suite is green — verifies tests, detects worktree vs normal-repo state, then presents the user with merge-locally / push-and-open-PR (approval required) / keep-as-is, and cleans up owned worktrees.
---

# Finishing a Development Branch

## Purpose

Take a branch from "tests pass" to "integrated" safely: verify the suite, confirm the base branch, present the user with explicit integration options, execute their choice, and clean up any worktree this workflow created.

## Workflow

1. **Verify tests.** Run the full project test suite on the current tree (`npm test` / `cargo test` / `pytest` / `go test ./...`). If anything fails, stop and report the failures. A green run earlier in the session does not count — re-run on the tree you are about to integrate.
2. **Detect environment** via `muse.exec`:
   ```bash
   GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
   GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
   WORKTREE_PATH=$(git rev-parse --show-toplevel)
   ```
   - `GIT_DIR == GIT_COMMON`: normal repo, no worktree cleanup.
   - `GIT_DIR != GIT_COMMON` on a named branch: worktree exists; cleanup may be owned by this workflow (step 5).
   - Detached HEAD: externally managed workspace — offer a reduced menu (step 3) and never clean up.
3. **Confirm the base branch.** Use the fork point named in the plan or task; if unknown, propose your best guess and ask: "This branch split from `<guess>` — correct?" Never merge into an unconfirmed base.
4. **Present options and wait.** The integration decision is always the user's. Present exactly:
   ```
   Implementation complete. What would you like to do?
   1. Merge back to <base-branch> locally
   2. Push and create a Pull Request
   3. Keep the branch as-is (I'll handle it later)
   Which option?
   ```
   For detached HEAD, present only options 2 and 3. Do not offer to discard work; discard happens only when the user explicitly asks (see `references/cleanup.md`).
5. **Execute their choice:**
   - **Option 1 — merge locally:** check out the base branch in the main repo root, `git pull`, `git merge <feature-branch>`, then re-run the test suite on the merged result. If the merged result fails, stop with branch and worktree intact — the merge is local and recoverable. Only when green: remove the worktree (below), then `git branch -d <feature-branch>`. A local merge never pushes.
   - **Option 2 — push and PR:** **Approval required.** Present the finished branch first — summary of commits, test results, diff stat — and ask: "Push `<branch>` to origin and open a PR against `<base>`?" Only after explicit approval, run `git push -u origin <feature-branch>` (from detached HEAD: `git push origin HEAD:refs/heads/<new-branch>`), then create the PR with `gh pr create --base <base>` following the repo's PR template, and report the URL. Keep the worktree — PR feedback is iterated on there.
   - **Option 3 — keep as-is:** report the branch name and worktree path; change nothing.
6. **Clean up the worktree** (options 1 and explicit discards only; never for options 2 or 3). Run from the main repo root, using the `WORKTREE_PATH` captured in step 2:
   ```bash
   git worktree remove "$WORKTREE_PATH"
   git worktree prune
   ```
   - Only worktrees under `.worktrees/` or `worktrees/` are owned by this workflow. Anything else belongs to the host environment — leave it in place.
   - If removal is refused (uncommitted files exist only there), never `--force` on your own initiative. Show `git -C "$WORKTREE_PATH" status --porcelain -uall` and ask the user: commit them, move them, or delete them.

## Operating Rules

- **Pushing to GitHub and opening a PR always require the user's explicit approval.** Present the finished branch and ask; never push unprompted, never `--force` push without an explicit request.
- Tests are verified on the exact tree being integrated, twice if merged (pre-merge and post-merge).
- A rejected push means the remote moved — investigate; do not force-push to fix it.
- The menu is complete as written. Discard is an explicit-request-only path (see `references/cleanup.md`).

## Output Contract

- Green test run (pre-integration, and post-merge when merging).
- The user's explicit choice recorded before any push, merge-to-mainline, or deletion.
- For option 2: the PR URL. For option 1: confirmation the base branch is updated and the branch/worktree are removed. For option 3: branch name and worktree path preserved.

Adapted from obra/superpowers (MIT, © 2025 Jesse Vincent).
