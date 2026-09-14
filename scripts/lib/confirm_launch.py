#!/usr/bin/env python3
"""confirm-launch.sh worker: confirm-CAS after the caller launches.

Runs under the project mutex (acquired by the entry-point wrapper).
  --chain-token <tok> (chain completion): CAS on chain_intent.claim.token
      (mismatch -> CAS_ABORT, exit 3); the launched run is authoritative and
      overwrites any recorded run_id; the arming write completes the chain:
      current_item = chain_intent.next_item, questions = [],
      parked_at/paused_at = null, chain_intent = null. CONFIRMED.
  recorded run_id == launched run_id -> CONFIRMED (idempotent)
  recorded run_id null/empty          -> record it (+armed_at=now); CONFIRMED
  recorded run_id is a different id  -> ADOPT_RECORDED <cur>, exit 6
                                       (caller stops the just-launched run
                                       and adopts the recorded one).

Stdout protocol: line 1 = result token; AUDIT:/NOTIFY: lines follow.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dfstate


def usage():
    print("usage: confirm_launch.py <project> <workstream> <launched-run-id> "
          "[--chain-token <tok>]", file=sys.stderr)


def main(argv):
    project, workstream, launched = argv[1], argv[2], argv[3]
    rest = argv[4:]
    chain_token = None
    if rest:
        if len(rest) != 2 or rest[0] != "--chain-token" or not rest[1]:
            usage()
            return 2
        chain_token = rest[1]

    cp = dfstate.load_checkpoint(project, workstream)
    if cp is None:
        print("NO_CHECKPOINT")
        print("NOTIFY: No checkpoint for workstream %s — cannot confirm the launch."
              % workstream)
        print("AUDIT: confirm-launch abort: checkpoint missing for workstream %s"
              % workstream)
        return 5

    cur = cp.get("run_id")
    ts = dfstate.now_iso()

    def chain_matches():
        ci = cp.get("chain_intent") or {}
        claim = ci.get("claim") or {}
        return bool(ci.get("next_item")) and claim.get("token") == chain_token

    def complete_chain():
        next_item = cp["chain_intent"]["next_item"]
        cp["current_item"] = next_item
        cp["questions"] = []
        cp["parked_at"] = None
        cp["paused_at"] = None
        cp["chain_intent"] = None
        cp["armed_at"] = ts

    # Chain completion path: a matching claim token makes the launched run
    # authoritative -- it overwrites any recorded run_id (the recorded run is
    # the previous item's terminal run, already reconciled via the ledger).
    if chain_token is not None:
        if not chain_matches():
            print("CAS_ABORT")
            print("AUDIT: confirm-launch CAS abort: chain claim token mismatch "
                  "(expected a claim matching the supplied token)")
            return 3
        next_item = cp["chain_intent"]["next_item"]
        complete_chain()
        cp["run_id"] = launched
        dfstate.save_checkpoint(project, workstream, cp)
        print("CONFIRMED")
        print("AUDIT: confirm-launch confirmed %s; chain completed to item %s"
              % (launched, next_item))
        return 0

    # Idempotent confirm: the recorded run is the one we launched.
    if cur == launched:
        print("CONFIRMED")
        return 0

    # Nothing recorded: record the launched run.
    if not cur:
        cp["run_id"] = launched
        cp["armed_at"] = ts
        dfstate.save_checkpoint(project, workstream, cp)
        print("CONFIRMED")
        print("AUDIT: confirm-launch confirmed run %s" % launched)
        return 0

    # A different run is recorded: the twin-run loser adopts the winner.
    print("ADOPT_RECORDED %s" % cur)
    print("AUDIT: confirm-launch conflict: recorded run %s wins over just-launched "
          "%s; caller stops the loser and adopts the recorded run" % (cur, launched))
    return 6


if __name__ == "__main__":
    if len(sys.argv) < 4 or len(sys.argv) > 6:
        usage()
        sys.exit(2)
    if not sys.argv[3]:
        usage()
        sys.exit(2)
    sys.exit(main(sys.argv))
