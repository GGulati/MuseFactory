# Cleanup and discard protocol (finishing-a-development-branch)

## Which worktrees this workflow may remove

| State | Cleanup |
|---|---|
| `GIT_DIR == GIT_COMMON` (normal repo) | No worktree — nothing to do |
| `WORKTREE_PATH` under `.worktrees/` or `worktrees/` | Owned — `git worktree remove` + `git worktree prune` |
| Worktree elsewhere | Host-owned — leave in place; use the platform's workspace-exit tool if one exists |
| Detached HEAD | Externally managed — never clean up |

Cleanup runs from the main repo root (`git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel`), never from inside the worktree being removed.

## Removal refused — uncommitted files

`git worktree remove` refuses when the worktree holds uncommitted files that exist nowhere else (notes, scratch, uncommitted plans). Show:

```bash
git -C "$WORKTREE_PATH" status --porcelain -uall
```

Then ask:

```
Worktree removal refused — these files were never committed:
<file list>
1. Commit them to <branch> before cleanup
2. Move them into <main repo root>
3. Delete them (unrecoverable)
Which?
```

Carry out the choice, then remove the worktree.

## Discard — explicit request only

Only when the user asks to throw the work away, in so many words. Confirm with this exact prompt:

```
This will permanently delete:
- Branch <name>
- All commits: <commit-list>
- Worktree at <path>
Type 'discard' to confirm.
```

Only the typed word `discard` authorizes deletion — "yeah, get rid of it" does not count. On confirmation, change to the main repo root, run the worktree cleanup above, then `git branch -D <feature-branch>`.

## Merging

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
git checkout <base-branch>
git pull
git merge <feature-branch>
<test command>   # full suite on the merged result
```

If the merged result fails: stop, leave branch and worktree in place, investigate. Nothing has been pushed, so the merge is local and recoverable.
