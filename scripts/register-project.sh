#!/usr/bin/env bash
# register-project.sh — idempotent project registration.
# Usage: register-project.sh <project> --chat <chat-id> --repo <path>
#          [--backlog <path>] [--worktree <path>] [--base-branch <branch>]
#
# Creates projects/<project>/{checkpoints,tombstones,user-replies} and writes
# project.json {project, chat_id, repo_path, backlog_path, worktree_path,
# base_branch, registered_at, tick_cron_id}. Re-registering never overwrites
# an existing registered_at or tick_cron_id. worktree_path/base_branch keep
# their recorded values unless the corresponding flag was passed; base_branch
# defaults to "main" when neither recorded nor given. Touches
# handled_run_ids and audit.log; creates notifications.jsonl and
# tick-health.json only when missing; copies --backlog to
# $projdir/backlog.md only when given and backlog.md is missing.
# Prints REGISTERED (new) or EXISTS (project.json already present).
#
# All state mutations run under the project mutex (M5): the validation
# section runs first with no mutex held, then the mutation section is
# re-invoked via mutex.sh with the --_mutex_inner subcommand. mutex.sh
# mkdir -p's the project dir, so this works for first registration too.
#
# Exit codes: 0 ok, 2 usage/validation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"

usage() {
  echo "usage: register-project.sh <project> --chat <chat-id> --repo <path> [--backlog <path>] [--worktree <path>] [--base-branch <branch>]" >&2
  exit 2
}

# ---- mutation section: runs under the project mutex via --_mutex_inner ----
if [ "${1:-}" = "--_mutex_inner" ]; then
  shift
  project="${RP_PROJECT:-}"
  chat_id="${RP_CHAT:-}"
  repo_path="${RP_REPO:-}"
  flag_worktree="${RP_WORKTREE:-}"
  flag_base_branch="${RP_BASE_BRANCH:-}"
  backlog_src="${RP_BACKLOG_SRC:-}"
  now="${RP_NOW:-}"
  [ -n "$project" ] || { echo "register-project.sh: missing RP_PROJECT" >&2; exit 2; }

  projdir="$(df_projdir "$project")" || exit 2
  mkdir -p "$projdir/checkpoints" "$projdir/tombstones" "$projdir/user-replies"

  existed=0
  [ -f "$projdir/project.json" ] && existed=1

  export RP_PROJDIR="$projdir" RP_PROJECT="$project" RP_CHAT="$chat_id" \
    RP_REPO="$repo_path" RP_WORKTREE="$flag_worktree" \
    RP_BASE_BRANCH="$flag_base_branch" RP_NOW="$now"
  python3 - <<'EOF'
import json, os
projdir = os.environ["RP_PROJDIR"]
p = os.path.join(projdir, "project.json")
existing = {}
if os.path.exists(p):
    with open(p, "r", encoding="utf-8") as f:
        existing = json.load(f)
# registered_at/tick_cron_id are never overwritten. worktree_path and
# base_branch keep their recorded values unless an explicit flag was
# passed; base_branch defaults to "main" when neither recorded nor given.
flag_worktree = os.environ.get("RP_WORKTREE") or None
flag_base = os.environ.get("RP_BASE_BRANCH") or None
doc = {
    "project": os.environ["RP_PROJECT"],
    "chat_id": os.environ["RP_CHAT"],
    "repo_path": os.environ["RP_REPO"],
    "backlog_path": os.path.join(projdir, "backlog.md"),
    "worktree_path": flag_worktree or existing.get("worktree_path") or None,
    "base_branch": flag_base or existing.get("base_branch") or "main",
    "registered_at": existing.get("registered_at") or os.environ["RP_NOW"],
    "tick_cron_id": existing.get("tick_cron_id"),
}
tmp = p + ".tmp.%d" % os.getpid()
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
os.replace(tmp, p)
EOF

  mutated=0
  [ "$existed" -eq 0 ] && mutated=1

  touch "$projdir/handled_run_ids" "$projdir/audit.log"

  if [ ! -f "$projdir/notifications.jsonl" ]; then
    : >"$projdir/notifications.jsonl"
    mutated=1
  fi

  if [ ! -f "$projdir/tick-health.json" ]; then
    python3 -c '
import json, os
p = os.path.join(os.environ["RP_PROJDIR"], "tick-health.json")
doc = {"dedupe_keys": {}, "violations": [], "outage_windows": []}
tmp = p + ".tmp.%d" % os.getpid()
with open(tmp, "w") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
os.replace(tmp, p)
'
    mutated=1
  fi

  if [ -n "$backlog_src" ] && [ ! -f "$projdir/backlog.md" ]; then
    cp -- "$backlog_src" "$projdir/backlog.md"
    mutated=1
  fi

  if [ "$mutated" -eq 1 ]; then
    df_audit "$project" "register-project.sh" \
      "registered (chat=$chat_id repo=$repo_path worktree=${flag_worktree:-unset} base=${flag_base_branch:-unset})"
  fi

  if [ "$existed" -eq 1 ]; then
    echo EXISTS
  else
    echo REGISTERED
  fi
  exit 0
fi

# ---- validation section: no mutex held ----
[ "$#" -ge 1 ] || usage
project="$1"
shift
chat_id="" repo_path="" backlog_src="" worktree_path="" base_branch=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --chat) chat_id="${2:-}"; shift 2 ;;
    --repo) repo_path="${2:-}"; shift 2 ;;
    --backlog) backlog_src="${2:-}"; shift 2 ;;
    --worktree) worktree_path="${2:-}"; shift 2 ;;
    --base-branch) base_branch="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$chat_id" ] || usage
[ -n "$repo_path" ] || usage
if [ -n "$backlog_src" ]; then
  [ -f "$backlog_src" ] || {
    echo "register-project.sh: backlog file not found: $backlog_src" >&2
    exit 2
  }
fi
if [ -n "$worktree_path" ]; then
  # The workflow fail-fast contract requires absolute paths without '..'.
  case "$worktree_path" in
    /*) ;;
    *) echo "register-project.sh: --worktree must be an absolute path: $worktree_path" >&2; exit 2 ;;
  esac
  case "$worktree_path" in
    *..*) echo "register-project.sh: --worktree must not contain '..': $worktree_path" >&2; exit 2 ;;
  esac
fi

df_projdir "$project" >/dev/null || exit 2

now="$(df_now)"
export RP_PROJECT="$project" RP_CHAT="$chat_id" RP_REPO="$repo_path" \
  RP_WORKTREE="$worktree_path" RP_BASE_BRANCH="$base_branch" \
  RP_BACKLOG_SRC="$backlog_src" RP_NOW="$now"
exec "$DF_SCRIPTS_DIR/mutex.sh" "$project" -- \
  "$DF_SCRIPTS_DIR/register-project.sh" --_mutex_inner
