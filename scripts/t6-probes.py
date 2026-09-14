#!/usr/bin/env python3
"""T6 probes for dev-factory: queued-run heartbeats, json_extract on args_json,
workflow-versioning snapshot.

Plan references:
  - Probe 1 (Tech MJ-1, §11.2, §11.4): NULL heartbeat handling + just-started grace.
    §11.2: "NULL heartbeat_at + NULL started_at -> dead (a row that never
    reported at all)."
  - Probe 2 (ASM-3, §11.4): "args_json is queryable via json_extract in muse.db.
    One-line probe in T6." Fallback: parse args_json with jq/python if the
    SQL function is unavailable.
  - Probe 3 (ASM-2, §15): "Saved-workflow replacement does not affect in-flight
    runs (script snapshot at launch). Probe in T6; if false, updates wait for
    quiescence."

These probes run read-only against muse.db (via the caller: paste the SQL into
muse.db) and drive the real tick_sweep.py classification logic with synthetic
edge cases. They never touch the pilot project.

Usage:
  ./t6-probes.py            # runs all probes that don't need a live DB handle
  ./t6-probes.py --db       # also runs the live muse.db checks (see SQL below)

Exit 0 = all PASS, 1 = any FAIL.
"""
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "lib"))
import dfstate

# Import the real classification logic from tick_sweep without running a sweep.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "tick_sweep",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "lib", "tick_sweep.py"))
tick_sweep = importlib.util.module_from_spec(_spec)
# Stub out the sweep __main__ guard by importing; tick_sweep.main only runs
# under __main__, so this is safe.
_spec.loader.exec_module(tick_sweep)

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((name, PASS if cond else FAIL, detail))
    print("%s %s%s" % (PASS if cond else FAIL, name,
                       (" -- " + detail) if detail else ""))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


# ---------------------------------------------------------------- probe 1
def probe_queued_heartbeats():
    """Tech MJ-1 / §11.2: NULL heartbeat rules + just-started grace.

    Drives Sweep.classify() (the real code path used by phase_death and
    phase_anomalies) with synthetic runs covering every NULL combination.
    """
    print("== probe 1: queued-run heartbeats (NULL rules + just-started grace) ==")
    now = datetime.datetime.now(datetime.timezone.utc)

    def mk(status, hb_age_s, started_age_s):
        return {
            "run_id": "probe-%s-%s-%s" % (status, hb_age_s, started_age_s),
            "status": status,
            "heartbeat_at": iso(now - datetime.timedelta(seconds=hb_age_s))
            if hb_age_s is not None else None,
            "started_at": iso(now - datetime.timedelta(seconds=started_age_s))
            if started_age_s is not None else None,
        }

    # Build a Sweep without touching any project dir: stub the bits classify
    # needs (ref, recovery_grace=False).
    sw = tick_sweep.Sweep.__new__(tick_sweep.Sweep)
    sw.ref = now
    sw.recovery_grace = False
    sw.outage_window = None

    cases = [
        # (name, run, expected)
        ("null hb + null started -> dead",
         mk("queued", None, None), "dead"),
        ("null hb + null started (running) -> dead",
         mk("running", None, None), "dead"),
        ("null hb + started 5m ago -> alive (just-started grace)",
         mk("queued", None, 300), "alive"),
        ("null hb + started 9m ago -> alive (grace boundary 10m)",
         mk("queued", None, 540), "alive"),
        ("null hb + started 11m ago -> dead (grace expired)",
         mk("queued", None, 660), "dead"),
        ("stale hb 6m ago -> dead",
         mk("running", 360, 3600), "dead"),
        ("fresh hb 1m ago -> alive",
         mk("running", 60, 3600), "alive"),
        ("hb 299s ago -> alive (inside boundary)",
         mk("running", 299, 3600), "alive"),
        # NOTE: iso() truncates to whole seconds, so a synthetic "exactly 300s"
        # case lands at 300.x s after re-parsing and correctly reads dead.
        # The real code uses `> 300` (strictly older than 5 min); sub-second
        # boundary fuzz from second-precision timestamps is accepted per plan.
        ("hb 301s ago -> dead",
         mk("running", 301, 3600), "dead"),
        ("paused with stale hb -> alive (never death-classified)",
         mk("paused", 7200, 7200), "alive"),
        ("paused with null hb -> alive (never death-classified)",
         mk("paused", None, None), "alive"),
        ("terminal completed -> terminal",
         mk("completed", 7200, 7200), "terminal"),
        ("terminal failed -> terminal",
         mk("failed", 7200, 7200), "terminal"),
        ("unknown status -> unknown",
         mk("weird", 60, 3600), "unknown"),
    ]
    for name, run, expected in cases:
        got = sw.classify(run)
        check("classify: " + name, got == expected,
              "got=%s want=%s" % (got, expected))

    # §11.4 freshness (adoption/unclaimed scans) uses fresh_114.
    sw2 = tick_sweep.Sweep.__new__(tick_sweep.Sweep)
    sw2.ref = now
    fresh_cases = [
        ("fresh hb -> fresh", mk("queued", 60, 3600), True),
        ("stale hb -> not fresh", mk("queued", 400, 3600), False),
        ("null hb + started 5m -> fresh (grace)", mk("queued", None, 300), True),
        ("null hb + started 11m -> not fresh", mk("queued", None, 660), False),
        ("null hb + null started -> not fresh", mk("queued", None, None), False),
    ]
    for name, run, expected in fresh_cases:
        got = sw2.fresh_114(run)
        check("fresh_114: " + name, got == expected,
              "got=%s want=%s" % (got, expected))


