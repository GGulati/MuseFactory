#!/usr/bin/env bash
# mutex.sh — project-wide mutex for dev-factory entry points.
# Usage: mutex.sh <project> -- <cmd> [args...]
# Acquires the mkdir-based lock at $projdir/.mutex.lock, runs <cmd>,
# releases on EXIT, and exits with the command's status.
# Polls every 0.05s up to 10s; a lock whose mtime is older than 30s is
# stale-broken (rmdir + audit). If CHECKPOINT_HOLD_SECS is set, sleeps that
# long while holding the lock (E2E fault injection only).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

[ "${1:-}" != "" ] || { echo "usage: mutex.sh <project> -- <cmd> [args...]" >&2; exit 2; }
project="$1"; shift
[ "${1:-}" = "--" ] || { echo "usage: mutex.sh <project> -- <cmd> [args...]" >&2; exit 2; }
shift
[ "$#" -ge 1 ] || { echo "usage: mutex.sh <project> -- <cmd> [args...]" >&2; exit 2; }

projdir="$(df_projdir "$project")" || exit 2
mkdir -p "$projdir"
lockdir="$projdir/.mutex.lock"

now_s() { date +%s; }
deadline=$(( $(now_s) + 10 ))

while ! mkdir "$lockdir" 2>/dev/null; do
  if [ -d "$lockdir" ]; then
    mtime="$(stat -c %Y "$lockdir" 2>/dev/null || echo 0)"
    if [ $(( $(now_s) - mtime )) -ge 30 ]; then
      if rmdir "$lockdir" 2>/dev/null; then
        df_audit "$project" "mutex.sh" "stale-break (lock older than 30s)"
        continue
      fi
    fi
  fi
  if [ "$(now_s)" -ge "$deadline" ]; then
    echo "mutex.sh: could not acquire $lockdir within 10s" >&2
    exit 1
  fi
  sleep 0.05
done

released=0
release() {
  if [ "$released" -eq 0 ]; then
    released=1
    rmdir "$lockdir" 2>/dev/null || true
  fi
}
trap release EXIT

if [ -n "${CHECKPOINT_HOLD_SECS:-}" ]; then
  sleep "$CHECKPOINT_HOLD_SECS"
fi

set +e
"$@"
rc=$?
set -e
exit "$rc"
