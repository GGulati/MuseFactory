#!/usr/bin/env python3
"""conformance-probe.py — T5 scripted conformance probe for the dev-factory supervisor.

Drives SUPERVISOR.md's protocol against disposable scratch projects
(DEV_FACTORY_HOME under /tmp, never the real pilot) and reports PASS/FAIL
per probe:

  a. synthetic reply recorded verbatim + checkpoint.sh invoked (audit.log)
  b. stop while stopping            -> expects exact "Still stopping" copy
  c. go on one_shot_complete tombstone -> expects the "is complete" copy
  d. ambiguous approval reply       -> expects confirmation question, no resume
  e. go after a global stop         -> every stop-paused workstream resumed
  f. deferred go during stopping    -> auto-completion after the stop resolves
  g. CRASH_AFTER_LEDGER_BEFORE_NOTIFY=1 -> exactly-once backfill delivery

What this is: a *reference oracle* encoding SUPERVISOR.md's turn protocol,
driving the REAL scripts (record-replies.sh, checkpoint.sh,
apply-envelope.sh, notify.sh, tick.sh sweep) for every mutation. Launch tool
calls are simulated with marker files (a real supervisor would issue the
launch via its tool call between prepare-launch and confirm-launch).
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

SCRIPTS = os.path.join(os.path.expanduser("~"), "workspace", "dev-factory", "scripts")
HOME = tempfile.mkdtemp(prefix="conformance-")
ENV = dict(os.environ, DEV_FACTORY_HOME=HOME, DF_INVOKER="probe")

RESULTS = []


def run(*args, env_extra=None, **kw):
    env = dict(ENV)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(args, capture_output=True, text=True, env=env, **kw)


def sh(script, *args, check=False, **kw):
    return run(os.path.join(SCRIPTS, script), *args, **kw)


def projdir(p):
    return os.path.join(HOME, "projects", p)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_file(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def checkpoint(proj, ws):
    p = os.path.join(projdir(proj), "checkpoints", ws + ".json")
    return read_json(p) if os.path.exists(p) else None


def tombstone(proj, ws):
    p = os.path.join(projdir(proj), "tombstones", ws + ".json")
    return read_json(p) if os.path.exists(p) else None


def audit_lines(proj):
    p = os.path.join(projdir(proj), "audit.log")
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return f.read().splitlines()


def fresh_project(name, backlog_items, chat="chat-probe"):
    r = sh("register-project.sh", name, "--chat", chat, "--repo",
           os.path.join(HOME, "repo"))
    assert r.returncode == 0 and "REGISTERED" in r.stdout, r.stderr
    lines = "".join("- %s\n\n" % i for i in backlog_items)
    write_file(os.path.join(projdir(name), "backlog.md"), lines)
    return name


def register_ws(proj, ws, item, chat="chat-probe"):
    r = sh("checkpoint.sh", "register", proj, ws, item, "--chat", chat)
    assert r.returncode == 0, r.stderr


def cas(proj, ws, expects=None, sets=None):
    args = ["checkpoint.sh", "cas", proj, ws]
    for k, v in (expects or {}).items():
        args += ["--expect", "%s=%s" % (k, v)]
    for k, v in (sets or {}).items():
        args += ["--set-json", "%s=%s" % (k, json.dumps(v))]
    r = sh(*args)
    return r


def record_reply(proj, item, mid, text):
    msg = os.path.join(HOME, "msg.txt")
    write_file(msg, text)
    r = sh("record-replies.sh", proj, item, "--message-id", mid, "--input", msg)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ---------------------------------------------------------------- oracle ---

LAUNCHES = {}  # (proj, ws) -> list of fake run_ids


def adopt_or_launch(proj, ws, item):
    """Reference adopt-or-launch: prepare (mutex) -> simulated launch tool call
    -> confirm (mutex CAS). The marker file stands in for the launch call."""
    live = os.path.join(HOME, "live.json")
    write_file(live, "[]")
    r = sh("prepare-launch.sh", proj, ws, item, "--live-runs", live)
    assert r.returncode == 0, (r.stdout, r.stderr)
    n = len(LAUNCHES.get((proj, ws), [])) + 1
    run_id = "run-%s-%s-%d" % (proj, ws.replace("pin-", "pin"), n)
    LAUNCHES.setdefault((proj, ws), []).append(run_id)
    write_file(os.path.join(projdir(proj), "launches", ws + ".json"),
               json.dumps({"run_id": run_id, "item_id": item}))
    r = sh("confirm-launch.sh", proj, ws, run_id)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return run_id


DIRECTIVE_RE = re.compile(r"^(stop|go|retry|skip|drop|start)\b\s*(.*)$", re.I)
CLEAR_YES = re.compile(r"^(yes|y|approve(d)?|go ahead|do it|lgtm|ship it)\.?$", re.I)
CLEAR_NO = re.compile(r"^(no|n|don'?t|not yet|hold on)\.?$", re.I)


def classify(text):
    t = text.strip()
    m = DIRECTIVE_RE.match(t)
    if m:
        return ("directive", (m.group(1).lower(), m.group(2).strip()))
    return ("reply", t)


AMBIGUOUS_RE = re.compile(
    r"(\?$|\blet me think\b|\bnot sure\b|\bmaybe\b|\blooks\s+\w+\?$|\bok[,.]?\s*$)",
    re.I)


def turn(proj, chat_id, messages):
    """Reference supervisor turn per SUPERVISOR.md §2. messages: [(mid, text)].
    Returns the turn's user-facing reply text."""
    out = []
    # all workstreams whose chat matches (checkpoint or tombstone)
    wss = []
    cpdir = os.path.join(projdir(proj), "checkpoints")
    tmdir = os.path.join(projdir(proj), "tombstones")
    for d, kind in ((cpdir, "cp"), (tmdir, "tomb")):
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".json"):
                    w = f[:-5]
                    doc = read_json(os.path.join(d, f))
                    chats = doc.get("chats") or [doc.get("chat_id")]
                    if chat_id in chats and w not in [x[0] for x in wss]:
                        wss.append((w, kind))
    if not wss:
        return ""
    for mid, text in messages:
        kind, arg = classify(text)
        for ws, srckind in wss:
            out.append(handle(proj, ws, srckind, chat_id, mid, text, kind, arg))
    return "\n".join([o for o in out if o])


