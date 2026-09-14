#!/usr/bin/env bash
# prepare-launch.sh — the OTP already_started in-flight guard.
# Usage: prepare-launch.sh <project> <workstream> <item-id> --live-runs <json-file>
#
# Under one project-mutex acquisition: applies the section 11.4 candidate
# filter to the live-runs JSON. Zero candidates -> arms the launch
# (run_id=null, armed_at=now), prints ARMED. Exactly one -> adopts it,
# prints ADOPTED <run_id>. More than one -> fail closed: prints
# ABORT_MULTIPLE plus a NOTIFY line, exit 5.
#
# Exit codes: 0 ok, 2 usage/validation, 3 CAS abort (n/a here), 5 fail-closed.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/run.sh"
LIBDIR="$DF_SCRIPTS_DIR/lib"

usage() {
  echo "usage: prepare-launch.sh <project> <workstream> <item-id> --live-runs <json-file>" >&2
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
  echo "prepare-launch.sh: live-runs file not found: $live_runs" >&2
  exit 2
}

df_projdir "$project" >/dev/null || exit 2
df_validate_workstream "$workstream" >/dev/null || exit 2
df_validate_slug "$item_id" "item id" >/dev/null || exit 2

rc=0
df_run_under_mutex "$project" "prepare-launch.sh" -- \
  python3 "$LIBDIR/prepare_launch.py" "$project" "$workstream" "$item_id" "$live_runs" || rc=$?
exit "$rc"
