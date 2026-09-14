#!/usr/bin/env python3
"""Canonical backlog block operations for the dev-factory.

Single implementation used by:
  - lib/backlog-lib.sh (thin bash wrappers calling this CLI), and
  - apply-envelope.sh (imports this module directly).

This module never acquires the project mutex itself; callers are
responsible for holding it (backlog.sh acquires; apply-envelope.sh calls
these functions while already holding its own acquisition -- never a
nested acquisition, per plan Tech C2).

Backlog format: top-level bullets are lines starting with `- ` or `* ` at
column 0. A block is the bullet line plus following indented or blank
lines, up to (not including) the next top-level bullet. Item id = slug of
the bullet's first-line text: lowercase, runs of non-alphanumeric become a
single hyphen, max 40 chars.

All mutations are idempotent and written via temp file + atomic rename.
"""
import os
import re
import sys
import tempfile


def slug(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40]


def _blocks(lines):
    """Return list of dicts {id, title, start, end} (end exclusive)."""
    blocks = []
    cur = None
    for i, line in enumerate(lines):
        if re.match(r"^[-*] ", line):
            if cur is not None:
                blocks.append(cur)
            title = re.sub(r"^[-*] ", "", line).rstrip("\n")
            cur = {"id": slug(title), "title": title, "start": i, "end": i + 1}
        elif cur is not None:
            if line.startswith(" ") or line.startswith("\t") or line.strip() == "":
                cur["end"] = i + 1
            else:
                # Non-indented, non-blank, non-bullet line: ends the block;
                # re-process this line as a potential new bullet.
                blocks.append(cur)
                cur = None
                if re.match(r"^[-*] ", line):
                    title = re.sub(r"^[-*] ", "", line).rstrip("\n")
                    cur = {"id": slug(title), "title": title, "start": i, "end": i + 1}
    if cur is not None:
        blocks.append(cur)
    return blocks


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def _write_atomic(path, lines):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".backlog-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
        os.rename(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def remove(path, item_id):
    """Remove the item's block. Idempotent: no-op when absent."""
    lines = _read(path)
    blocks = _blocks(lines)
    kept = []
    removed = False
    for b in blocks:
        if b["id"] == item_id and not removed:
            removed = True
            continue
        kept.append(b)
    if not removed:
        return False
    out = []
    for b in kept:
        out.extend(lines[b["start"]:b["end"]])
    # Collapse 3+ consecutive blank lines that a removal may leave behind.
    final = []
    blanks = 0
    for ln in out:
        if ln.strip() == "":
            blanks += 1
            if blanks <= 2:
                final.append(ln)
        else:
            blanks = 0
            final.append(ln)
    _write_atomic(path, final)
    return True


def move_to_bottom(path, item_id):
    """Move the item's block to the end. No-op when absent or already last."""
    lines = _read(path)
    blocks = _blocks(lines)
    idx = next((i for i, b in enumerate(blocks) if b["id"] == item_id), None)
    if idx is None or idx == len(blocks) - 1:
        return False
    block_lines = lines[blocks[idx]["start"]:blocks[idx]["end"]]
    rest = []
    for i, b in enumerate(blocks):
        if i != idx:
            rest.extend(lines[b["start"]:b["end"]])
    # Ensure exactly one blank line separates the moved block.
    while rest and rest[-1].strip() == "":
        rest.pop()
    rest.append("\n")
    rest.extend(block_lines)
    if rest and not rest[-1].endswith("\n"):
        rest[-1] += "\n"
    _write_atomic(path, rest)
    return True


def get(path, item_id):
    """Return the item's block text, or None when absent."""
    lines = _read(path)
    for b in _blocks(lines):
        if b["id"] == item_id:
            return "".join(lines[b["start"]:b["end"]])
    return None


def title(path, item_id):
    """Return the item's first-line title, or None when absent."""
    lines = _read(path)
    for b in _blocks(lines):
        if b["id"] == item_id:
            return b["title"]
    return None


def top_open(path):
    """Return the id of the first top-level bullet, or None when empty."""
    lines = _read(path)
    blocks = _blocks(lines)
    return blocks[0]["id"] if blocks else None


def _cli():
    if len(sys.argv) < 3:
        print("usage: backlog.py <remove|move-to-bottom|get|top-open|title> <file> [item-id]",
              file=sys.stderr)
        return 2
    op, path = sys.argv[1], sys.argv[2]
    item_id = sys.argv[3] if len(sys.argv) > 3 else None
    if not os.path.exists(path):
        print(f"backlog.py: file not found: {path}", file=sys.stderr)
        return 2
    if op == "remove":
        print("REMOVED" if remove(path, item_id) else "NOT_FOUND")
    elif op == "move-to-bottom":
        print("MOVED" if move_to_bottom(path, item_id) else "NOT_FOUND_OR_LAST")
    elif op == "get":
        block = get(path, item_id)
        if block is None:
            print("NOT_FOUND")
            return 1
        sys.stdout.write(block)
    elif op == "title":
        t = title(path, item_id)
        if t is None:
            print("NOT_FOUND")
            return 1
        print(t)
    elif op == "top-open":
        t = top_open(path)
        if t is None:
            print("EMPTY")
            return 1
        print(t)
    else:
        print(f"backlog.py: unknown op {op}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