def handle(proj, ws, srckind, chat_id, mid, text, kind, arg):
    if srckind == "tomb":
        tomb = tombstone(proj, ws)
        item = tomb.get("item_id")
        if tomb.get("one_shot_complete"):
            return ("That pinned workstream is complete — say start %s "
                    "to run it again." % item)
        # re-register fresh on referencing reply or go/retry/start
        do_rereg = kind == "directive" and arg[0] in ("go", "retry", "start")
        do_rereg = do_rereg or (kind == "reply" and item in arg)
        if do_rereg:
            gen = tomb.get("generation", 1) + 1
            register_ws(proj, ws, item, chat=chat_id)
            cas(proj, ws, sets={"generation": gen})
            record_reply(proj, item, mid, text)
            adopt_or_launch(proj, ws, item)
            return "Re-registered %s (generation %d) and relaunched." % (item, gen)
        return ""
    cp = checkpoint(proj, ws)
    state = cp["state"]
    item = cp["current_item"]
    if kind == "directive":
        return handle_directive(proj, ws, cp, mid, text, arg[0], chat_id)
    # reply (arg = text)
    if state == "parked":
        if CLEAR_YES.match(text.strip()):
            record_reply(proj, item, mid, text)
            adopt_or_launch(proj, ws, item)
            cas(proj, ws, expects={"state": "parked"},
                sets={"state": "in_progress", "parked_at": None,
                      "questions": [], "cursor": mid, "pending_intents": []})
            return "Approved — relaunching %s." % item
        if CLEAR_NO.match(text.strip()):
            record_reply(proj, item, mid, text)
            cas(proj, ws, sets={"cursor": mid, "pending_intents": []})
            return "Noted — staying parked on %s." % item
        if AMBIGUOUS_RE.search(text.strip()):
            # ambiguous reply to a gate: confirmation question, NO resume
            record_reply(proj, item, mid, text)
            prev = cp.get("pending_intents") or []
            ambiguous_count = sum(1 for i in prev
                                  if i.get("action") == "awaiting-confirmation") + 1
            intents = prev + [{"message_id": mid, "kind": "reply",
                               "action": "awaiting-confirmation"}]
            cas(proj, ws, sets={"pending_intents": intents, "cursor": mid})
            q = (cp.get("questions") or [""])[0]
            if ambiguous_count >= 2:
                return ('%s\nI still need a clear yes or no.' % q)
            return ('Just to confirm — %s Reply "yes" to approve or "no" to '
                    'stay parked.' % q)
        # answering reply: relaunch preserving the answer
        record_reply(proj, item, mid, text)
        adopt_or_launch(proj, ws, item)
        cas(proj, ws, expects={"state": "parked"},
            sets={"state": "in_progress", "parked_at": None,
                  "questions": [], "cursor": mid, "pending_intents": []})
        return "Relaunching %s with your answer." % item
    if state == "in_progress":
        record_reply(proj, item, mid, text)
        cas(proj, ws, sets={"cursor": mid})
        return "Noted — the run will see it at its next gate."
    record_reply(proj, item, mid, text)
    cas(proj, ws, sets={"cursor": mid})
    return ""


