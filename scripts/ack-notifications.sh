#!/usr/bin/env bash
# ack-notifications.sh — mark notification records delivered.
# Usage: ack-notifications.sh <project> <id> [<id>...]
#
# Under one project-mutex acquisition: for each id, sets delivered_at=now
# where currently null in notifications.jsonl. Prints ACKED <n> (n = records
# transitioned). Already-delivered records are untouched.
#
# Exit codes: 0 ok, 2 usage/validation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/run.sh"
LIBDIR="$DF_SCRIPTS_DIR/lib"

usage() {
  echo "usage: ack-notifications.sh <project> <id> [<id>...]" >&2
  exit 2
}

[ "$#" -ge 2 ] || usage
project="$1"
shift
df_projdir "$project" >/dev/null || exit 2
for id in "$@"; do
  [ -n "$id" ] || usage
done

rc=0
df_run_under_mutex "$project" "ack-notifications.sh" -- \
  python3 "$LIBDIR/ack_notifications.py" "$project" "$@" || rc=$?
exit "$rc"
