# lib/run.sh — run a state worker under the project mutex and demux stdout.
# Sourced by entry points (after lib/common.sh). Requires DF_SCRIPTS_DIR.
#
# Worker stdout protocol (first line is the machine-readable result token):
#   line 1:            result token (e.g. ARMED, CONFIRMED, ABORT_MULTIPLE)
#   AUDIT: <message>   consumed here -> df_audit (never echoed)
#   NOTIFY: <copy>     echoed after the result token for the caller to deliver
#
# Usage: df_run_under_mutex <project> <script-name> -- <cmd> [args...]
# Exits with the worker's exit status.
# shellcheck disable=SC2148

df_run_under_mutex() {
  local project="$1" script_name="$2"
  shift 2
  [ "${1:-}" = "--" ] || {
    echo "df_run_under_mutex: expected -- before command" >&2
    return 2
  }
  shift
  [ "$#" -ge 1 ] || {
    echo "df_run_under_mutex: no command given" >&2
    return 2
  }

  local out rc line
  out="$(mktemp)"
  rc=0
  "$DF_SCRIPTS_DIR/mutex.sh" "$project" -- "$@" >"$out" || rc=$?

  # Audit lines are consumed, never echoed. Everything else (result token
  # first, then NOTIFY: lines / multi-line payloads) goes to stdout as-is.
  while IFS= read -r line; do
    df_audit "$project" "$script_name" "${line#AUDIT: }"
  done < <(grep '^AUDIT: ' "$out" 2>/dev/null || true)

  if [ ! -s "$out" ]; then
    printf 'ERROR\n'
  else
    grep -v '^AUDIT: ' "$out" || true
  fi

  rm -f "$out"
  return "$rc"
}