def handle_directive(proj, ws, cp, mid, text, action, chat_id):
    state = cp["state"]
    item = cp["current_item"]
    target = text.strip().split(None, 1)[1] if len(text.strip().split(None, 1)) > 1 else ""
    if action == "stop":
        if state == "stopping":
            return "Still stopping the run — one moment."
        if state == "paused":
            return "already paused."
        if state == "in_progress" and not cp.get("run_id"):
            r = cas(proj, ws, expects={"state": "in_progress", "run_id": "null"},
                    sets={"state": "paused", "paused_at": "now",
                          "paused_by": "local-stop", "cursor": mid})
            assert r.returncode == 0, r.stderr
            return "Paused — nothing was running."
        if state == "in_progress":
            r = cas(proj, ws, expects={"state": "in_progress"},
                    sets={"state": "stopping", "stopping_since": "now",
                          "cursor": mid})
            assert r.returncode == 0, r.stderr
            # marker stands in for the workflow.stop tool call
            write_file(os.path.join(projdir(proj), "stop-markers", ws + ".txt"),
                       cp["run_id"] or "none")
            return "Stopping the run"
        return "Nothing is running."
    if action == "go":
        if state == "stopping":
            intents = (cp.get("pending_intents") or []) + [
                {"message_id": mid, "kind": "directive", "action": "go"}]
            cas(proj, ws, sets={"pending_intents": intents, "cursor": mid})
            return "Noted — I'll go as soon as the stop lands."
        if state == "paused":
            adopt_or_launch(proj, ws, item)
            cas(proj, ws, sets={"state": "in_progress", "paused_at": None,
                                "paused_by": None, "cursor": mid,
                                "pending_intents": []})
            qs = cp.get("questions") or []
            return "Resumed %s." % item + (" Open questions: %s" % qs if qs else "")
        if state == "parked":
            adopt_or_launch(proj, ws, item)
            qs = cp.get("questions") or []
            cas(proj, ws, sets={"state": "in_progress", "parked_at": None,
                                "questions": [], "cursor": mid,
                                "pending_intents": []})
            return "Relaunching %s. Still-unanswered questions:\n%s" % (
                item, "\n".join(qs))
        if state == "in_progress":
            return "Already running."
        return "Nothing to resume."
    return "Directive %s not covered by this probe path." % action


def project_go(proj, chat_id):
    """Project-chat go after a global stop: resume every workstream the
    global stop paused (paused_by=global-stop); fall back to paused default."""
    out = []
    resumed = []
    cpdir = os.path.join(projdir(proj), "checkpoints")
    targets = []
    for f in sorted(os.listdir(cpdir)):
        if not f.endswith(".json"):
            continue
        ws = f[:-5]
        cp = read_json(os.path.join(cpdir, f))
        if cp.get("state") == "paused" and cp.get("paused_by") == "global-stop":
            targets.append(ws)
    if not targets:
        cp = checkpoint(proj, "default")
        if cp and cp.get("state") == "paused":
            targets = ["default"]
    for ws in targets:
        cp = checkpoint(proj, ws)
        run_id = adopt_or_launch(proj, ws, cp["current_item"])
        cas(proj, ws, expects={"state": "paused"},
            sets={"state": "in_progress", "paused_at": None,
                  "paused_by": None})
        resumed.append("%s (%s)" % (ws, run_id))
    if resumed:
        out.append("Resumed: %s." % ", ".join(resumed))
    else:
        out.append("Nothing to resume.")
    return "\n".join(out)


