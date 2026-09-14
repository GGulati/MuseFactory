# lib/common.sh — shared helpers for dev-factory scripts.
# Sourced, never executed directly. Requires bash.
# shellcheck disable=SC2148

# Home of the dev-factory state tree (overridable for tests).
df_home() {
  printf '%s' "${DEV_FACTORY_HOME:-$HOME/workspace/dev-factory}"
}

# Validate a generic slug (project names, item ids). Echoes the value.
df_validate_slug() {
  local value="${1:-}" what="${2:-slug}"
  if ! [[ "$value" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "invalid $what: '$value'" >&2
    return 2
  fi
  printf '%s' "$value"
}

# Validate a project slug and echo its state directory.
df_projdir() {
  local project
  project="$(df_validate_slug "${1:-}" "project slug")" || return 2
  printf '%s' "$(df_home)/projects/$project"
}

# Validate a workstream name and echo it.
df_validate_workstream() {
  local ws="${1:-}"
  if ! [[ "$ws" =~ ^(default|pin-[a-z0-9][a-z0-9-]*)$ ]]; then
    echo "invalid workstream: '$ws'" >&2
    return 2
  fi
  printf '%s' "$ws"
}

# UTC timestamp, ISO-8601 with Z.
df_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# Append one audit line: "<ts> <invoker> <script> <message>".
# Every mutating script calls this exactly once per mutation.
df_audit() {
  local project="$1" script="$2" message="$3"
  local projdir ts invoker
  projdir="$(df_projdir "$project")" || return 2
  mkdir -p "$projdir"
  ts="$(df_now)"
  invoker="${DF_INVOKER:-cli}"
  printf '%s %s %s %s\n' "$ts" "$invoker" "$script" "$message" >>"$projdir/audit.log"
}

# Random hex id (for notification records etc.).
df_uuid() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr 'A-Z\n' 'a-z' | tr -d '\n'
  else
    python3 -c 'import uuid,sys; sys.stdout.write(uuid.uuid4().hex)'
  fi
}
