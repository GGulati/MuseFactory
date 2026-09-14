#!/usr/bin/env python3
"""adopt-or-relaunch.sh worker: strict orphan adoption check.

Runs under the project mutex (acquired by the entry-point wrapper).
Uses the same section 11.4 candidate filter as prepare-launch.sh:
  exactly one live run for (project, item) -> adopt (record run_id), ADOPT <id>
  zero live runs                          -> no state change, RELAUNCH
  more than one                           -> fail closed, notify, exit 5

Stdout protocol: line 1 = result token; AUDIT:/NOTIFY: lines follow.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dfstate


def main(argv):
    project, workstream, item_id, live_runs_file = argv[1], argv[2], argv[3], argv[4]
    ref = dfstate.now_dt()

    try:
        live_runs = dfstate.load_live_runs(live_runs_file)
    except Exception as e:
        print("LIVE_RUNS_ERROR")
        print("NOTIFY: Could not read live-run data for %s — not adopting or "
              "relaunching until a human looks. (%s)" % (item_id, e))
        print("AUDIT: adopt-or-relaunch abort: unreadable live-runs file: %s" % e)
        return 5

    cp = dfstate.load_checkpoint(project, workstream)
    if cp is None:
        print("NO_CHECKPOINT")
        print("NOTIFY: No checkpoint for workstream %s — refusing to adopt or "
              "relaunch blind." % workstream)
        print("AUDIT: adopt-or-relaunch abort: checkpoint missing for workstream %s"
              % workstream)
        return 5

    cands = dfstate.adoption_candidates(
        live_runs, project, item_id, ref, armed_at=cp.get("armed_at"))

    if len(cands) > 1:
        ids = ",".join(str(c.get("run_id")) for c in cands)
        print("ABORT_MULTIPLE")
        print("NOTIFY: Found %d live runs for %s — not adopting or relaunching "
              "until a human looks." % (len(cands), item_id))
        print("AUDIT: adopt-or-relaunch abort: %d live candidates for item %s (%s)"
              % (len(cands), item_id, ids))
        return 5

    if len(cands) == 1:
        rid = cands[0].get("run_id")
        cp["run_id"] = rid
        cp["armed_at"] = dfstate.now_iso()
        dfstate.save_checkpoint(project, workstream, cp)
        print("ADOPT %s" % rid)
        print("AUDIT: adopt-or-relaunch adopted live run %s for item %s"
              % (rid, item_id))
        return 0

    print("RELAUNCH")
    print("AUDIT: adopt-or-relaunch found no live run for item %s; caller relaunches "
          "(no state change)" % item_id)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("usage: adopt_or_relaunch.py <project> <workstream> <item-id> "
              "<live-runs.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv))
