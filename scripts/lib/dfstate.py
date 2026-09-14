#!/usr/bin/env python3
"""Shared state helpers for dev-factory entry points. Not an entry point itself.

Imported by the lib/*_<name>.py workers, which all run under the project
mutex (acquired by their entry-point wrappers). This module never acquires
the mutex.
"""
import datetime
import json
import os


def home():
    return os.environ.get(
        "DEV_FACTORY_HOME", os.path.expanduser("~/workspace/dev-factory")
    )


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def now_dt():
    return datetime.datetime.now(datetime.timezone.utc)


def projdir(project):
    return os.path.join(home(), "projects", project)


def checkpoint_path(project, workstream):
    return os.path.join(projdir(project), "checkpoints", workstream + ".json")


def load_checkpoint(project, workstream):
    """Return the checkpoint dict, or None when the file does not exist."""
    p = checkpoint_path(project, workstream)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(project, workstream, cp):
    """Atomic temp-file + rename write of the checkpoint."""
    p = checkpoint_path(project, workstream)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cp, f, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def parse_iso(s):
    """Parse an ISO-8601 timestamp (trailing Z accepted). None on failure."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def fresh_within(ts, seconds, ref):
    dt = parse_iso(ts)
    if dt is None:
        return False
    return (ref - dt).total_seconds() <= seconds


# Statuses that count as "live" for the adoption filter (plan §11.4:
# paused counts as live only for foreign-pause detection, never adoption).
LIVE_STATUSES = ("running", "queued")


def adoption_candidates(live_runs, project, item_id, ref, armed_at=None):
    """Plan §11.4 strict orphan adoption filter.

    A candidate must satisfy ALL of:
      - status in {running, queued} (paused is NEVER adopted)
      - args.project == project and args.item_id == item_id
      - heartbeat_at within 5 min, OR
        (heartbeat_at null AND started_at within 10 min)  -- just-started grace
      - started_at within 10 min of the checkpoint's latest armed_at
        (armed_at=None skips this check; callers with a checkpoint pass it)
    """
    out = []
    armed_dt = parse_iso(armed_at) if armed_at else None
    for r in live_runs or []:
        if not isinstance(r, dict):
            continue
        if r.get("status") not in LIVE_STATUSES:
            continue
        args = r.get("args") or {}
        if args.get("project") != project or args.get("item_id") != item_id:
            continue
        hb = r.get("heartbeat_at")
        if hb is not None:
            if not fresh_within(hb, 5 * 60, ref):
                continue
        elif not fresh_within(r.get("started_at"), 10 * 60, ref):
            continue
        if armed_dt is not None:
            started = parse_iso(r.get("started_at"))
            if started is None or abs((started - armed_dt).total_seconds()) > 600:
                continue
        out.append(r)
    return out


def load_live_runs(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("live-runs file must contain a JSON array")
    return data
