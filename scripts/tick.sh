#!/usr/bin/env bash
# tick.sh — per-project liveness tick entry point (plan §11).
#
# The tick is the OTP monitor (polling substitute for 'DOWN', 2-min
# interval) and the standby supervisor: it runs the same deterministic
# scripts as the supervisor and may apply envelopes, relaunch dead runs,
# and reconcile the backlog -- but it never interprets user intent, never
# touches chats, and every mutation goes through scripts/ (ms-scale mutex,
# CAS, ledger). Its only user channel is its cron delivery to the project
# side chat.
#
# Scripts never launch workflows and never hold the mutex during a launch,
# so the sweep emits pending-launch records and the cron worker performs
# the launches (tool calls) between sweep and confirm:
#
#   tick.sh <project> sweep --live-runs <file> [--db-unreachable]
#       Full deterministic sweep (plan §11.1 precedence). Prints
#       TICK_SWEEP_OK plus DELIVERY / PENDING / MARK sections.
#       --live-runs: JSON array prepared by the worker from muse.db
#         [{run_id,status,heartbeat_at,started_at,completed_at,
#           final_result,args:{project,item_id}}].
#         Pass --db-unreachable instead when muse.db is unreachable:
#         file-only mode, no checkpoint mutations, no disarms (§11.7).
#       Worker protocol after a sweep:
#         1. for each PENDING token: read
#            checkpoints/pending-launches/<token>.json and launch the
#            dev-factory workflow with that file's "workflow_args" object
#            ({project, item_id, backlog_path, repo_path, worktree_path,
#            base_branch} -- absolute paths satisfying the workflow's
#            fail-fast arg contract; never launch with any other args).
#            If "workflow_args" is null, do NOT launch: the args are
#            unresolvable (project.json lacks worktree_path) -- audit it
#            and leave the checkpoint for the supervisor instead of
#            inventing paths. Then:
#            tick.sh <project> confirm-launch <token> <run-id>
#         2. send the DELIVERY block as this run's project-chat message
#            (empty delivery -> stay silent)
#         3. notify.sh <project> mark-delivered --ids <MARK ids>
#
#   tick.sh <project> confirm-launch <token> <run-id>
#       confirm-CAS a worker-performed launch (confirm-launch.sh); on
#       success the pending record is consumed. Prints WORKFLOW_ARGS=<json>
#       so the worker can see the exact args the launch must have used;
#       warns when workflow_args was null (unresolvable -- the launch
#       could not have satisfied the workflow's arg contract). Idempotent:
#       re-confirming an already-recorded run prints CONFIRMED.
#
# Exit codes: 0 ok, 2 usage/validation, 1 sweep error (fail closed).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"
LIBDIR="$DF_SCRIPTS_DIR/lib"

usage() {
  echo "usage: tick.sh <project> sweep --live-runs <file> [--db-unreachable]" >&2
  echo "       tick.sh <project> confirm-launch <token> <run-id>" >&2
  exit 2
}

[ "$#" -ge 2 ] || usage
project="$1"
op="$2"
shift 2
projdir="$(df_projdir "$project")" || exit 2

case "$op" in
  sweep)
    live_runs=""
    db_unreachable=0
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --live-runs) [ -n "${2:-}" ] || usage; live_runs="$2"; shift 2 ;;
        --db-unreachable) db_unreachable=1; shift ;;
        *) usage ;;
      esac
    done
    if [ "$db_unreachable" -eq 1 ]; then
      exec python3 "$LIBDIR/tick_sweep.py" sweep "$project" --db-unreachable
    fi
    [ -n "$live_runs" ] || usage
    [ -f "$live_runs" ] || {
      echo "tick.sh: live-runs file not found: $live_runs" >&2
      exit 2
    }
    exec python3 "$LIBDIR/tick_sweep.py" sweep "$project" "$live_runs"
    ;;
  confirm-launch)
    [ "$#" -eq 2 ] || usage
    token="$1"
    run_id="$2"
    [[ "$token" =~ ^[0-9a-f]{32}$ ]] || {
      echo "tick.sh: bad pending-launch token" >&2
      exit 2
    }
    [ -n "$run_id" ] || {
      echo "tick.sh: empty run-id" >&2
      exit 2
    }
    pend="$projdir/checkpoints/pending-launches/$token.json"
    [ -f "$pend" ] || {
      echo "tick.sh: no pending launch for token $token" >&2
      exit 2
    }
    eval "$(python3 - "$pend" <<'PYEOF'
import json, shlex, sys
try:
    pl = json.load(open(sys.argv[1]))
    ws, item, ct = pl.get("workstream"), pl.get("item_id"), pl.get("chain_token")
    wa = pl.get("workflow_args")
    assert isinstance(ws, str) and isinstance(item, str) and pl.get("token")
    print("ws=%s" % shlex.quote(ws))
    print("item=%s" % shlex.quote(item))
    print("chain_token=%s" % shlex.quote(ct if isinstance(ct, str) else ""))
    print("wargv=%s" % shlex.quote(json.dumps(wa, separators=(",", ":"), sort_keys=True)))
except Exception:
    print("echo 'tick.sh: corrupt pending-launch file' >&2; exit 2")
    sys.exit(0)
PYEOF
)"
    # shellcheck disable=SC2154
    echo "WORKFLOW_ARGS=${wargv:-null}"
    if [ "${wargv:-null}" = "null" ]; then
      echo "tick.sh: warning: pending-launch record has null workflow_args --" \
        "the launch could not have satisfied the workflow's fail-fast arg" \
        "contract; verify the run's args before trusting it" >&2
    fi
    rc=0
    if [ -n "${chain_token:-}" ]; then
      "$DF_SCRIPTS_DIR/confirm-launch.sh" "$project" "$ws" "$run_id" \
        --chain-token "$chain_token" || rc=$?
    else
      "$DF_SCRIPTS_DIR/confirm-launch.sh" "$project" "$ws" "$run_id" || rc=$?
    fi
    if [ "$rc" -eq 0 ]; then
      "$DF_SCRIPTS_DIR/mutex.sh" "$project" -- rm -f "$pend"
    fi
    exit "$rc"
    ;;
  *) usage ;;
esac
