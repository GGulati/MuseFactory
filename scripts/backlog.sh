#!/usr/bin/env bash
# backlog.sh — serialized backlog edits.
# Usage: backlog.sh <project> <remove|move-to-bottom|get|top-open> [item-id]
#
# Mutex.sh wrapper around the lib/backlog-lib.sh functions, applied to
# $projdir/backlog.md. remove/move-to-bottom print OK (idempotent no-ops when
# absent); get prints the item block; top-open prints the first item's id.
# get/top-open exit 1 when the item/backlog is empty.
#
# Exit codes: 0 ok, 1 item absent (get/top-open), 2 usage/validation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/run.sh"
LIBDIR="$DF_SCRIPTS_DIR/lib"

usage() {
  echo "usage: backlog.sh <project> <remove|move-to-bottom|get|top-open> [item-id]" >&2
  exit 2
}

[ "$#" -ge 2 ] || usage
project="$1" op="$2" item_id="${3:-}"
case "$op" in
  remove | move-to-bottom | get) [ -n "$item_id" ] || usage ;;
  top-open) ;;
  *) usage ;;
esac
if [ -n "$item_id" ]; then
  df_validate_slug "$item_id" "item id" >/dev/null || exit 2
fi

projdir="$(df_projdir "$project")" || exit 2
backlog_file="$projdir/backlog.md"

export DF_OP="$op" DF_FILE="$backlog_file" DF_ITEM="$item_id" DF_LIBDIR="$LIBDIR"
rc=0
df_run_under_mutex "$project" "backlog.sh" -- bash -c '
    set -euo pipefail
    # shellcheck disable=SC1091
    source "$DF_LIBDIR/backlog-lib.sh"
    case "$DF_OP" in
      remove)
        tok="$(bl_remove "$DF_FILE" "$DF_ITEM")"
        echo OK
        echo "AUDIT: backlog remove $DF_ITEM -> $tok"
        ;;
      move-to-bottom)
        tok="$(bl_move_to_bottom "$DF_FILE" "$DF_ITEM")"
        echo OK
        echo "AUDIT: backlog move-to-bottom $DF_ITEM -> $tok"
        ;;
      get)
        bl_get "$DF_FILE" "$DF_ITEM"
        ;;
      top-open)
        bl_top_open "$DF_FILE"
        ;;
    esac
  ' || rc=$?
exit "$rc"
