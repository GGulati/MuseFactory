#!/usr/bin/env bash
# notify.sh — durable notification helpers (plan §9.1, §11.1).
#
# Notifications are durable records in notifications.jsonl:
#   {id, run_id, workstream, event, copy, created_at, delivered_at}
# Writers append them under the project mutex (same hold as the ledger
# append); the tick backfills undelivered records through its project-chat
# delivery and the worker marks them delivered afterwards. Nothing is
# ever silently dropped: a crash between delivery and mark-delivered
# just redelivers next sweep.
#
# Usage:
#   notify.sh <project> pending
#       Print undelivered records, one per line: <id>\t<event>\t<copy>
#       (read-only; no mutex).
#   notify.sh <project> mark-delivered --ids <id1,id2,...>
#       CAS-set delivered_at=now for the given ids (under the mutex).
#       Delegates to ack-notifications.sh.
#
# Exit codes: 0 ok, 2 usage/validation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DF_SCRIPTS_DIR="${DF_SCRIPTS_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1091
source "$DF_SCRIPTS_DIR/lib/common.sh"

usage() {
  echo "usage: notify.sh <project> {pending|mark-delivered --ids <id,...>}" >&2
  exit 2
}

[ "$#" -ge 2 ] || usage
project="$1"
op="$2"
shift 2
projdir="$(df_projdir "$project")" || exit 2

case "$op" in
  pending)
    [ "$#" -eq 0 ] || usage
    python3 - "$projdir/notifications.jsonl" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    f = open(path, encoding="utf-8")
except FileNotFoundError:
    sys.exit(0)
for line in f:
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    if r.get("delivered_at") is None and r.get("id") and r.get("copy"):
        copy = str(r["copy"]).replace("\t", " ").replace("\n", " ")
        print("%s\t%s\t%s" % (r["id"], r.get("event", ""), copy))
PYEOF
    ;;
  mark-delivered)
    ids=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --ids) [ -n "${2:-}" ] || usage; ids="$2"; shift 2 ;;
        *) usage ;;
      esac
    done
    [ -n "$ids" ] || usage
    # shellcheck disable=SC2086
    exec "$DF_SCRIPTS_DIR/ack-notifications.sh" "$project" $(echo "$ids" | tr ',' ' ')
    ;;
  *) usage ;;
esac
