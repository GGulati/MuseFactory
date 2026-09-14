#!/usr/bin/env bash
# apply-envelope.sh -- apply one terminal envelope exactly once (plan §8.3).
#
# Usage: apply-envelope.sh <project> <workstream> <envelope.json> <run-id>
#                          [--run-status <status>] [--no-chain]
#
# One script, two callers (terminal-handoff turns, tick recovery). Exactly-once
# via the handled_run_ids ledger: check-and-append under a single project-mutex
# acquisition, matched on run_id. Both callers run this same script; the loser
# sees the ledger and skips.
#
# Backlog mutations go through the sourced lib/backlog.py (imported by the
# embedded python) -- never a nested backlog.sh acquisition (plan Tech C2).
# The notification record is appended under the SAME mutex hold as the ledger
# append. notify() uses deterministic IDs ("<run_id>:<event>") and skips
# append if the ID already exists, and all paths call notify() BEFORE
# ledger_append(): a crash between the two is safe on re-run -- the
# notification is not duplicated, and the ledger appends exactly once.
#
# stdout: APPLIED_DONE | APPLIED_PARKED | APPLIED_FAILED | APPLIED_UNKNOWN |
#         APPLIED_DONE_TOMBSTONED | ALREADY_APPLIED | SUPERSEDED | LEDGER_ONLY |
#         IGNORED_NO_CHECKPOINT, plus optional CHAIN_ARMED <next-item>.
#
# --no-chain: reconcile a done envelope without arming chain_intent (the
# stop re-verify path, plan §11.2a: chaining would violate the stop intent).
set -euo pipefail
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "${1:-}" = "__under_lock" ]; then
  shift
  _project="$1"; _workstream="$2"; _envelope="$3"; _run_id="$4"; _run_status="${5:-}"; _no_chain="${6:-}"
  export DF_PROJDIR="$HOME/workspace/dev-factory/projects/$_project"
  [ -n "${DEV_FACTORY_HOME:-}" ] && export DF_PROJDIR="$DEV_FACTORY_HOME/projects/$_project"
  export DF_SCRIPTS="$SCRIPTS"
  export DF_WORKSTREAM="$_workstream" DF_ENVELOPE="$_envelope" DF_RUN_ID="$_run_id"
  export DF_RUN_STATUS="$_run_status" DF_INVOKER="${DF_INVOKER:-cli}"
  export DF_NO_CHAIN="$_no_chain"
  python3 - "$_project" <<'PYEOF'
import json, os, re, sys, tempfile
sys.path.insert(0, os.path.join(os.environ["DF_SCRIPTS"], "lib"))
import backlog as bl

project     = sys.argv[1]
projdir     = os.environ["DF_PROJDIR"]
workstream  = os.environ["DF_WORKSTREAM"]
env_path    = os.environ["DF_ENVELOPE"]
run_id      = os.environ["DF_RUN_ID"]
run_status  = os.environ.get("DF_RUN_STATUS") or ""
no_chain   = os.environ.get("DF_NO_CHAIN") == "1"
invoker     = os.environ.get("DF_INVOKER", "cli")

import datetime
def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = now()
TERMINAL = ("done", "awaiting-approval", "blocked", "failed")

cp_path      = os.path.join(projdir, "checkpoints", workstream + ".json")
ledger_path  = os.path.join(projdir, "handled_run_ids")
notif_path   = os.path.join(projdir, "notifications.jsonl")
audit_path   = os.path.join(projdir, "audit.log")
backlog_path = os.path.join(projdir, "backlog.md")

def load_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def write_atomic(p, data):
    d = os.path.dirname(os.path.abspath(p))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.rename(tmp, p)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def resolved_status(env):
    # Plan §5.3 terminal envelopes carry top-level `status`; `outcome` is a
    # legacy fallback kept for older fixtures/tools. `status` wins when both
    # are present.
    if not isinstance(env, dict):
        return None
    return env.get("status") or env.get("outcome")

