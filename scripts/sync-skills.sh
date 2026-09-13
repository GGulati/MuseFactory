#!/usr/bin/env bash
# sync-skills.sh — install/update the MuseFactory skills from this repo.
#
# The repo is the source of truth. This script makes the installed copy
# (~/workspace/skills/develop by default) exactly match the repo, so the two
# can never drift. Re-run it after every `git pull`.
#
# Usage:
#   scripts/sync-skills.sh            # sync repo -> installed copy
#   scripts/sync-skills.sh --check    # report drift without changing anything
#
# Override the install target (default: ~/workspace/skills/develop):
#   MUSE_WORKSPACE=/path/to/workspace scripts/sync-skills.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/skills/develop"
TARGET="${MUSE_WORKSPACE:-$HOME/workspace}/skills/develop"

if [[ ! -f "$SRC/SKILL.md" ]]; then
  echo "error: repo source not found: $SRC/SKILL.md" >&2
  exit 2
fi

if [[ "${1:-}" == "--check" ]]; then
  if [[ ! -d "$TARGET" ]]; then
    echo "drift: installed copy missing at $TARGET"
    exit 1
  fi
  if diff -r -q "$SRC" "$TARGET" > /dev/null; then
    echo "in sync: $TARGET matches the repo"
    exit 0
  else
    echo "drift detected between repo and $TARGET:"
    diff -r "$SRC" "$TARGET" || true
    exit 1
  fi
fi

mkdir -p "$TARGET"
if command -v rsync > /dev/null; then
  rsync -a --delete "$SRC/" "$TARGET/"
else
  rm -rf "$TARGET"
  mkdir -p "$TARGET"
  cp -r "$SRC/." "$TARGET/"
fi

[[ -f "$TARGET/SKILL.md" ]] || { echo "error: sync failed, SKILL.md missing at $TARGET" >&2; exit 2; }
echo "synced: $SRC -> $TARGET"
