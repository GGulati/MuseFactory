#!/usr/bin/env bash
# checkpoint.sh — checkpoint store for dev-factory workstreams.
# Reads are lock-free (single atomic-rename files); every mutation runs
# exactly one mutex.sh acquisition around a python read-modify-write.
#
#   checkpoint.sh get <project> <workstream>
#   checkpoint.sh register <project> <workstream> <item-id> --chat <chat-id>
#   checkpoint.sh cas <project> <workstream> [--expect <dotpath>=<string>]...
#                                              [--set-json <dotpath>=<json>]...
#   checkpoint.sh claim-chain <project> <workstream> --expect-next <item>
#                                                     --token <tok> --by <turn|tick>
#   checkpoint.sh release-chain <project> <workstream> --expect-token <tok>
#   checkpoint.sh disarm <project> <workstream> --reason <disarmed|completed> [--one-shot]
#   checkpoint.sh list <project>
#   checkpoint.sh get-tombstone <project> <workstream>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

usage() { echo "usage: checkpoint.sh {get|register|cas|claim-chain|release-chain|disarm|list|get-tombstone} <project> ..." >&2; exit 2; }

op="${1:-}"
case "$op" in
  get|register|cas|claim-chain|release-chain|disarm|list|get-tombstone) ;;
  *) usage ;;
esac
shift
project="${1:-}"; [ -n "$project" ] || usage; shift
projdir="$(df_projdir "$project")" || exit 2

# ---- read-only paths (no mutex) -------------------------------------------
case "$op" in
  get)
    ws="$(df_validate_workstream "${1:-}")" || exit 2
    python3 - "$projdir/checkpoints/$ws.json" <<'PYEOF'
import sys, json
try:
    print(json.dumps(json.load(open(sys.argv[1])), indent=2, sort_keys=True))
except FileNotFoundError:
    print("checkpoint.sh: no checkpoint for workstream", file=sys.stderr)
    sys.exit(1)
PYEOF
    exit "$?"
    ;;
  get-tombstone)
    ws="$(df_validate_workstream "${1:-}")" || exit 2
    python3 - "$projdir/tombstones/$ws.json" <<'PYEOF'
import sys, json
try:
    print(json.dumps(json.load(open(sys.argv[1])), indent=2, sort_keys=True))
except FileNotFoundError:
    print("checkpoint.sh: no tombstone for workstream", file=sys.stderr)
    sys.exit(1)
