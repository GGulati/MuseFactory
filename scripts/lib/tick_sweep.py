#!/usr/bin/env python3
"""tick sweep worker: per-project liveness sweep (plan §11).

Called by tick.sh sweep. This orchestrator never holds the project mutex
itself; every mutation goes through scripts/ entry points, each of which
serializes on the project mutex (ms-scale, CAS-validated). A few
tick-specific transitions (stopping resolution, end-of-sweep flush) run as
small python snippets under mutex.sh -- one acquisition each.

Reads (lock-free classification reads):
  checkpoints/<workstream>.json, handled_run_ids, tick-health.json,
  notifications.jsonl, backlog.md, and the --live-runs JSON array:
  [{run_id, status, heartbeat_at, started_at, completed_at, final_result,
    args:{project,item_id}}]  (prepared by the cron worker from muse.db).

Writes (all under the project mutex via scripts/):
  checkpoint transitions, ledger appends, notification records, tombstones,
  pending-launch files, tick-health.json.

Stdout protocol:
  line 1: TICK_SWEEP_OK
  DELIVERY_BEGIN / DELIVERY_END: chat copy for the project side chat
    (empty -> the worker stays silent)
  PENDING_BEGIN / PENDING_END: "<token> <workstream> <item-id>" lines --
    the worker launches the dev-factory workflow per token, using the
    pending-launch file's "workflow_args" object (the workflow's full
    fail-fast args contract; null means unresolvable -- do NOT launch,
    leave the checkpoint for the supervisor), then calls
    tick.sh confirm-launch <token> <run-id>
  MARK_BEGIN / MARK_END: space-separated notification ids the worker marks
    delivered (notify.sh mark-delivered) after its chat delivery lands
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dfstate
import backlog as bl

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMINAL = ("completed", "failed", "stopped")
LIVE = ("running", "queued", "paused")
DISARM_COPY = ("I haven't heard back in a week, so I've shelved this. "
               "Reply here any time and I'll pick it back up.")
RECOVERY_COPY = ("The database is reachable again -- no checkpoint transitions "
                 "were made during the outage; normal sweeps have resumed.")
OUTAGE_COPY = ("I can't reach the run database right now, so I'm making no "
               "checkpoint changes and no disarms until it's back. I'll keep "
               "checking.")
INCONCLUSIVE_STOP_COPY = "I couldn't confirm the stop -- the run may still be going."
FALLBACK_COPY = ("I still can't confirm the stop -- the workstream is back to "
                 "in-progress; say stop again if you want it stopped.")


def sh(*args):
    """Run a scripts/ entry point. Returns (rc, stdout)."""
    p = subprocess.run(list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    return p.returncode, p.stdout


def sh_mtx(project, *args):
    """Run argv under the project mutex. Returns (rc, stdout)."""
    return sh(os.path.join(SCRIPTS, "mutex.sh"), project, "--", *args)


def first_line(out):
    out = (out or "").strip()
    return out.split("\n", 1)[0].strip() if out else ""


def notify_lines(out):
    return [l[len("NOTIFY:"):].strip() for l in (out or "").splitlines()
            if l.startswith("NOTIFY:")]


class Sweep:
    def __init__(self, project, live_runs_file, db_unreachable):
        self.project = project
        self.projdir = dfstate.projdir(project)
        self.db_unreachable = db_unreachable
        self.ref = dfstate.now_dt()
        self.live_runs = []
        self.runs_by_id = {}
        if live_runs_file and not db_unreachable:
            for r in dfstate.load_live_runs(live_runs_file):
                if not isinstance(r, dict):
                    continue
                args = r.get("args")
                if args is None and isinstance(r.get("args_json"), dict):
                    args = r["args_json"]
                r["args"] = args if isinstance(args, dict) else {}
                self.live_runs.append(r)
                if r.get("run_id"):
                    self.runs_by_id[r["run_id"]] = r
        self.handled = self._load_handled()
        self.cps = self._load_checkpoints()
        self.health = self._load_health()
        self.anomaly_now = set()      # dedupe keys active this sweep
        # Snapshot of known anomaly keys at sweep start (key -> created_at).
        # Used for safe clearing: a key whose condition cleared is dropped
        # only if its created_at still matches (guards against clearing a
        # key that was re-created after our snapshot).
        self.anomaly_known = {
            k: (v or {}).get("created_at")
            for k, v in ((self.health.get("anomaly_keys") or {}).items())
        }
        self.new_anomaly_keys = {}    # key -> {"created_at","copy"}
        self.drop_anomaly_keys = []   # (key, created_at_seen)
        self.queued_notifs = []       # durable notification records to flush
        self.delivery = []            # chat copy lines (via backfill)
        self.pending = []             # pending launch dicts
        self.mark_ids = []
        self.outage_changed = False
        self.new_violations = []
        self.recovery_grace = False
        self.outage_window = None
        self.audit("tick sweep start db_unreachable=%s live_runs=%d checkpoints=%d"
                   % (db_unreachable, len(self.live_runs), len(self.cps)))

    # ---- loading ------------------------------------------------------
    def _load_handled(self):
        p = os.path.join(self.projdir, "handled_run_ids")
        try:
            with open(p, encoding="utf-8") as f:
                return {l.rstrip("\n") for l in f if l.strip()}
        except OSError:
            return set()

    def _load_checkpoints(self):
        d = os.path.join(self.projdir, "checkpoints")
        cps = {}
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return cps
        for n in names:
            if not n.endswith(".json"):
                continue
            ws = n[:-5]
            if not re.match(r"^(default|pin-[a-z0-9][a-z0-9-]*)$", ws):
                continue
            try:
                with open(os.path.join(d, n), encoding="utf-8") as f:
                    cps[ws] = json.load(f)
            except (OSError, ValueError):
                continue
        return cps

    def _load_health(self):
        p = os.path.join(self.projdir, "tick-health.json")
        try:
            with open(p, encoding="utf-8") as f:
                h = json.load(f)
                return h if isinstance(h, dict) else {}
        except (OSError, ValueError):
            return {}

    def audit(self, msg):
        try:
            with open(os.path.join(self.projdir, "audit.log"), "a",
                      encoding="utf-8") as f:
                f.write("%s tick sweep %s\n" % (dfstate.now_iso(), msg))
        except OSError:
            pass

    # ---- classification (plan §9.3) ------------------------------------
    def classify(self, run):
        """alive | dead | terminal | unknown (paused never dies)."""
        st = run.get("status")
        if st in TERMINAL:
            return "terminal"
        if st == "paused":
            return "alive"  # heartbeat frozen by design; never death-classified
        if st not in ("running", "queued"):
            return "unknown"
        hb = dfstate.parse_iso(run.get("heartbeat_at"))
        started = dfstate.parse_iso(run.get("started_at"))
        if self.recovery_grace and self.outage_window and hb:
            ostart = dfstate.parse_iso(self.outage_window.get("started_at"))
            if ostart and hb >= ostart:
                return "alive"  # staleness fully explained by the outage
        if hb is None:
            if started and (self.ref - started).total_seconds() <= 600:
                return "alive"  # just-started grace
            return "dead"  # NULL + older than 10 min, or never reported at all
        if (self.ref - hb).total_seconds() > 300:
            return "dead"
        return "alive"

    def fresh_114(self, run):
        """§11.4 freshness for adoption/unclaimed scans."""
        hb = dfstate.parse_iso(run.get("heartbeat_at"))
        if hb is not None:
            return (self.ref - hb).total_seconds() <= 300
        started = dfstate.parse_iso(run.get("started_at"))
        return bool(started and (self.ref - started).total_seconds() <= 600)

    # ---- dedupe + durable notifications -------------------------------
    def anomaly(self, key, copy, event="anomaly", run_id=None, workstream=None):
        """Deduped once per key per episode; the key clears when the
        condition clears so a genuine recurrence re-notifies exactly once."""
        self.anomaly_now.add(key)
        keys = self.health.get("anomaly_keys") or {}
        if key in keys:
            return False
        self.new_anomaly_keys[key] = {"created_at": dfstate.now_iso(),
                                      "copy": copy}
        self.queue_notify(event, copy, run_id, workstream)
        return True

    def queue_notify(self, event, copy, run_id=None, workstream=None):
        self.queued_notifs.append(
            {"id": uuid.uuid4().hex, "run_id": run_id, "workstream": workstream,
             "event": event, "copy": copy, "created_at": dfstate.now_iso(),
             "delivered_at": None})

    def script_notify(self, out, key_prefix, workstream):
        """Convert a sub-script's NOTIFY: lines into deduped durable records."""
        for copy in notify_lines(out):
            self.anomaly("%s/%s" % (key_prefix, workstream), copy,
                         workstream=workstream)

    # ---- backlog -------------------------------------------------------
    def item_open(self, item_id):
        try:
            return bl.get(os.path.join(self.projdir, "backlog.md"),
                          item_id) is not None
        except OSError:
            return False

    def item_title(self, item_id):
        try:
            return (bl.title(os.path.join(self.projdir, "backlog.md"), item_id)
                    or item_id)
        except OSError:
            return item_id

    # ---- pending launches ----------------------------------------------
    def resolve_workflow_args(self, item_id):
        """Resolve the dev-factory workflow's fail-fast args contract from
        project.json: {project, item_id, backlog_path, repo_path,
        worktree_path, base_branch} with absolute paths. Returns None (and
        audits a warning) when project.json lacks worktree_path: the pending
        record is still emitted but the worker must not launch with
        invented paths."""
        try:
            with open(os.path.join(self.projdir, "project.json"),
                      "r", encoding="utf-8") as f:
                proj = json.load(f)
        except (OSError, ValueError):
            proj = {}
        worktree_path = proj.get("worktree_path")
        if not worktree_path:
            self.audit("tick pending launch item=%s: project.json has no "
                       "worktree_path; emitting with workflow_args=None "
                       "(unresolvable -- do not launch)"
                       % item_id)
            return None
        return {"project": self.project,
                "item_id": item_id,
                "backlog_path": os.path.join(self.projdir, "backlog.md"),
                "repo_path": proj.get("repo_path"),
                "worktree_path": worktree_path,
                "base_branch": proj.get("base_branch") or "main"}

    def emit_pending(self, workstream, item_id, chain_token):
        workflow_args = self.resolve_workflow_args(item_id)
        self.pending.append({"token": uuid.uuid4().hex,
                             "workstream": workstream, "item_id": item_id,
                             "chain_token": chain_token,
                             "workflow_args": workflow_args,
                             "created_at": dfstate.now_iso()})
        self.audit("tick pending launch ws=%s item=%s chain=%s args=%s"
                   % (workstream, item_id, bool(chain_token),
                      "resolved" if workflow_args else "unresolvable"))

    # ==================================================================
    # phases (§11.1 precedence)
    # ==================================================================
    def phase_chain(self):
        """Complete pending chain_intent: claim -> release -> launch ->
        confirm. Claims under the mutex, releases immediately; the worker
        launches (tool call, never under mutex) and confirm-launch.sh
        confirm-CASes. Stale claims (>10 min) may be reclaimed; a stale
        claim with a live run for the bound item recovers via confirm."""
        for ws, cp in sorted(self.cps.items()):
            ci = cp.get("chain_intent")
            if not isinstance(ci, dict):
                continue
            nxt = ci.get("next_item")
            if not nxt:
                continue
            claim = ci.get("claim")
            if isinstance(claim, dict):
                claimed_at = dfstate.parse_iso(claim.get("claimed_at"))
                age = ((self.ref - claimed_at).total_seconds()
                       if claimed_at else 10**9)
                if age <= 600:
                    if claim.get("by") == "tick":
                        self.recover_chain_claim(ws, cp, ci, claim)
                    continue  # fresh claim: launch in flight, leave alone
                if self.recover_chain_claim(ws, cp, ci, claim):
                    continue
                rc, out = sh(os.path.join(SCRIPTS, "checkpoint.sh"),
                             "release-chain", self.project, ws,
                             "--expect-token", claim.get("token") or "")
                if rc != 0:
                    self.audit("tick chain ws=%s stale release failed (raced)"
                               % ws)
                    continue
                self.audit("tick chain ws=%s reclaimed stale claim" % ws)
            token = uuid.uuid4().hex
            rc, out = sh(os.path.join(SCRIPTS, "checkpoint.sh"),
                         "claim-chain", self.project, ws,
                         "--expect-next", nxt, "--token", token, "--by", "tick")
            if rc != 0:
                self.audit("tick chain ws=%s claim failed (raced)" % ws)
                continue
            if not self.item_open(nxt):
                sh(os.path.join(SCRIPTS, "checkpoint.sh"), "cas",
                   self.project, ws,
                   "--expect", "chain_intent.claim.token=%s" % token,
                   "--set-json", "chain_intent=null")
                self.audit("tick chain ws=%s cleared: next item %s not open"
                           % (ws, nxt))
                continue
            self.emit_pending(ws, nxt, token)

    def recover_chain_claim(self, ws, cp, ci, claim):
        """A claim with a live run for the bound item means the launch
        happened but confirm was lost: complete it via confirm-launch.sh."""
        nxt = ci.get("next_item")
        claimed_at = dfstate.parse_iso(claim.get("claimed_at"))
        cands = [r for r in self.live_runs
                 if r.get("status") in ("running", "queued")
                 and r["args"].get("project") == self.project
                 and r["args"].get("item_id") == nxt
                 and claimed_at
                 and dfstate.parse_iso(r.get("started_at"))
                 and dfstate.parse_iso(r.get("started_at")) >= claimed_at]
        if len(cands) != 1:
            return False
        rid = cands[0]["run_id"]
        rc, out = sh(os.path.join(SCRIPTS, "confirm-launch.sh"),
                     self.project, ws, rid,
                     "--chain-token", claim.get("token") or "")
        self.audit("tick chain ws=%s recovered lost confirm run=%s rc=%d %s"
                   % (ws, rid, rc, first_line(out)))
        return rc == 0

    def phase_terminal(self):
        """Terminal reconciliation (state-aware). Stopping checkpoints are
        owned by phase_stopping; everything else goes through
        apply-envelope.sh, which already implements the paused/stopping +
        stopped ledger-only path and the paused + late-done no-chain path."""
        self.terminal_applied = []
        for ws, cp in sorted(self.cps.items()):
            if cp.get("state") == "stopping":
                continue
            rid = cp.get("run_id")
            if not rid or rid in self.handled:
                continue
            run = self.runs_by_id.get(rid)
            if run is None or run.get("status") not in TERMINAL:
                continue
            deaths_before = list(cp.get("death_timestamps") or [])
            fd, env_path = tempfile.mkstemp(prefix="tick-env-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(run.get("final_result") or "")
                rc, out = sh(os.path.join(SCRIPTS, "apply-envelope.sh"),
                             self.project, ws, env_path, rid,
                             "--run-status", run.get("status") or "")
            finally:
                try:
                    os.unlink(env_path)
                except OSError:
                    pass
            tok = first_line(out)
            self.audit("tick terminal ws=%s run=%s -> %s" % (ws, rid, tok))
            if tok.startswith("APPLIED_"):
                self.handled.add(rid)
                if deaths_before:
                    self.terminal_applied.append(
                        (ws, cp.get("current_item"), len(deaths_before)))

    def phase_death(self):
        """Death detection: live-excluding-paused runs with stale heartbeat
        (§9.3). Stopping checkpoints are never death-classified. On death:
        record-death.sh (intensity); sub-threshold -> prepare-launch.sh
        (adopt-or-arm); escalated -> parked, no relaunch."""
        for ws, cp in sorted(self.cps.items()):
            if cp.get("state") != "in_progress":
                continue
            rid = cp.get("run_id")
            if not rid:
                continue
            run = self.runs_by_id.get(rid)
            if run is None or self.classify(run) != "dead":
                continue
            item = cp.get("current_item") or "?"
            rc, out = sh(os.path.join(SCRIPTS, "record-death.sh"),
                         self.project, ws, "--summary",
                         "tick: stale heartbeat on run %s (item %s)"
                         % (rid, item))
            tok = first_line(out)
            self.audit("tick death ws=%s run=%s -> %s" % (ws, rid, tok))
            if "ESCALATED" in tok:
                continue  # parked + escalation record written by record-death
            rc2, out2 = sh(os.path.join(SCRIPTS, "prepare-launch.sh"),
                           self.project, ws, item,
                           "--live-runs", self.live_runs_path)
            tok2 = first_line(out2)
            if tok2 == "ARMED":
                if self.item_open(item):
                    self.emit_pending(ws, item, None)
                else:
                    self.audit("tick death ws=%s not relaunching: item %s "
                               "not open" % (ws, item))
            elif tok2.startswith("ADOPTED"):
                self.audit("tick death ws=%s adopted %s" % (ws, tok2))
            else:
                self.script_notify(out2, "launchfail", ws)

    def phase_orphan(self):
        """Strict orphan scan: checkpoint expects a run (run_id null after
        arming, or recorded run_id gone) -> adopt-or-relaunch.sh. Armed
        within the last 60 s: in-flight launch grace, skip. Fresh chain
        claims are owned by phase_chain."""
        for ws, cp in sorted(self.cps.items()):
            if cp.get("state") != "in_progress":
                continue
            ci = cp.get("chain_intent")
            if isinstance(ci, dict) and isinstance(ci.get("claim"), dict):
                claimed_at = dfstate.parse_iso(ci["claim"].get("claimed_at"))
                if claimed_at and (self.ref - claimed_at).total_seconds() <= 600:
                    continue
            rid = cp.get("run_id")
            item = cp.get("current_item")
            if not item:
                continue
            if rid is None:
                armed_at = dfstate.parse_iso(cp.get("armed_at"))
                if armed_at and (self.ref - armed_at).total_seconds() <= 60:
                    continue  # in-flight launch grace
            elif rid in self.runs_by_id:
                r = self.runs_by_id[rid]
                if r.get("status") in ("running", "queued", "paused"):
                    # live -> not orphan; paused -> foreign-pause branch
                    continue
                # else: recorded run_id exists but is not live, not terminal
                # (terminal runs are reconciled by phase_terminal before this
                # phase), and not paused -> orphan per §11.1 -> fall through
                # to the adoption/relaunch logic below.
            rc, out = sh(os.path.join(SCRIPTS, "adopt-or-relaunch.sh"),
                         self.project, ws, item,
                         "--live-runs", self.live_runs_path)
            tok = first_line(out)
            self.audit("tick orphan ws=%s item=%s -> %s" % (ws, item, tok))
            if tok.startswith("ADOPT"):
                continue
            if tok == "RELAUNCH":
                if not self.item_open(item):
                    self.audit("tick orphan ws=%s not relaunching: item %s "
                               "not open" % (ws, item))
                    continue
                if rid is not None:
                    # recorded run_id refers to a vanished row: clear it so
                    # confirm-launch.sh records the new run instead of
                    # ADOPT_RECORDED-ing a ghost.
                    rc3, _ = sh(os.path.join(SCRIPTS, "checkpoint.sh"),
                                "cas", self.project, ws,
                                "--expect", "run_id=%s" % rid,
                                "--set-json", "run_id=null",
                                "--set-json", "armed_at=\"%s\""
                                % dfstate.now_iso())
                    if rc3 != 0:
                        continue
                else:
                    # refresh armed_at so overlapping ticks see the
                    # in-flight grace instead of double-emitting.
                    sh(os.path.join(SCRIPTS, "checkpoint.sh"), "cas",
                       self.project, ws, "--expect", "run_id=null",
                       "--set-json",
                       "armed_at=\"%s\"" % dfstate.now_iso())
                self.emit_pending(ws, item, None)
            else:
                self.script_notify(out, "orphanfail", ws)

    def phase_foreign_pause(self):
        """checkpoint in_progress + run paused -> record paused_observed_at,
        notify once, do not touch."""
        for ws, cp in sorted(self.cps.items()):
            if cp.get("state") != "in_progress":
                continue
            rid = cp.get("run_id")
            run = self.runs_by_id.get(rid) if rid else None
            if run is None or run.get("status") != "paused":
                continue
            sh(os.path.join(SCRIPTS, "checkpoint.sh"), "cas",
               self.project, ws, "--expect", "state=in_progress",
               "--set-json", "paused_observed_at=\"%s\"" % dfstate.now_iso())
            self.anomaly(
                "fpause/%s/%s" % (ws, rid),
                "Run %s for %s is paused outside the factory -- left "
                "untouched. Say go to resume it or stop to park it."
                % (rid, self.item_title(cp.get("current_item") or "?")),
                event="foreign-pause", run_id=rid, workstream=ws)

    def phase_stopping(self):
        """Inconclusive-stop re-verify (§11.2): re-poll stopping checkpoints
        every sweep; never death-classify them. Four outcomes: (a)
        terminal-on-its-own -> apply-envelope --no-chain then -> paused;
        (b) confirmed stopped -> paused; (c/d) still live or unreadable ->
        stays stopping (deduped notice), bounded fallback to in_progress
        after 30 min."""
        for ws, cp in sorted(self.cps.items()):
            if cp.get("state") != "stopping":
                continue
            rid = cp.get("run_id")
            run = self.runs_by_id.get(rid) if rid else None
            since = dfstate.parse_iso(cp.get("stopping_since"))
            old = bool(since and (self.ref - since).total_seconds() > 1800)
            long = bool(since and (self.ref - since).total_seconds() > 300)
            if run is None or run.get("status") not in TERMINAL + LIVE:
                if old:
                    self.stop_fallback(ws, cp)
                else:
                    if long:
                        self.stop_long_notice(ws, cp)
                    self.anomaly(
                        "stop-inconclusive/%s/%s" % (ws, cp.get("stopping_since")),
                        INCONCLUSIVE_STOP_COPY, event="stop-inconclusive",
                        run_id=rid, workstream=ws)
                continue
            st = run.get("status")
            if st in ("completed", "failed"):
                fd, env_path = tempfile.mkstemp(prefix="tick-env-")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(run.get("final_result") or "")
                    rc, out = sh(os.path.join(SCRIPTS, "apply-envelope.sh"),
                                 self.project, ws, env_path, rid,
                                 "--run-status", st, "--no-chain")
                finally:
                    try:
                        os.unlink(env_path)
                    except OSError:
                        pass
                tok = first_line(out)
                self.audit("tick stopping ws=%s terminal-on-its-own -> %s"
                           % (ws, tok))
                if tok == "APPLIED_DONE":
                    self.handled.add(rid)
                    self.stop_to_paused(
                        ws, cp,
                        "The run finished just as the stop landed -- I've "
                        "recorded its result; nothing is running.")
                elif tok in ("ALREADY_APPLIED", "LEDGER_ONLY", "SUPERSEDED"):
                    # Envelope already reconciled (or not ours): the stop
                    # still takes effect -> paused. Ledger-append ensures
                    # later data for this run_id is ignored.
                    self.handled.add(rid)
                    self.stop_to_paused(
                        ws, cp,
                        "The run had already finished -- I've recorded its "
                        "result; nothing is running.")
                # APPLIED_PARKED/APPLIED_FAILED/APPLIED_UNKNOWN: their own
                # disposition stands (parked with questions); the stop is moot
                # because the run already reached a terminal outcome.
                # APPLIED_DONE_TOMBSTONED: checkpoint is gone, nothing to do.
            elif st in ("stopped", "paused"):
                self.stop_to_paused(ws, cp, "Stopped.")
            else:  # live
                if old:
                    self.stop_fallback(ws, cp)
                else:
                    if long:
                        self.stop_long_notice(ws, cp)
                    self.anomaly(
                        "stop-inconclusive/%s/%s" % (ws, cp.get("stopping_since")),
                        INCONCLUSIVE_STOP_COPY, event="stop-inconclusive",
                        run_id=rid, workstream=ws)

    def stop_long_notice(self, ws, cp):
        """5-minute escalation (§10 event catalog): stop past 5 min and
        still inconclusive -> deduped "taking unusually long" notice, then
        keep waiting (no fallback until 30 min). The key is per stopping
        episode (stopping_since), so a genuine recurrence re-notifies."""
        self.anomaly(
            "stop-long/%s/%s" % (ws, cp.get("stopping_since")),
            "The stop for %s is taking unusually long -- still stopping "
            "after 5 minutes. I'm still waiting on it."
            % (cp.get("current_item") or "?"),
            event="stop-long", run_id=cp.get("run_id"), workstream=ws)

    def stop_to_paused(self, ws, cp, ack_copy):
        """CAS stopping -> paused (expect state + run_id); ledger-append the
        stopped run_id (takes precedence: later data for it is ignored).
        Single mutex-held CAS: revalidates state==stopping and matching
        run_id while writing checkpoint, ledger, and audit atomically.
        Also propagates stop provenance: paused_by takes the checkpoint's
        stopping_by ("global-stop"/"local-stop" written by the supervisor
        when it CAS-wrote stopping), then stopping_by is cleared."""
        rid = cp.get("run_id")
        # Single mutex hold: check + mutate. subprocess uses an argv list
        # (no shell), so ack_copy needs no shell-quoting.
        code = (
            "import json,os,sys,datetime\n"
            "projdir,ws,rid,ack = sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]\n"
            "now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')\n"
            "p=os.path.join(projdir,'checkpoints',ws+'.json')\n"
            "cp=json.load(open(p))\n"
            "ok = cp.get('state')=='stopping' and cp.get('run_id')==rid\n"
            "print('CONFLICT' if not ok else 'OK')\n"
            "sys.stdout.flush()\n"
            "if not ok: sys.exit(0)\n"
            "cp['state']='paused';cp['paused_at']=now;cp['stopping_since']=None\n"
            "cp['paused_by']=cp.get('stopping_by');cp['stopping_by']=None\n"
            "tmp=p+'.tmp';json.dump(cp,open(tmp,'w'),indent=2);open(tmp,'a').write(chr(10));os.replace(tmp,p)\n"
            "led=os.path.join(projdir,'handled_run_ids')\n"
            "have=set(l.rstrip(chr(10)) for l in open(led) if l.strip()) if os.path.exists(led) else set()\n"
            "open(led,'a').write(rid+chr(10)) if rid and rid not in have else None\n"
            "au=open(os.path.join(projdir,'audit.log'),'a');au.write(now+' tick stop-to-paused ws='+ws+' run='+rid+chr(10));au.close()\n"
            "print('PAUSED')\n"
        )
        rc, out = sh_mtx(self.project, "python3", "-c", code,
                         self.projdir, ws, rid or "", ack_copy)
        lines = (out or "").strip().split("\n")
        if lines and lines[0].strip() == "CONFLICT":
            self.audit("tick stopping ws=%s to-paused raced (state changed)"
                       % ws)
            return
        if lines and lines[-1].strip() == "PAUSED":
            self.handled.add(rid)
            self.queue_notify("stop", ack_copy, rid, ws)
            self.audit("tick stopping ws=%s -> paused run=%s" % (ws, rid))

    def stop_fallback(self, ws, cp):
        """Bounded fallback: stopping older than 30 min and still
        inconclusive -> back to in_progress + notify. Single mutex-held
        CAS: revalidates state==stopping while writing."""
        code = (
            "import json,os,sys,datetime\n"
            "projdir,ws = sys.argv[1],sys.argv[2]\n"
            "now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')\n"
            "p=os.path.join(projdir,'checkpoints',ws+'.json')\n"
            "cp=json.load(open(p))\n"
            "ok=cp.get('state')=='stopping'\n"
            "print('CONFLICT' if not ok else 'OK')\n"
            "sys.stdout.flush()\n"
            "if not ok: sys.exit(0)\n"
            "cp['state']='in_progress';cp['stopping_since']=None\n"
            "tmp=p+'.tmp';json.dump(cp,open(tmp,'w'),indent=2);open(tmp,'a').write(chr(10));os.replace(tmp,p)\n"
            "au=open(os.path.join(projdir,'audit.log'),'a');au.write(now+' tick stop-fallback ws='+ws+chr(10));au.close()\n"
            "print('FALLBACK')\n"
        )
        rc, out = sh_mtx(self.project, "python3", "-c", code,
                         self.projdir, ws)
        lines = (out or "").strip().split("\n")
        if lines and lines[0].strip() == "CONFLICT":
            return
        if lines and lines[-1].strip() == "FALLBACK":
            self.queue_notify("stop", FALLBACK_COPY, cp.get("run_id"), ws)
            self.audit("tick stopping ws=%s fallback -> in_progress" % ws)

    def phase_anomalies(self):
        """Failed stop, parked + unexpected live run, two chats, unclaimed
        runs. All notify-once-per-key; nothing is touched."""
        for ws, cp in sorted(self.cps.items()):
            rid = cp.get("run_id")
            run = self.runs_by_id.get(rid) if rid else None
            state = cp.get("state")
            item = cp.get("current_item") or "?"
            if state == "paused" and run is not None \
                    and run.get("status") in ("running", "queued") \
                    and self.classify(run) == "alive":
                self.anomaly(
                    "failed-stop/%s/%s" % (ws, rid),
                    "The stop didn't take -- run %s for %s is still going. "
                    "Left untouched; say stop again." % (rid, item),
                    event="failed-stop", run_id=rid, workstream=ws)
            if state == "parked":
                for r in self.live_runs:
                    if r.get("status") in ("running", "queued") \
                            and self.classify(r) == "alive" \
                            and r["args"].get("project") == self.project \
                            and r["args"].get("item_id") == item:
                        self.anomaly(
                            "parked-live/%s/%s" % (ws, r["run_id"]),
                            "Workstream %s is parked but run %s for %s is "
                            "live -- left untouched, not adopted."
                            % (ws, r["run_id"], item),
                            event="parked-live-run", run_id=r["run_id"],
                            workstream=ws)
            chats = cp.get("chats") or []
            if len(chats) > 1:
                self.new_violations.append(
                    {"id": "two-chats/%s" % ws, "workstream": ws,
                     "kind": "two-chats",
                     "created_at": dfstate.now_iso()})
                self.anomaly(
                    "two-chats/%s" % ws,
                    "Workstream %s is mapped to %d chats -- left untouched "
                    "until a human looks." % (ws, len(chats)),
                    event="two-chats", workstream=ws)
        claimed = {cp.get("run_id") for cp in self.cps.values()
                   if cp.get("run_id")}
        for r in self.live_runs:
            if r.get("status") not in ("running", "queued"):
                continue
            if not self.fresh_114(r):
                continue
            if r["args"].get("project") != self.project:
                continue
            rid = r.get("run_id")
            if not rid or rid in claimed:
                continue
            started = dfstate.parse_iso(r.get("started_at"))
            if started and (self.ref - started).total_seconds() <= 90:
                continue  # just launched by a worker; confirm is in flight
            self.anomaly(
                "unclaimed/%s" % rid,
                "I see a live run %s for item %s that no workstream claims "
                "-- left untouched." % (rid, r["args"].get("item_id")),
                event="unclaimed-run", run_id=rid)

    def phase_disarm(self):
        """7-day disarm: parked/paused checkpoints older than 7 days become
        tombstones; the verbatim disarm message is delivered."""
        for ws, cp in sorted(self.cps.items()):
            state = cp.get("state")
            if state not in ("parked", "paused"):
                continue
            ts = dfstate.parse_iso(cp.get("parked_at") or cp.get("paused_at"))
            if not ts or (self.ref - ts).total_seconds() <= 7 * 86400:
                continue
            rc, out = sh(os.path.join(SCRIPTS, "checkpoint.sh"), "disarm",
                         self.project, ws, "--reason", "disarmed")
            if rc == 0:
                self.queue_notify("disarm", DISARM_COPY, cp.get("run_id"), ws)
                self.audit("tick disarm ws=%s" % ws)

    def phase_stabilization(self):
        """OTP stabilization: a relaunched run reaching a terminal envelope,
        or 30 min with no further death, emits the lightweight recovery note
        and clears the intensity window."""
        for ws, item, n in getattr(self, "terminal_applied", []):
            self.queue_notify(
                "recovered", "Recovered after %d restart%s (item %s)."
                % (n, "" if n == 1 else "s", item), None, ws)
            sh(os.path.join(SCRIPTS, "checkpoint.sh"), "cas",
               self.project, ws, "--set-json", "death_timestamps=[]")
            self.audit("tick stabilized ws=%s after %d restarts" % (ws, n))
        for ws, cp in sorted(self.cps.items()):
            deaths = cp.get("death_timestamps") or []
            if not deaths:
                continue
            newest = max((dfstate.parse_iso(d) for d in deaths),
                         default=None)
            if newest and (self.ref - newest).total_seconds() > 1800:
                self.queue_notify(
                    "recovered",
                    "Recovered after %d restart%s (item %s)."
                    % (len(deaths), "" if len(deaths) == 1 else "s",
                       cp.get("current_item") or "?"), None, ws)
                sh(os.path.join(SCRIPTS, "checkpoint.sh"), "cas",
                   self.project, ws, "--set-json", "death_timestamps=[]")
                self.audit("tick stabilized ws=%s (quiet 30 min)" % ws)

    def phase_file_sweep(self):
        """§14 per-run forensics: prune workflow run working dirs under
        <projdir>/runs/<run_id>/ older than 30 days by directory mtime.
        Convention (established here): launchers write per-run forensics
        under runs/<run_id>/; the tick's file sweep prunes anything older
        than 30 days. Non-directory entries are ignored. Failure to remove
        one dir never aborts the sweep."""
        d = os.path.join(self.projdir, "runs")
        try:
            names = os.listdir(d)
        except OSError:
            return  # no runs dir yet: nothing to prune
        cutoff = self.ref.timestamp() - 30 * 86400
        pruned = 0
        for n in sorted(names):
            p = os.path.join(d, n)
            try:
                if not os.path.isdir(p):
                    continue
                if os.path.getmtime(p) >= cutoff:
                    continue
            except OSError:
                continue
            try:
                shutil.rmtree(p)
                pruned += 1
            except OSError as e:
                self.audit("tick file-sweep prune failed %s: %s" % (p, e))
        if pruned:
            self.audit("tick file-sweep pruned %d run dir(s) older than 30d"
                       % pruned)

    # ---- outage (§11.7) ------------------------------------------------
    def outage_mode(self):
        h = self.health
        out = h.get("outage") or {}
        now = dfstate.now_iso()
        if not out.get("active"):
            out.update({"active": True, "started_at": now,
                        "last_notice_at": now})
            self.queue_notify("outage", OUTAGE_COPY, None, None)
            self.audit("tick outage started")
        else:
            last = dfstate.parse_iso(out.get("last_notice_at"))
            if not last or (self.ref - last).total_seconds() > 3600:
                out["last_notice_at"] = now
                self.queue_notify("outage", OUTAGE_COPY, None, None)
        h["outage"] = out
        self.outage_changed = True
        # file-only reporting: checkpoint/tombstone/backlog mtimes
        lines = ["Outage file sweep (no checkpoint mutations, no disarms):"]
        for sub in ("checkpoints", "tombstones"):
            d = os.path.join(self.projdir, sub)
            try:
                names = sorted(os.listdir(d))
            except OSError:
                names = []
            lines.append("  %s/: %d files" % (sub, len(
                [n for n in names if n.endswith(".json")])))
        try:
            mt = os.path.getmtime(os.path.join(self.projdir, "backlog.md"))
            lines.append("  backlog.md mtime: %d" % int(mt))
        except OSError:
            lines.append("  backlog.md: missing")
        self.delivery.extend(lines)

    def recover_outage(self):
        h = self.health
        out = h.get("outage") or {}
        started = out.get("started_at")
        window = {"started_at": started, "ended_at": dfstate.now_iso()}
        wins = h.get("outage_windows") or []
        wins.append(window)
        h["outage_windows"] = wins[-10:]
        h["outage"] = {"active": False, "started_at": None,
                       "last_notice_at": None}
        self.outage_changed = True
        self.recovery_grace = True
        self.outage_window = window
        self.queue_notify("outage-recovered", RECOVERY_COPY, None, None)
        self.audit("tick outage recovered; grace armed for this sweep")

    # ---- finish ---------------------------------------------------------
    def finish(self):
        """One mutex acquisition for all end-of-sweep writes: flush queued
        notifications, append pinned copies to pending_relay, write
        pending-launch files, merge tick-health. Then the backfill read and
        the machine-readable sections."""
        flush_code = (
            "import json,os,sys,uuid\n"
            "projdir = sys.argv[1]\n"
            "notifs = json.loads(sys.argv[2])\n"
            "pending = json.loads(sys.argv[3])\n"
            "add_keys = json.loads(sys.argv[4])\n"
            "drop_keys = json.loads(sys.argv[5])\n"
            "violations = json.loads(sys.argv[6])\n"
            "outage = json.loads(sys.argv[7])\n"
            "outage_changed = sys.argv[8] == '1'\n"
            "outage_windows = json.loads(sys.argv[9])\n"
            "np = os.path.join(projdir,'notifications.jsonl')\n"
            "if notifs:\n"
            "    f=open(np,'a');[f.write(json.dumps(r)+chr(10)) for r in notifs];f.close()\n"
            "# pinned-workstream copies -> pending_relay (dedupe exact copy)\n"
            "for r in notifs:\n"
            "    w=r.get('workstream') or ''\n"
            "    if w.startswith('pin-'):\n"
            "        p=os.path.join(projdir,'checkpoints',w+'.json')\n"
            "        if os.path.exists(p):\n"
            "            cp=json.load(open(p));rel=cp.get('pending_relay') or []\n"
            "            entry='[tick] '+r['copy']\n"
            "            [rel.append(entry) for _ in [0] if entry not in rel]\n"
            "            cp['pending_relay']=rel\n"
            "            t=p+'.tmp';json.dump(cp,open(t,'w'),indent=2);open(t,'a').write(chr(10));os.replace(t,p)\n"
            "# pending-launch files\n"
            "pd=os.path.join(projdir,'checkpoints','pending-launches')\n"
            "os.makedirs(pd,exist_ok=True)\n"
            "for pl in pending:\n"
            "    p=os.path.join(pd,pl['token']+'.json')\n"
            "    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644)\n"
            "    os.write(fd,(json.dumps(pl,indent=2)+chr(10)).encode());os.close(fd)\n"
            "# tick-health merge\n"
            "hp=os.path.join(projdir,'tick-health.json')\n"
            "h=json.load(open(hp)) if os.path.exists(hp) else {}\n"
            "ak=h.get('anomaly_keys') or {}\n"
            "[ak.pop(k) for k,ts in drop_keys if isinstance(ak.get(k),dict) and ak[k].get('created_at')==ts]\n"
            "ak.update(add_keys);h['anomaly_keys']=ak\n"
            "v=h.get('violations') or []\n"
            "[v.append(x) for x in violations if x.get('id') not in [y.get('id') for y in v]]\n"
            "h['violations']=v\n"
            "if outage_changed:h['outage']=outage;h['outage_windows']=outage_windows\n"
            "t=hp+'.tmp';json.dump(h,open(t,'w'),indent=2);open(t,'a').write(chr(10));os.replace(t,hp)\n"
            "print('FLUSHED %d notifs %d pending' % (len(notifs),len(pending)))\n"
        )
        drop = [(k, self.anomaly_known[k]) for k in
                (set((self.health.get("anomaly_keys") or {})) - self.anomaly_now)
                if k in self.anomaly_known]
        # Drop keys whose condition cleared this sweep. The created_at match
        # (checked in the flush) guards against clearing a key that was
        # re-created after our snapshot.
        rc, out = sh_mtx(
            self.project, "python3", "-c", flush_code, self.projdir,
            json.dumps(self.queued_notifs), json.dumps(self.pending),
            json.dumps(self.new_anomaly_keys), json.dumps(drop),
            json.dumps(self.new_violations),
            json.dumps(self.health.get("outage") or {}),
            "1" if self.outage_changed else "0",
            json.dumps(self.health.get("outage_windows") or []))
        self.audit("tick flush rc=%d %s" % (rc, first_line(out)))
        self.backfill()

    def backfill(self):
        """Notification backfill: every undelivered record goes into this
        run's project-chat delivery; the worker marks them delivered after
        the delivery lands (notify.sh mark-delivered)."""
        np = os.path.join(self.projdir, "notifications.jsonl")
        try:
            f = open(np, encoding="utf-8")
        except OSError:
            return
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("delivered_at") is None and r.get("id") and r.get("copy"):
                self.delivery.append(str(r["copy"]))
                self.mark_ids.append(r["id"])
        f.close()

    def run(self):
        if self.db_unreachable:
            self.outage_mode()
            self.finish()
        else:
            if (self.health.get("outage") or {}).get("active"):
                self.recover_outage()
            self.phase_chain()
            self.phase_terminal()
            self.phase_death()
            self.phase_orphan()
            self.phase_foreign_pause()
            self.phase_stopping()
            self.phase_anomalies()
            self.phase_disarm()
            self.phase_stabilization()
            self.phase_file_sweep()
            self.finish()
        # prune anomaly keys whose condition cleared (safe: created_at match)
        print("TICK_SWEEP_OK")
        print("DELIVERY_BEGIN")
        for line in self.delivery:
            print(line)
        print("DELIVERY_END")
        print("PENDING_BEGIN")
        for p in self.pending:
            print("%s %s %s" % (p["token"], p["workstream"], p["item_id"]))
        print("PENDING_END")
        print("MARK_BEGIN")
        if self.mark_ids:
            print(" ".join(self.mark_ids))
        print("MARK_END")
        return 0


def main(argv):
    if len(argv) != 4 or argv[1] != "sweep":
        print("usage: tick_sweep.py sweep <project> <live-runs.json>|--db-unreachable",
              file=sys.stderr)
        return 2
    project = argv[2]
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", project):
        print("tick_sweep.py: bad project slug", file=sys.stderr)
        return 2
    db_unreachable = argv[3] == "--db-unreachable"
    live_runs_path = None if db_unreachable else argv[3]
    if not db_unreachable and not os.path.isfile(live_runs_path):
        print("tick_sweep.py: live-runs file not found: %s" % live_runs_path,
              file=sys.stderr)
        return 2
    sw = Sweep(project, live_runs_path, db_unreachable)
    sw.live_runs_path = live_runs_path
    try:
        return sw.run()
    except Exception as e:  # fail closed: never half-sweep silently
        print("TICK_SWEEP_ERROR %s: %s" % (type(e).__name__, e),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
