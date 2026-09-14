#!/usr/bin/env python3
"""prepare-launch.sh worker: the OTP already_started in-flight guard.

Runs under the project mutex (acquired by the entry-point wrapper).
Strict live-run check per the section 11.4 candidate filter:
  exactly one live run for (project, item) -> adopt it (record run_id)
  zero live runs                       -> arm the launch (run_id=null)
  more than one                        -> fail closed, notify, exit 5

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
        print("NOTIFY: Could not read live-run data for %s — not launching "
              "until a human looks. (%s)" % (item_id, e))
        print("AUDIT: prepare-launch abort: unreadable live-runs file: %s" % e)
        return 5

    cp = dfstate.load_checkpoint(project, workstream)
    if cp is None:
        print("NO_CHECKPOINT")
        print("NOTIFY: No checkpoint for workstream %s — refusing to launch blind."
              % workstream)
        print("AUDIT: prepare-launch abort: checkpoint missing for workstream %s"
              % workstream)
        return 5

    cands = dfstate.adoption_candidates(
        live_runs, project, item_id, ref, armed_at=cp.get("armed_at"))
    ts = dfstate.now_iso()

    if len(cands) > 1:
        ids = ",".join(str(c.get("run_id")) for c in cands)
        print("ABORT_MULTIPLE")
        print("NOTIFY: Found %d live runs for %s — not launching until a human "
              "looks." % (len(cands), item_id))
        print("AUDIT: prepare-launch abort: %d live candidates for item %s (%s)"
              % (len(cands), item_id, ids))
        return 5

    if len(cands) == 1:
        rid = cands[0].get("run_id")
        cp["run_id"] = rid
        cp["armed_at"] = ts
        dfstate.save_checkpoint(project, workstream, cp)
        print("ADOPTED %s" % rid)
        print("AUDIT: prepare-launch adopted live run %s for item %s"
              % (rid, item_id))
        return 0

    cp["run_id"] = None
    cp["armed_at"] = ts
    dfstate.save_checkpoint(project, workstream, cp)
    print("ARMED")
    print("AUDIT: prepare-launch armed launch for item %s (no live runs)" % item_id)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("usage: prepare_launch.py <project> <workstream> <item-id> "
              "<live-runs.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv))