PYEOF
    exit "$?"
    ;;
  list)
    for f in "$projdir/checkpoints"/*.json; do
      [ -e "$f" ] || continue
      basename "$f" .json
    done
    exit 0
    ;;
esac

# ---- mutating paths: exactly one mutex acquisition ------------------------
# op-specific args are passed through to the embedded python program.
case "$op" in
  register|cas|claim-chain|release-chain|disarm) ;;
  *) usage ;;
esac

ws=""
if [ "$#" -ge 1 ]; then
  ws="$(df_validate_workstream "$1")" || exit 2
fi

exec "$SCRIPT_DIR/mutex.sh" "$project" -- python3 - "$projdir" "$project" "$op" "$@" <<'PYEOF'
import sys, os, re, json, tempfile, datetime, uuid

projdir, project, op = sys.argv[1], sys.argv[2], sys.argv[3]
rest = sys.argv[4:]
SCRIPT = "checkpoint.sh"
INVOKER = os.environ.get("DF_INVOKER", "cli")

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def ckpt_path(ws):
    return os.path.join(projdir, "checkpoints", ws + ".json")

def die(msg, code):
    print(f"{SCRIPT}: {msg}", file=sys.stderr)
    sys.exit(code)

def audit(summary):
    with open(os.path.join(projdir, "audit.log"), "a") as f:
        f.write(f"{now()} {INVOKER} {SCRIPT} {summary}\n")
        f.flush()
        os.fsync(f.fileno())

def atomic_write(path, obj):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
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

def load_checkpoint(ws):
    try:
        with open(ckpt_path(ws)) as f:
            return json.load(f)
    except FileNotFoundError:
        die(f"no checkpoint for workstream '{ws}'", 1)

def resolve(obj, dotpath):
    cur = obj
    for part in dotpath.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur

def canon(v):
    # Compare-as-strings: JSON null (or a missing path) renders as "null".
    if v is None:
        return "null"
    if isinstance(v, str):
        return v
    return json.dumps(v, separators=(",", ":"), sort_keys=True)

def assign(obj, dotpath, value):
    parts = dotpath.split(".")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value

def cas_abort(detail):
    print(f"CAS_ABORT: {detail}", file=sys.stderr)
    sys.exit(3)

def valid_slug(v):
    return re.fullmatch(r"[a-z0-9][a-z0-9-]*", v or "") is not None

# ---- op: register ---------------------------------------------------------
if op == "register":
    # args: <workstream> <item-id> --chat <chat-id>
    ws, item_id = rest[0], rest[1] if len(rest) > 1 else ""
    chat = ""
    for i, a in enumerate(rest):
        if a == "--chat" and i + 1 < len(rest):
            chat = rest[i + 1]
    if not valid_slug(item_id):
        die(f"invalid item id '{item_id}'", 2)
    if not chat:
        die("register requires --chat <chat-id>", 2)
    path = ckpt_path(ws)
    if os.path.exists(path):
        die(f"checkpoint already exists for workstream '{ws}'", 4)
    cp = {
        "workstream": ws, "generation": 1, "chats": [chat], "project": project,
        "state": "in_progress", "current_item": item_id, "run_id": None,
        "armed_at": now(), "questions": [], "parked_at": None,
        "paused_at": None, "stopping_since": None, "stopping_by": None,
        "paused_by": None,
        "cursor": None, "pending_intents": [], "chain_intent": None,
        "death_timestamps": [], "pending_relay": [], "paused_observed_at": None,
    }
    atomic_write(path, cp)
    audit(f"register {ws} item={item_id} chat={chat}")
    print("REGISTERED")

# ---- op: cas ---------------------------------------------------------------
elif op == "cas":
    # args: <workstream> [--expect <dotpath>=<string>]... [--set-json <dotpath>=<json>]...
    ws = rest[0]
    expects, sets = [], []
    i = 1
    while i < len(rest):
        a = rest[i]
        if a in ("--expect", "--set-json"):
            i += 1
            if i >= len(rest):
                die(f"{a} requires a value", 2)
            p, eq, v = rest[i].partition("=")
            if not p or not eq:
                die(f"{a} requires <dotpath>=<value>", 2)
            if a == "--expect":
                expects.append((p, v))
            else:
                try:
                    jv = json.loads(v)
                except json.JSONDecodeError as e:
                    die(f"--set-json value is not valid JSON: {e}", 2)
                sets.append((p, jv))
        else:
            die(f"unexpected argument '{a}'", 2)
        i += 1
    cp = load_checkpoint(ws)
    for p, expected in expects:
        actual = canon(resolve(cp, p))
        if actual != expected:
            cas_abort(f"expect {p}={expected} but was {actual}")
    for p, jv in sets:
        assign(cp, p, jv)
    atomic_write(ckpt_path(ws), cp)
    audit(f"cas {ws} expects={len(expects)} sets={len(sets)}")
    print(json.dumps(cp, indent=2, sort_keys=True))

# ---- op: claim-chain ---------------------------------------------------------
elif op == "claim-chain":
    # args: <workstream> --expect-next <item> --token <tok> --by <turn|tick>
    ws = rest[0]
    expect_next = token = by = ""
    i = 1
    while i < len(rest):
        a = rest[i]
        if a in ("--expect-next", "--token", "--by"):
            i += 1
            if i >= len(rest):
                die(f"{a} requires a value", 2)
            if a == "--expect-next":
                expect_next = rest[i]
            elif a == "--token":
                token = rest[i]
            else:
                by = rest[i]
        else:
            die(f"unexpected argument '{a}'", 2)
        i += 1
    if by not in ("turn", "tick"):
        die("--by must be turn|tick", 2)
    if not token or not expect_next:
        die("claim-chain requires --expect-next and --token", 2)
    cp = load_checkpoint(ws)
    ci = cp.get("chain_intent")
    if not isinstance(ci, dict) or ci.get("next_item") != expect_next or ci.get("claim") is not None:
        cas_abort(f"chain_intent.next_item={expect_next} with unclaimed intent not present")
    ci["claim"] = {"token": token, "claimed_at": now(), "by": by}
    atomic_write(ckpt_path(ws), cp)
    audit(f"claim-chain {ws} next={expect_next} by={by}")
    print("CLAIMED")

# ---- op: release-chain -------------------------------------------------------
elif op == "release-chain":
    # args: <workstream> --expect-token <tok>
    ws = rest[0]
    token = ""
    i = 1
    while i < len(rest):
        if rest[i] == "--expect-token":
            i += 1
            if i >= len(rest):
                die("--expect-token requires a value", 2)
            token = rest[i]
        else:
            die(f"unexpected argument '{rest[i]}'", 2)
        i += 1
    if not token:
        die("release-chain requires --expect-token", 2)
    cp = load_checkpoint(ws)
    ci = cp.get("chain_intent")
    claim = ci.get("claim") if isinstance(ci, dict) else None
    if not isinstance(claim, dict) or claim.get("token") != token:
        cas_abort("chain_intent.claim.token mismatch")
    ci["claim"] = None
    atomic_write(ckpt_path(ws), cp)
    audit(f"release-chain {ws}")
    print("RELEASED")

# ---- op: disarm ---------------------------------------------------------------
elif op == "disarm":
    # args: <workstream> --reason <disarmed|completed> [--one-shot]
    ws = rest[0]
    reason, one_shot = "", False
    i = 1
    while i < len(rest):
        a = rest[i]
        if a == "--reason":
            i += 1
            if i >= len(rest):
                die("--reason requires a value", 2)
            reason = rest[i]
        elif a == "--one-shot":
            one_shot = True
        else:
            die(f"unexpected argument '{a}'", 2)
        i += 1
    if reason not in ("disarmed", "completed"):
        die("--reason must be disarmed|completed", 2)
    cp = load_checkpoint(ws)
    chats = cp.get("chats") or []
    tomb = {
        "workstream": ws,
        "chat_id": chats[0] if chats else None,
        "item_id": cp.get("current_item"),
        ("disarmed_at" if reason == "disarmed" else "completed_at"): now(),
        "one_shot_complete": bool(one_shot),
        "generation": cp.get("generation"),
    }
    atomic_write(os.path.join(projdir, "tombstones", ws + ".json"), tomb)
    os.remove(ckpt_path(ws))
    audit(f"disarm {ws} reason={reason} one_shot={one_shot}")
    print("DISARMED")

else:
    die(f"unknown op '{op}'", 2)
PYEOF