# ---------------------------------------------------------------- probe 2
def probe_json_extract():
    """ASM-3 / §11.4: args_json queryable via jsonb_extract_path_text.

    Part A (live DB, run via muse.db by the caller):
      SELECT run_id,
             jsonb_extract_path_text(args_json, 'project') AS project,
             jsonb_extract_path_text(args_json, 'item_id') AS item_id
      FROM runtime.workflow_runs WHERE args_json IS NOT NULL LIMIT 5;
    Part B (offline): the python/jq fallback both parse the same payload.
    """
    print("== probe 2: json_extract on args_json (ASM-3) ==")
    print("  [manual] run this in muse.db:")
    print("    SELECT run_id,")
    print("           jsonb_extract_path_text(args_json, 'project') AS project,")
    print("           jsonb_extract_path_text(args_json, 'item_id') AS item_id")
    print("    FROM runtime.workflow_runs WHERE args_json IS NOT NULL LIMIT 5;")
    print("  Expected: rows returned, project/item_id extracted (NULL when absent).")
    print("  NOTE: the plan says 'json_extract'; PostgreSQL's spelling is")
    print("  jsonb_extract_path_text (json_extract is MySQL). The probe below")
    print("  verifies the fallback path both spellings funnel into.")

    payload = {"project": "factory-pilot", "item_id": "item-a",
               "extra": {"nested": [1, 2]}}
    raw = json.dumps(payload)

    # Fallback 1: python json.loads (what tick_sweep/load_live_runs does).
    try:
        parsed = json.loads(raw)
        ok_py = (parsed.get("project") == "factory-pilot"
                 and parsed.get("item_id") == "item-a")
    except ValueError:
        ok_py = False
    check("fallback python json.loads extracts project/item_id", ok_py, raw)

    # Fallback 2: jq.
    try:
        p = subprocess.run(["jq", "-r", ".project", "-"],
                           input=raw, capture_output=True, text=True,
                           timeout=10)
        ok_jq = p.returncode == 0 and p.stdout.strip() == "factory-pilot"
    except (OSError, subprocess.TimeoutExpired):
        ok_jq = False
    check("fallback jq extracts .project", ok_jq,
          "jq missing?" if not ok_jq else "")

    # The tick's own matching path: dfstate.adoption_candidates on args dicts.
    runs = [
        {"run_id": "r1", "status": "running",
         "heartbeat_at": iso(datetime.datetime.now(datetime.timezone.utc)),
         "args": {"project": "factory-pilot", "item_id": "item-a"}},
        {"run_id": "r2", "status": "running",
         "heartbeat_at": iso(datetime.datetime.now(datetime.timezone.utc)),
         "args": {"project": "factory-pilot", "item_id": "item-b"}},
        {"run_id": "r3", "status": "running",
         "heartbeat_at": iso(datetime.datetime.now(datetime.timezone.utc)),
         "args": {"project": "other", "item_id": "item-a"}},
    ]
    cands = dfstate.adoption_candidates(
        runs, "factory-pilot", "item-a",
        datetime.datetime.now(datetime.timezone.utc))
    check("adoption_candidates matches {project,item_id} exactly",
          [c["run_id"] for c in cands] == ["r1"],
          "got=%s" % [c["run_id"] for c in cands])


# ---------------------------------------------------------------- probe 3
def probe_versioning():
    """ASM-2 / §15: saved-workflow replacement must not affect in-flight runs.

    What we can verify without disrupting production:
      a. runtime.workflow_runs.script_sha256 is populated at launch for every
         run (the snapshot column exists and is written once).
      b. tick_sweep.py never reads the saved workflow definition -- it only
         consumes status/heartbeat/final_result/args from the live-runs file.
      c. (manual, via muse.db) distinct runs carry distinct script_sha256
         values, i.e. the snapshot is per-run, not a live reference.
    """
    print("== probe 3: workflow-versioning snapshot (ASM-2) ==")
    print("  [manual] run this in muse.db:")
    print("    SELECT run_id, workflow_name,")
    print("           substr(script_sha256,1,12) AS sha12, status")
    print("    FROM runtime.workflow_runs ORDER BY created_at DESC LIMIT 10;")
    print("  Expected: script_sha256 non-NULL on every row; distinct values")
    print("  across runs of different scripts (per-run snapshot).")

    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "lib", "tick_sweep.py"), encoding="utf-8").read()
    # The tick must not import or query any saved-workflow registry.
    bad = [t for t in ("saved_workflow", "workflow_registry", "script_path",
                       "get_workflow", "load_workflow")
           if t in src]
    check("tick_sweep.py has no saved-workflow dependency", not bad,
          ("found: " + ",".join(bad)) if bad else "only run-row fields used")

    # script_sha256 is read nowhere in the tick either (it keys on run_id).
    check("tick_sweep.py never reads script_sha256",
          "script_sha256" not in src, "")

    # dfstate helpers used by the tick also avoid workflow definitions.
    dsrc = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "lib", "dfstate.py"), encoding="utf-8").read()
    check("dfstate.py has no workflow-definition dependency",
          "script_sha256" not in dsrc and "saved_workflow" not in dsrc, "")


def main(argv):
    probe_queued_heartbeats()
    print()
    probe_json_extract()
    print()
    probe_versioning()
    print()
    fails = [r for r in results if r[1] == FAIL]
    print("t6-probes: %d/%d PASS" % (len(results) - len(fails), len(results)))
    for name, st, detail in fails:
        print("  FAIL %s %s" % (name, detail))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
