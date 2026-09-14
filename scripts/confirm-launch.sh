#!/usr/bin/env bash
# confirm-launch.sh — confirm-CAS after the caller issues the launch tool call.
# Usage: confirm-launch.sh <project> <workstream> <launched-run-id> [--chain-token <tok>]
#
# Under one project-mutex acquisition:
#   recorded run_id == launched-run-id -> CONFIRMED (idempotent)
#   recorded run_id null/empty          -> record it (+armed_at=now); with
#                                          --chain-token, CAS on
#                                          chain_intent.claim.token (mismatch ->
#                                          CAS_ABORT, exit 3) and perform the
#                                          arming write that completes the chain
#                                          (current_item=next_item, questions=[],
#                                          parked_at/paused_at=null,
#                                          chain_intent=null)
#   recorded run_id is a different id  -> ADOPT_RECORDED <cur>, exit 6
#                                          (caller stops the just-launched run
#                                          and adopts the recorded one)
#
# Exit codes: 0 ok, 2 usage/validation, 3 CAS abort, 5 fail-closed, 6 adopt-recorded.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/run.sh"
LIBDIR="$DF_SCRIPTS_DIR/lib"

usage() {
  echo "usage: confirm-launch.sh <project> <workstream> <launched-run-id> [--chain-token <tok>]" >&2
  exit 2
}

[ "$#" -ge 3 ] || usage
project="$1" workstream="$2" launched_run_id="$3"
shift 3
chain_token=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --chain-token) [ -n "${2:-}" ] || usage; chain_token="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$launched_run_id" ] || usage

df_projdir "$project" >/dev/null || exit 2
df_validate_workstream "$workstream" >/dev/null || exit 2

args=(python3 "$LIBDIR/confirm_launch.py" "$project" "$workstream" "$launched_run_id")
[ -n "$chain_token" ] && args+=(--chain-token "$chain_token")

rc=0
df_run_under_mutex "$project" "confirm-launch.sh" -- "${args[@]}" || rc=$?
exit "$rc"
