#!/usr/bin/env bash
# record-replies.sh — append a verbatim user reply to an item's reply file.
# Usage: record-replies.sh <project> <item-id> --message-id <mid> --input <file>
# Under one mutex acquisition: if <mid> already has a "## <ts> <mid>" header
# in user-replies/<item-id>.md, prints DEDUPED (exit 0); otherwise appends
# the entry via temp file + atomic rename and prints RECORDED.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib/common.sh"

usage() { echo "usage: record-replies.sh <project> <item-id> --message-id <mid> --input <file>" >&2; exit 2; }

[ "$#" -ge 2 ] || usage
project="$1"; item_id="$2"; shift 2
projdir="$(df_projdir "$project")" || exit 2
df_validate_slug "$item_id" "item id" >/dev/null || exit 2

mid=""; input=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --message-id) [ "$#" -ge 2 ] || usage; mid="$2"; shift 2 ;;
    --input)      [ "$#" -ge 2 ] || usage; input="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$mid" ] || usage
[ -n "$input" ] || usage
case "$mid" in
  *[!-a-zA-Z0-9_.:]*)
    echo "record-replies.sh: invalid message id '$mid'" >&2; exit 2 ;;
esac
[ -f "$input" ] || { echo "record-replies.sh: input file not found: $input" >&2; exit 2; }

exec "$SCRIPT_DIR/mutex.sh" "$project" -- python3 - "$projdir" "$item_id" "$mid" "$input" <<'PYEOF'
import sys, os, re, tempfile, datetime

projdir, item_id, mid, input_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
SCRIPT = "record-replies.sh"
INVOKER = os.environ.get("DF_INVOKER", "cli")

def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

replies_dir = os.path.join(projdir, "user-replies")
os.makedirs(replies_dir, exist_ok=True)
path = os.path.join(replies_dir, item_id + ".md")

existing = ""
if os.path.exists(path):
    with open(path) as f:
        existing = f.read()

for line in existing.splitlines():
    m = re.match(r"^## \S+ (\S+)\s*$", line)
    if m and m.group(1) == mid:
        print("DEDUPED")
        sys.exit(0)

with open(input_path) as f:
    contents = f.read()

entry = "## " + now() + " " + mid + "\n" + contents
if not entry.endswith("\n"):
    entry += "\n"
entry += "\n"

fd, tmp = tempfile.mkstemp(dir=replies_dir, prefix=".tmp-")
try:
    with os.fdopen(fd, "w") as f:
        f.write(existing + entry)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise

with open(os.path.join(projdir, "audit.log"), "a") as f:
    f.write(f"{now()} {INVOKER} {SCRIPT} record-replies {item_id} mid={mid}\n")
    f.flush()
    os.fsync(f.fileno())

print("RECORDED")
PYEOF
