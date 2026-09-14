#!/usr/bin/env bash
# adopt-or-relaunch.sh — strict orphan adoption check.
# Usage: adopt-or-relaunch.sh <project> <workstream> <item-id> --live-runs <json-file>
#
# Under one project-mutex acquisition: applies the same section 11.4
# candidate filter as prepare-launch.sh. Exactly one live run for
# (project, item) -> record run_id (+armed_at), prints ADOPT <run_id>.
# Zero -> no state change, prints RELAUNCH (the caller relaunches).
# More than one -> fail closed: prints ABORT_MULTIPLE plus a NOTIFY line,
# exit 5.
#
# Exit codes: 0 ok, 2 usage/validation, 5 fail-closed.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/run.sh"
LIBDIR="$DF_SCRIPTS_DIR/lib"

usage() {
  echo "usage: adopt-or-relaunch.sh <project> <workstream> <item-id> --live-runs <json-file>" >&2
  exit 2
}

[ "$#" -ge 3 ] || usage
project="$1" workstream="$2" item_id="$3"
shift 3
live_runs=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --live-runs) [ -n "${2:-}" ] || usage; live_runs="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$live_runs" ] || usage
[ -f "$live_runs" ] || {
  echo "adopt-or-relaunch.sh: live-runs file not found: $live_runs" >&2
  exit 2
}

df_projdir "$project" >/dev/null || exit 2
df_validate_workstream "$workstream" >/dev/null || exit 2
df_validate_slug "$item_id" "item id" >/dev/null || exit 2

rc=0
df_run_under_mutex "$project" "adopt-or-relaunch.sh" -- \
  python3 "$LIBDIR/adopt_or_relaunch.py" "$project" "$workstream" "$item_id" "$live_runs" || rc=$?
exit "$rc"
