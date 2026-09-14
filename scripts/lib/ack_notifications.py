#!/usr/bin/env python3
"""ack-notifications.sh worker: mark notification records delivered.

Runs under the project mutex (acquired by the entry-point wrapper).
For each given id, sets delivered_at=now where it is currently null in
notifications.jsonl (records: {id, run_id, workstream, event, copy,
created_at, delivered_at}). Already-delivered records are untouched.
Reports ACKED <n> where n is the number of records transitioned.

Stdout protocol: line 1 = result token; AUDIT:/NOTIFY: lines follow.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dfstate


def main(argv):
    project = argv[1]
    ids = argv[2:]
    want = set(ids)

    npath = os.path.join(dfstate.projdir(project), "notifications.jsonl")
    records = []
    if os.path.exists(npath):
        with open(npath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

    ts = dfstate.now_iso()
    marked = 0
    for r in records:
        if r.get("id") in want and r.get("delivered_at") is None:
            r["delivered_at"] = ts
            marked += 1

    if marked:
        tmp = "%s.tmp.%d" % (npath, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp, npath)

    print("ACKED %d" % marked)
    print("AUDIT: ack-notifications marked %d record(s) delivered" % marked)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: ack_notifications.py <project> <id> [<id>...]",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv))