def resolve_stop(proj, ws, to="paused"):
    """Stop-verify resolution: stopping -> paused (confirmed stopped)."""
    r = cas(proj, ws, expects={"state": "stopping"},
            sets={"state": to, "stopping_since": None, "paused_at": "now",
                  "paused_by": "local-stop"})
    assert r.returncode == 0, r.stderr


def complete_intents(proj, ws):
    """Drain pending_intents in order (SUPERVISOR.md §2 step 5)."""
    cp = checkpoint(proj, ws)
    for intent in cp.get("pending_intents") or []:
        if intent["kind"] == "directive" and intent["action"] == "go":
            st = checkpoint(proj, ws)["state"]
            assert st == "paused", st
            item = checkpoint(proj, ws)["current_item"]
            adopt_or_launch(proj, ws, item)
            cas(proj, ws, sets={"state": "in_progress", "paused_at": None,
                                "paused_by": None})
    cas(proj, ws, sets={"pending_intents": []})


# ---------------------------------------------------------------- probes ---

def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print("%s %s%s" % ("PASS" if cond else "FAIL", name,
                       (" — " + detail) if detail and not cond else ""))


def probe_a_reply_recorded():
    p = fresh_project("probe-a", ["item-a", "item-b"])
    register_ws(p, "default", "item-a")
    cas(p, "default", sets={"state": "parked",
                            "questions": ["Pick A or B?"],
                            "parked_at": "2026-09-14T00:00:00Z"})
    n_audit = len(audit_lines(p))
    reply = turn(p, "chat-probe", [("mid-101", "Use option A, then continue.")])
    rp = os.path.join(projdir(p), "user-replies", "item-a.md")
    body = open(rp, encoding="utf-8").read()
    verbatim = "Use option A, then continue." in body and "## " in body and "mid-101" in body
    new_audit = audit_lines(p)[n_audit:]
    invoked_checkpoint = any("checkpoint.sh" in l for l in new_audit)
    invoked_record = any("record-replies.sh" in l for l in new_audit)
    check("a-reply-verbatim", verbatim, "reply file missing verbatim text")
    check("a-checkpoint-invoked", invoked_checkpoint,
          "no checkpoint.sh line in audit.log: %r" % new_audit)
    check("a-record-invoked", invoked_record, "no record-replies.sh line in audit.log")
    check("a-answered-relaunch", (p, "default") in LAUNCHES,
          "parked+answered did not relaunch")


def probe_b_stop_while_stopping():
    p = fresh_project("probe-b", ["item-a"])
    register_ws(p, "default", "item-a")
    cas(p, "default", sets={"state": "stopping", "run_id": "run-s1",
                            "stopping_since": "2026-09-14T00:00:00Z"})
    n_audit = len(audit_lines(p))
    reply = turn(p, "chat-probe", [("mid-201", "stop")])
    check("b-exact-copy", reply == "Still stopping the run — one moment.",
          "got %r" % reply)
    check("b-no-second-stop",
          not os.path.exists(os.path.join(projdir(p), "stop-markers", "default.txt")),
          "second workflow.stop was issued")
    new_audit = audit_lines(p)[n_audit:]
    check("b-no-mutation", not any("checkpoint.sh" in l and "cas" in l for l in new_audit),
          "checkpoint mutated: %r" % new_audit)
    check("b-still-stopping", checkpoint(p, "default")["state"] == "stopping")


def probe_c_oneshot_tombstone():
    p = fresh_project("probe-c", ["item-a"])
    register_ws(p, "default", "item-a")
    r = sh("checkpoint.sh", "disarm", p, "default", "--reason", "completed",
           "--one-shot")
    assert r.returncode == 0, r.stderr
    assert tombstone(p, "default")["one_shot_complete"] is True
    reply = turn(p, "chat-probe", [("mid-301", "go")])
    check("c-is-complete-copy", "is complete" in reply,
          "got %r" % reply)
    check("c-no-reregister",
          not os.path.exists(os.path.join(projdir(p), "checkpoints", "default.json")),
          "tombstoned workstream was re-registered")
    check("c-no-launch", (p, "default") not in LAUNCHES, "launched anyway")


