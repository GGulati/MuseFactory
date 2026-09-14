#!/usr/bin/env bash
# record-death.sh — OTP restart-intensity accounting for a workstream.
# Usage: record-death.sh <project> <workstream> [--summary <text>]
# Under one mutex acquisition: appends now to death_timestamps, drops
# entries older than 30 minutes. At >= 3 deaths in the window the workstream
# is parked (state=parked, parked_at=now, paused_at=null) with a recovery
# question, and an escalation notification record is appended to
# notifications.jsonl under the same mutex hold. Prints DEATHS=<n>, or
# DEATHS=<n> ESCALATED when the threshold trips.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

usage() { echo "usage: record-death.sh <project> <workstream> [--summary <text>]" >&2; exit 2; }

[ "$#" -ge 2 ] || usage
project="$1"; ws_in="$2"; shift 2
projdir="$(df_projdir "$project")" || exit 2
ws="$(df_validate_workstream "$ws_in")" || exit 2

summary="(no summary provided)"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --summary) [ "$#" -ge 2 ] || usage; summary="$2"; shift 2 ;;
    *) usage ;;
  esac
done

exec "$SCRIPT_DIR/mutex.sh" "$project" -- python3 - "$projdir" "$project" "$ws" "$summary" <<'PYEOF'
import sys, os, json, tempfile, datetime, uuid

projdir, project, ws, summary = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
SCRIPT = "record-death.sh"
INVOKER = os.environ.get("DF_INVOKER", "cli")
WINDOW_SECS = 30 * 60
ESCALATE_AT = 3

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def parse_ts(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)

path = os.path.join(projdir, "checkpoints", ws + ".json")
try:
    with open(path) as f:
        cp = json.load(f)
except FileNotFoundError:
    print(f"{SCRIPT}: no checkpoint for workstream '{ws}'", file=sys.stderr)
    sys.exit(1)

t = now()
cutoff = parse_ts(t) - datetime.timedelta(seconds=WINDOW_SECS)
deaths = []
for ts in cp.get("death_timestamps") or []:
    try:
        if parse_ts(ts) >= cutoff:
            deaths.append(ts)
    except (ValueError, TypeError):
        continue
deaths.append(t)
cp["death_timestamps"] = deaths
n = len(deaths)

escalated = ""
if n >= ESCALATE_AT:
    item = cp.get("current_item")
    question = (f"The run for {item} has died 3 times in 30 minutes. "
                f"I've parked it \u2014 here\u2019s the last error: {summary}. "
                "Say retry to try again.")
    cp["state"] = "parked"
    cp["parked_at"] = t
    cp["paused_at"] = None
    cp["questions"] = [question]
    notif = {
        "id": uuid.uuid4().hex,
        "run_id": cp.get("run_id"),
        "workstream": ws,
        "event": "escalation",
        "copy": question,
        "created_at": t,
        "delivered_at": None,
    }
    with open(os.path.join(projdir, "notifications.jsonl"), "a") as f:
        f.write(json.dumps(notif, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    escalated = " ESCALATED"

d = os.path.dirname(path)
fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
try:
    with os.fdopen(fd, "w") as f:
        json.dump(cp, f, indent=2, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

with open(os.path.join(projdir, "audit.log"), "a") as f:
    f.write(f"{t} {INVOKER} {SCRIPT} record-death {ws} deaths={n}{escalated}\n")
    f.flush()
    os.fsync(f.fileno())

print(f"DEATHS={n}{escalated}")
PYEOF