def notif_has_id(nid):
    try:
        with open(notif_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("id") == nid:
                    return True
    except OSError:
        pass
    return False

def ledger_has(rid):
    try:
        with open(ledger_path, encoding="utf-8") as f:
            return any(line.rstrip("\n") == rid for line in f)
    except OSError:
        return False

def ledger_append(rid):
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(rid + "\n")

def notify(event, copy, rid):
    # Deterministic ID (f"{run_id}:{event}") + existence check => idempotent
    # append. Callers always notify BEFORE ledger_append: a crash between the
    # two is safe on re-run (notify skips the duplicate, ledger appends once).
    nid = f"{rid}:{event}"
    if notif_has_id(nid):
        return
    rec = {"id": nid, "run_id": rid, "workstream": workstream,
           "event": event, "copy": copy, "created_at": NOW, "delivered_at": None}
    with open(notif_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def audit(msg):
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(f"{NOW} {invoker} apply-envelope {msg}\n")

def save_cp(cp):
    write_atomic(cp_path, json.dumps(cp, indent=2) + "\n")

# --- 1. checkpoint must exist -------------------------------------------
cp = load_json(cp_path)
if cp is None:
    ledger_append(run_id)
    audit(f"workstream={workstream} run={run_id} IGNORED_NO_CHECKPOINT (ledger-appended)")
    print("IGNORED_NO_CHECKPOINT")
    sys.exit(0)

# --- 2. exactly-once ledger check ----------------------------------------
if ledger_has(run_id):
    print("ALREADY_APPLIED")
    sys.exit(0)

env = load_json(env_path)
item_id = env.get("item_id") if isinstance(env, dict) else None
blog_exists = os.path.exists(backlog_path)
def safe_title(iid):
    try:
        return bl.title(backlog_path, iid) if blog_exists else None
    except OSError:
        return None
title = safe_title(item_id) or (item_id or "?")

def finish_parked(event, questions, copy, result, needs_review=None):
    cp["state"] = "parked"
    cp["parked_at"] = NOW
    cp["questions"] = questions
    # Notify BEFORE ledger (crash-safe with idempotent notify, M1).
    notify(event, copy, run_id)
    ledger_append(run_id)
    if needs_review is not None:
        cp["needs_review"] = needs_review
    save_cp(cp)
    audit(f"workstream={workstream} run={run_id} status={event} item={item_id} -> parked")
    print(result)

# --- 3. unparseable envelope: park + notify, fail closed ------------------
if not isinstance(env, dict) or resolved_status(env) not in TERMINAL or not isinstance(item_id, str):
    q = "I couldn't understand the run's result \u2014 nothing was applied."
    finish_parked("unknown", [q], q, "APPLIED_UNKNOWN")
    sys.exit(0)

# --- 4. stop-path exception: paused/stopping + run stopped -> ledger only --
if run_status == "stopped" and cp.get("state") in ("paused", "stopping"):
    ledger_append(run_id)
    audit(f"workstream={workstream} run={run_id} LEDGER_ONLY (stopped while {cp.get('state')}; stop-verify path owns the outcome)")
    print("LEDGER_ONLY")
    sys.exit(0)

# --- 5. superseded: envelope is for an item this workstream moved past ----
if item_id != cp.get("current_item"):
    ledger_append(run_id)
    audit(f"workstream={workstream} run={run_id} SUPERSEDED item={item_id} current={cp.get('current_item')}")
    print("SUPERSEDED")
    sys.exit(0)

status = resolved_status(env)
chain_armed = None

if status == "done":
    done_items = (env.get("reconciliations") or {}).get("done_items") or [item_id]
    # The review gate (if any) is satisfied by completion: clear needs_review.
    # NOTE: needs_review must also be cleared when a NEW run_id is recorded on
    # this checkpoint (relaunch/resume), i.e. in lib/confirm_launch.py,
    # lib/prepare_launch.py and lib/adopt_or_relaunch.py where cp["run_id"] is
    # assigned, and in the supervisor reply-handling "go"/"retry"/"resume"
    # paths that unpark a workstream. Those are outside this script's scope.
    cp.pop("needs_review", None)
    if blog_exists:
        for did in done_items:
            if isinstance(did, str):
                try:
                    bl.remove(backlog_path, did)
                except OSError:
                    pass
    if workstream.startswith("pin-"):
        tomb = {"workstream": workstream,
                "chat_id": (cp.get("chats") or [None])[0],
                "item_id": cp.get("current_item"),
                "completed_at": NOW, "one_shot_complete": True,
                "generation": cp.get("generation", 1)}
        write_atomic(os.path.join(projdir, "tombstones", workstream + ".json"),
                     json.dumps(tomb, indent=2) + "\n")
        try: os.unlink(cp_path)
        except OSError: pass
        notify("done", f"Done: {title}. Workstream complete.", run_id)
        ledger_append(run_id)
        audit(f"workstream={workstream} run={run_id} done item={item_id} -> one_shot tombstone")
        print("APPLIED_DONE_TOMBSTONED")
        sys.exit(0)
    if cp.get("state") == "paused":
        # Late done on a paused workstream: reconcile state only, never chain.
        notify("done", f"Done: {title} (finished while paused).", run_id)
        ledger_append(run_id)
        save_cp(cp)
        audit(f"workstream={workstream} run={run_id} done item={item_id} while paused (no chain)")
        print("APPLIED_DONE")
        sys.exit(0)
    nxt = None if no_chain else (bl.top_open(backlog_path) if blog_exists else None)
    if nxt:
        nxt_title = safe_title(nxt) or nxt
        cp["chain_intent"] = {"next_item": nxt, "armed_at": NOW, "claim": None}
        notify("done", f"Done: {title}. Starting {nxt_title} next.", run_id)
        chain_armed = nxt
    elif no_chain:
        cp["chain_intent"] = None
        notify("done", f"Done: {title}. Recorded (no chain -- reconcile only).", run_id)
    else:
        cp["chain_intent"] = None
        notify("done", f"Done: {title}. Backlog is empty.", run_id)
    ledger_append(run_id)
    save_cp(cp)
    audit(f"workstream={workstream} run={run_id} done item={item_id} chain={chain_armed} no_chain={no_chain}")
    print("APPLIED_DONE")
    if chain_armed:
        print(f"CHAIN_ARMED {chain_armed}")
elif status in ("blocked", "awaiting-approval"):
    qs = env.get("questions") or []
    qs = [str(q) for q in qs] if isinstance(qs, list) else [str(qs)]
    copy = "\n".join(qs) if qs else "(no questions)"
    nr = None
    # needs-review convention (M4, envelope part): the worker hit a develop-skill
    # review gate and returned status "blocked" with
    # blocked_details = {"review_kind": "plan"|"code", "artifact_path": "..."}.
    # Park as usual, but flag the checkpoint so the supervisor knows a
    # fresh-context reviewer must be spawned before relaunching the worker.
    # needs_review is cleared by the done branch above and must also be cleared
    # whenever a new run_id is recorded (relaunch) or the workstream resumes.
    details = env.get("blocked_details")
    if status == "blocked" and isinstance(details, dict) and details.get("review_kind") in ("plan", "code"):
        rk = details.get("review_kind")
        artifact = details.get("artifact_path") or copy
        copy = f"Item {title} is ready for {rk} review. {artifact}"
        nr = {"review_kind": rk, "artifact_path": details.get("artifact_path"),
              "requested_at": NOW, "run_id": run_id}
    finish_parked("parked", qs, copy, "APPLIED_PARKED", needs_review=nr)
elif status == "failed":
    summary = str(env.get("failure_summary") or "")
    qs = env.get("questions")
    qs = [str(q) for q in qs] if isinstance(qs, list) and qs else [
        f"The run for {title} failed: {summary}. Reply retry to try again, "
        "skip to move it to the bottom, or drop to remove it."]
    finish_parked("failed", qs, "\n".join(qs), "APPLIED_FAILED")
PYEOF
  exit $?
fi

# --- outer: validate, then run under the project mutex --------------------
if [ $# -lt 4 ]; then
  echo "usage: apply-envelope.sh <project> <workstream> <envelope.json> <run-id> [--run-status <status>] [--no-chain]" >&2
  exit 2
fi
_project="$1"; _workstream="$2"; _envelope="$3"; _run_id="$4"; shift 4
_run_status=""
_no_chain=""
while [ $# -gt 0 ]; do
  case "$1" in
    --run-status) _run_status="${2:?--run-status needs a value}"; shift 2 ;;
    --no-chain) _no_chain="1"; shift ;;
    *) echo "usage: apply-envelope.sh <project> <workstream> <envelope.json> <run-id> [--run-status <status>] [--no-chain]" >&2; exit 2 ;;
  esac
done
if ! [[ "$_project" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then echo "apply-envelope.sh: bad project slug" >&2; exit 2; fi
if ! [[ "$_workstream" =~ ^(default|pin-[a-z0-9][a-z0-9-]*)$ ]]; then echo "apply-envelope.sh: bad workstream" >&2; exit 2; fi
[ -f "$_envelope" ] || { echo "apply-envelope.sh: envelope file not found: $_envelope" >&2; exit 2; }
[ -n "$_run_id" ] || { echo "apply-envelope.sh: empty run-id" >&2; exit 2; }

"$SCRIPTS/mutex.sh" "$_project" -- "$SCRIPTS/apply-envelope.sh" __under_lock \
  "$_project" "$_workstream" "$_envelope" "$_run_id" "$_run_status" "$_no_chain"