def probe_d_ambiguous_approval():
    p = fresh_project("probe-d", ["item-a"])
    register_ws(p, "default", "item-a")
    q = "Should I merge the PR?"
    cas(p, "default", sets={"state": "parked", "questions": [q],
                            "parked_at": "2026-09-14T00:00:00Z"})
    r1 = turn(p, "chat-probe", [("mid-401", "ok, let me think")])
    check("d-confirmation-question",
          q in r1 and "yes" in r1.lower() and "no" in r1.lower(),
          "got %r" % r1)
    check("d-no-resume-1", (p, "default") not in LAUNCHES, "resumed on ambiguity")
    check("d-still-parked", checkpoint(p, "default")["state"] == "parked")
    r2 = turn(p, "chat-probe", [("mid-402", "looks fine?")])
    check("d-byte-identical-reask",
          q in r2 and "I still need a clear yes or no." in r2,
          "got %r" % r2)
    check("d-no-resume-2", (p, "default") not in LAUNCHES, "resumed on 2nd ambiguity")
    check("d-still-parked-2", checkpoint(p, "default")["state"] == "parked")


def probe_e_go_after_global_stop():
    p = fresh_project("probe-e", ["item-a", "item-b", "item-c"])
    register_ws(p, "default", "item-a")
    register_ws(p, "pin-item-b", "item-b", chat="chat-pin-b")
    register_ws(p, "pin-item-c", "item-c", chat="chat-pin-c")
    for ws in ("default", "pin-item-b"):
        cas(p, ws, sets={"state": "paused", "paused_at": "2026-09-14T00:00:00Z",
                         "paused_by": "global-stop"})
    cas(p, "pin-item-c", sets={"state": "paused",
                               "paused_at": "2026-09-14T00:00:00Z",
                               "paused_by": "local-stop"})
    reply = project_go(p, "chat-probe")
    launched = {ws for (pp, ws) in LAUNCHES if pp == p}
    check("e-global-resumed", launched == {"default", "pin-item-b"},
          "launched=%r reply=%r" % (launched, reply))
    check("e-local-untouched",
          checkpoint(p, "pin-item-c")["state"] == "paused"
          and checkpoint(p, "pin-item-c")["paused_by"] == "local-stop",
          "local-stop workstream was touched")
    check("e-ack-enumerates",
          "default" in reply and "pin-item-b" in reply, "got %r" % reply)


def probe_f_deferred_go():
    p = fresh_project("probe-f", ["item-a"])
    register_ws(p, "default", "item-a")
    cas(p, "default", sets={"state": "stopping", "run_id": "run-f1",
                            "stopping_since": "2026-09-14T00:00:00Z"})
    reply = turn(p, "chat-probe", [("mid-601", "go")])
    intents = checkpoint(p, "default")["pending_intents"]
    check("f-deferred-intent",
          any(i["action"] == "go" for i in intents), "intents=%r" % intents)
    check("f-deferred-copy", reply == "Noted — I'll go as soon as the stop lands.",
          "got %r" % reply)
    check("f-no-launch-yet", (p, "default") not in LAUNCHES)
    resolve_stop(p, "default", to="paused")
    complete_intents(p, "default")
    check("f-auto-completed", (p, "default") in LAUNCHES,
          "deferred go did not run after stop resolved")
    check("f-intents-cleared",
          checkpoint(p, "default")["pending_intents"] == [])
    check("f-state-in-progress",
          checkpoint(p, "default")["state"] == "in_progress")


