# lib/backlog-lib.sh — thin bash wrappers over the canonical lib/backlog.py.
# Sourced, never executed directly. Shared logic lives in backlog.py;
# these wrappers keep the bl_* function names/signatures from the spec.
# shellcheck disable=SC2148

_df_bl_libdir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# bl_remove <file> <item-id> — idempotent no-op when absent.
bl_remove() {
  python3 "$_df_bl_libdir/backlog.py" remove "$@"
}

# bl_move_to_bottom <file> <item-id> — idempotent no-op when absent or last.
bl_move_to_bottom() {
  python3 "$_df_bl_libdir/backlog.py" move-to-bottom "$@"
}

# bl_get <file> <item-id> — prints the item's block; exit 1 when absent.
bl_get() {
  python3 "$_df_bl_libdir/backlog.py" get "$@"
}

# bl_top_open <file> — prints the first top-level bullet's id; exit 1 when none.
bl_top_open() {
  python3 "$_df_bl_libdir/backlog.py" top-open "$@"
}

# bl_title <file> <item-id> — prints the item's first-line title; exit 1 when absent.
bl_title() {
  python3 "$_df_bl_libdir/backlog.py" title "$@"
}
