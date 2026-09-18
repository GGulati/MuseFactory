#!/usr/bin/env bash
# sync-skills.sh — install/update the MuseFactory skills from this repo.
#
# The repo is the source of truth. This script makes the installed copies
# (~/workspace/skills/<name> by default) exactly match the repo, so the two
# can never drift. Re-run it after every `git pull`.
#
# Usage:
#   scripts/sync-skills.sh            # sync repo -> installed copies
#   scripts/sync-skills.sh --check    # report drift without changing anything
#
# Override the install target (default: ~/workspace/skills):
#   MUSE_WORKSPACE=/path/to/workspace scripts/sync-skills.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${MUSE_WORKSPACE:-$HOME/workspace}/skills"

CHECK=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK=1
fi

drift=0
for src in "$REPO_ROOT"/skills/*/; do
  [[ -f "$src/SKILL.md" ]] || continue
  name="$(basename "$src")"
  target="$TARGET_ROOT/$name"

  if [[ "$CHECK" == "1" ]]; then
    if [[ ! -d "$target" ]]; then
      echo "drift: installed copy missing at $target"
      drift=1
    elif ! diff -r -q "$src" "$target" > /dev/null; then
      echo "drift detected between repo and $target:"
      diff -r "$src" "$target" || true
      drift=1
    else
      echo "in sync: $target"
    fi
    continue
  fi

  mkdir -p "$target"
  if command -v rsync > /dev/null; then
    rsync -a --delete "$src" "$target/"
  else
    rm -rf "$target"
    mkdir -p "$target"
    cp -r "$src/." "$target/"
  fi

  [[ -f "$target/SKILL.md" ]] || { echo "error: sync failed, SKILL.md missing at $target" >&2; exit 2; }
  echo "synced: $src -> $target"
done

exit "$drift"