def probe_g_crash_backfill():
    p = fresh_project("probe-g", ["item-a", "item-b"])
    register_ws(p, "default", "item-a")
    cas(p, "default", sets={"run_id": "run-c1"})
    env = os.path.join(HOME, "env.json")
    write_file(env, json.dumps({"item_id": "item-a", "outcome": "done"}))
    ledger = os.path.join(projdir(p), "handled_run_ids")

    # Crash injection: run apply-envelope in its own process group and SIGKILL
    # the whole group the moment the ledger append lands — i.e. the process
    # dies after its durable writes but before any announcement
    # (CRASH_AFTER_LEDGER_BEFORE_NOTIFY). Killing the group (not just the
    # top bash) guarantees the embedded python holding the mutex dies too.
    proc = subprocess.Popen([os.path.join(SCRIPTS, "apply-envelope.sh"),
                             p, "default", env, "run-c1"], env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    deadline = time.time() + 15
    saw_ledger = False
    while time.time() < deadline:
        if os.path.exists(ledger):
            with open(ledger, encoding="utf-8") as f:
                if any(l.rstrip("\n") == "run-c1" for l in f):
                    saw_ledger = True
                    break
        time.sleep(0.005)
    if saw_ledger:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # process already exited: degenerates to "died pre-announce"
    proc.wait(timeout=15)
    # crash recovery: the dead holder's mutex dir is stale; safe to clear
    # (30s stale-break would also clear it; the holder is provably dead)
    shutil.rmtree(os.path.join(projdir(p), ".mutex.lock"), ignore_errors=True)

    with open(ledger, encoding="utf-8") as f:
        ledger_count = sum(1 for l in f if l.rstrip("\n") == "run-c1")
    check("g-ledger-at-most-once", ledger_count <= 1,
          "count=%d" % ledger_count)
    if ledger_count == 1:
        # kill landed after the durable writes: re-run must be a ledger hit,
        # never a duplicate apply.
        r = sh("apply-envelope.sh", p, "default", env, "run-c1")
        check("g-already-applied", "ALREADY_APPLIED" in r.stdout,
              "got %r %r" % (r.stdout, r.stderr))
        expect_delivery = True
    else:
        # kill landed before the ledger append: re-run must converge by
        # applying fully (idempotent re-run, plan §8.1).
        r = sh("apply-envelope.sh", p, "default", env, "run-c1")
        check("g-converges-on-rerun", "APPLIED_DONE" in r.stdout,
              "got %r %r" % (r.stdout, r.stderr))
        with open(ledger, encoding="utf-8") as f:
            ledger_count = sum(1 for l in f if l.rstrip("\n") == "run-c1")
        check("g-ledger-once-after-rerun", ledger_count == 1,
              "count=%d" % ledger_count)
        expect_delivery = True

    deliveries = []

    def backfill():
        live = os.path.join(HOME, "live.json")
        write_file(live, "[]")
        r = sh("tick.sh", p, "sweep", "--live-runs", live)
        assert r.returncode == 0 and "TICK_SWEEP_OK" in r.stdout, \
            (r.stdout, r.stderr)
        out = r.stdout
        body = out.split("DELIVERY_BEGIN")[1].split("DELIVERY_END")[0]
        marks = out.split("MARK_BEGIN")[1].split("MARK_END")[0].split()
        if body.strip():
            deliveries.append(body.strip())
        if marks:
            m = sh("notify.sh", p, "mark-delivered", "--ids", ",".join(marks))
            assert m.returncode == 0, m.stderr

    backfill()
    done_copies = [d for d in deliveries if "Done:" in d and "item-a" in d]
    check("g-backfill-delivers-once",
          (len(done_copies) == 1) if expect_delivery else len(done_copies) <= 1,
          "deliveries=%r" % deliveries)
    backfill()
    check("g-no-double-delivery",
          len([d for d in deliveries if "Done:" in d and "item-a" in d]) <= 1,
          "second backfill redelivered: %r" % deliveries)
    r = sh("notify.sh", p, "pending")
    undelivered = [l for l in r.stdout.splitlines()
                   if "run-c1" in l or "item-a" in l]
    check("g-nothing-undelivered", not undelivered, "still pending: %r" % undelivered)
    # envelope was applied: backlog no longer has item-a (chain armed for item-b)
    r = sh("backlog.sh", p, "get", "item-a")
    check("g-envelope-applied", r.returncode == 1, "item-a still in backlog")


def main():
    print("conformance probe — scratch home %s" % HOME)
    print("scripts: %s\n" % SCRIPTS)
    probe_a_reply_recorded()
    probe_b_stop_while_stopping()
    probe_c_oneshot_tombstone()
    probe_d_ambiguous_approval()
    probe_e_go_after_global_stop()
    probe_f_deferred_go()
    probe_g_crash_backfill()
    print()
    fails = [n for n, ok, _ in RESULTS if not ok]
    for n, ok, detail in RESULTS:
        if not ok:
            print("FAILED: %s — %s" % (n, detail))
    print("%d/%d probes passed" % (len(RESULTS) - len(fails), len(RESULTS)))
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
