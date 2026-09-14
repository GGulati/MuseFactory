# SUPERVISOR.md — dev-factory supervisor runbook

This file is the complete runbook for the dev-factory **supervisor** role: the
agent-side turn that owns user intent, applies terminal envelopes, and
restarts workers. A fresh-context agent with only this file open must be able
to execute the protocol correctly.

Source of truth for the design: the plan (v6) §§5, 7, 8, 9.2, 11, 12, 14.
This file distills it into executable rules. Where this file and the plan
disagree, the plan wins — flag the drift, don't improvise.

## 0. Mental model (OTP cut)

- **Supervisor (you)** = OTP supervisor process. You own user intent, apply
  terminal envelopes, and restart workers. You never edit state directly:
  every mutation goes through `scripts/` entry points.
- **Tick (cron worker)** = liveness monitor. It never interprets user intent,
  never touches chats. It runs the same deterministic recovery scripts you do.
- **Workers (workflow runs)** = OTP worker processes. One run handles one
  backlog item and exits. They never push, merge, delete branches, or edit
  the backlog. All they do is run phases and return a terminal envelope.
- **Files are message queues, not workers.** `pending_intents`,
  `chain_intent`, `pending_relay`, `notifications.jsonl` are durable
  mailboxes; either you or the tick can drain them.

### Standing invariants (non-negotiable)

1. One workflow run handles one item and exits. No relaunch loops.
2. Nothing is implicitly approved. An ambiguous reply never resumes.
3. Replies are preserved verbatim; unanswered questions are repeated
   byte-identically.
4. Wake on any reply while parked: resume both blocked and awaiting-approval
   items.
5. Workers never push, merge, delete branches, or directly edit the backlog.
6. Scripts never launch workflows, and never hold the mutex across a launch.
7. Workspace-only replies never enter repositories or Git history.
8. `handled_run_ids`, `notifications.jsonl`, `audit.log` are append-only.
9. Never advance the chat cursor before intents complete (cardinal sin).
10. Never guess a chat id, workstream name, item id, run id, or copy string —
    read them from state or the plan.

## 1. The serialization contract (§8.1)

Two parties (your turns, the tick) mutate shared state. Neither holds
exclusion across reasoning. Instead, **every mutation is a deterministic
script invocation**:

- **One project-wide mutex, one acquisition per entry point.**
  `scripts/mutex.sh` (mkdir-based, one lock dir per project) is acquired once
  per entry-point invocation around a single read-modify-write (temp file +
  atomic rename), held for milliseconds. Acquired only by top-level entry
  points: `checkpoint.sh`, `apply-envelope.sh`, `backlog.sh` (standalone),
  `record-replies.sh`, `record-death.sh`, `prepare-launch.sh`,
  `confirm-launch.sh`, `adopt-or-relaunch.sh`, and `tick.sh`'s phases. Shared
  logic lives in `scripts/lib/*.sh`, sourced — never executed as children —
  so nothing ever re-acquires.
- **Guarded files** (all under `~/workspace/dev-factory/projects/<project>/`,
  or `$DEV_FACTORY_HOME` in tests): `checkpoints/<workstream>.json`,
  `tombstones/<workstream>.json`, `backlog.md`, `handled_run_ids`,
  `tick-health.json`, `notifications.jsonl`, `project.json` → the project
  mutex via entry points. `user-replies/<item-id>.md` → the project mutex via
  `record-replies.sh` (temp+rename + message-id dedupe make concurrent
  appends safe).
- **Acquire failures are transient, never silent.** Scripts retry with
  backoff up to 10 s, then exit non-zero. A chat turn retries the script call
  with backoff up to ~60 s; if still failing, **do not advance the cursor**
  — the un-advanced cursor is the redrive mechanism (the next turn
  re-drains; message-id dedupe skips recorded ids) — and tell the user what
  blocked. The tick defers to its next cycle. Replies are never lost to
  contention.
- **Compare-and-swap (CAS).** Every mutating entry point takes
  `--expect key=value` preconditions and aborts (exit 3) on mismatch. On
  abort: re-read and retry — **except** when the re-read shows the checkpoint
  became a tombstone: then follow the tombstone path (§2 step 6), never the
  original protocol. CAS-abort→tombstone is a first-class runbook case.
- **Exactly-once via `handled_run_ids`.** Every envelope application checks
  the append-only ledger under the mutex (`grep -Fxq`, exact-line match) and
  appends after applying. Handoff turns and the tick run the same
  `apply-envelope.sh`; the loser sees the ledger and skips. Match on
  **run_id**, never just item_id. The ledger is never pruned.
- **Idempotent actions are the backstop.** Backlog applies, checkpoint
  transitions, chain arms, and ledger appends are all idempotent. A crash
  between mutation and ledger-append converges on re-run; the ledger is the
  fast path, idempotency is the guarantee.
- **Adopt-or-launch on every launch path** (OTP `already_started`):
  `prepare-launch.sh` (mutex: strict live-run check — fresh heartbeat or
  just-started grace; exactly-one live run for (project, item) is **adopted**,
  zero arms the launch, >1 fails closed with a deduped notification) →
  **release** → the caller issues the launch tool call → `confirm-launch.sh`
  (mutex, CAS: recorded == just-launched → confirm and proceed; a different
  recorded id → `workflow.stop` the just-launched run and adopt the recorded
  one). Initial launches, intent replays, tick relaunches, and chain steps all
  use this path. The tick's orphan branch skips checkpoints armed within the
  last 60 s (in-flight launch grace).
- **Audit.** Every entry-point invocation appends `timestamp invoker
  mutation` to `audit.log`. Deviations from this protocol are detectable
  after the fact (that's what the T5 conformance probe checks).

## 2. The turn protocol (§8.2)

**Trigger.** The protocol runs when the turn's `chat_id` matches a
checkpoint's `chats[]` or a tombstone's `chat_id` (§9.2). Otherwise it does
not run.

**Step 1 — Handoff first.** If this turn carries a terminal handoff —
wherever it landed (handoffs arrive on the runtime's channel, observed on
main; the plan does not assume the project chat) — route by run identity,
not by chat: extract `run_id` from the handoff, resolve `{project, item_id}`
from the run's `args_json`, then run:

```
apply-envelope.sh <project> <workstream> <envelope.json> <run-id>
```

The script dedupes via the ledger; running it twice is safe. The handoff
turn announces nothing on main — the notification routes to the workstream's
chat (§6). The tick backstop covers handoffs that never surface as a turn.

**Step 2 — Drain chat messages since the cursor.** The cursor is a
best-effort high-water mark; dedupe by the message-id headers in the replies
file is authoritative. **Do not advance the cursor until step 5.**

Classify each message:

- **reply** — answers a parked question, or chatter.
- **directive** — `stop`, `go`, `retry`, `skip`, `drop`, `start` (with an
  optional item id).
- **misdirected** — belongs to another workstream (§7).

**Approval-gate tie-break (nothing is implicitly approved):**

- An ambiguous reply to an awaiting-approval gate ("ok, let me think",
  "looks fine?") **does not resume** — ask a one-line confirmation.
- A second consecutive ambiguous reply re-asks the approval question
  **byte-identically** with a one-line note: "I still need a clear yes or
  no." — still no resume.

**Step 3 — Record.** Append new messages **verbatim** to
`user-replies/<item-id>.md` with `## <ISO-8601> <message-id>` headers, via
whole-file temp+rename:

```
record-replies.sh <project> <item-id> --message-id <mid> --input <file>
```

Dedupe source is the message-id headers in this file, **not** the checkpoint
cursor — a crash between recording and cursor-advance re-drains and skips
already-recorded ids. Readers never see torn lines; concurrent appends are
serialized by the project mutex.

**Step 4 — Set pending intents** via `checkpoint.sh`:

- A list of `{message_id, kind, action}` with kind `{reply, directive}`.
- Closed action set — reply → `resume-with-replies` / `acknowledge`;
  directive → `stop` / `go` / `retry` / `skip` / `drop` / `start` (same
  vocabulary as §9.2).
- **Only unresolvable or deferred classifications become intents** (e.g.
  `go` / `retry` / `start` while stopping). Everything else is consumed by
  the turn.
- Chain completion uses `chain_intent`, never `pending_intents`;
  tombstone re-registration executes inline (step 6).
- Ordering is fixed: replies are recorded (step 3) **before** the checkpoint
  write — the two files are never "atomic"; the ordering plus dedupe is what
  makes crashes safe.

**Step 5 — Complete intents in order via the scripts** (adopt-or-launch for
launches), advance the cursor past the drained messages, clear the intents —
one `checkpoint.sh` CAS per transition.

**Step 6 — Tombstone match.** If the chat matched a tombstone rather than a
checkpoint:

- `one_shot_complete` (pinned, finished): answer
  **"That pinned workstream is complete — say start <item> to run it
  again."** Do not re-register.
- Otherwise, if the turn carries a reply referencing the item or a
  `go`/`retry`/`start` directive: re-register fresh — new checkpoint
  (generation+1), archive `user-replies/<item-id>.md` to
  `user-replies/<item-id>.gen<N>.md` (week-old answers never suppress
  re-asking), then record the triggering reply into the new generation's
  file and process it normally.
- A tombstoned workstream with no referencing reply/directive: the protocol
  does not run.

**Wake on any reply while parked.** Steps 2–5 run for chatter too (cursor
advances, no re-spam); questions are re-asked byte-identically only when a
reply fails to address them. Partial answers relaunch preserving the
answered ones.

**Mid-run reply ack.** A reply classified while the workstream is
`in_progress` gets one line — **"Noted — the run will see it at its next
gate."** — no resume, no re-ask.

**Same-chat turn overlap.** Two turns in one chat interleave only at script
boundaries (each `scripts/` invocation is atomic under the project mutex).
Both turns call `record-replies.sh` — message-id dedupe makes the
double-record a no-op. Both set intents via `checkpoint.sh --expect
cursor=<old>` — the loser's CAS aborts, it re-reads (sees the winner's
cursor and intents) and converges: no double launch (adopt-or-launch), no
lost reply (dedupe). A turn that crashes anywhere before step 5 leaves the
cursor un-advanced; the next turn re-drains. **Cursor-advance-early is the
cardinal sin: never advance the cursor before intents complete.**

## 3. Terminal envelope application (`apply-envelope.sh`, §8.3)

One script, two callers (handoff turns, tick recovery). Under the project
mutex: ledger check → idempotent apply → ledger append → release.

Per status:

- **done:** apply reconciliations via the sourced backlog-apply lib function
  (idempotent) → mark item done → arm durable `chain_intent`
  `{next_item, armed_at, claim: null}` in the checkpoint **before closing**
  the item, `next_item` bound at arm time → ledger append → append the
  notification record → release. Chain completion happens after release via
  the claim → release → launch → confirm protocol below. A crash between
  arming and completion leaves `chain_intent` set; the next drain completes
  it. **Pinned workstreams never chain:** for a pinned checkpoint the done
  path arms nothing and writes a `one_shot_complete` tombstone instead.
  Notification: per-item completion note + next-item started note (§6
  routing).
- **blocked / awaiting-approval:** checkpoint → `parked`, questions stored
  byte-identically, `parked_at=now`. Notify with the questions verbatim. A
  blocked envelope carrying `blocked_details` (needs-review, see the
  protocol below) parks with `needs_review` set.
- **failed:** checkpoint → `parked` with `failure_summary`; notify asking
  `retry` / `skip` / `drop`.
- **User retry after a crash-loop escalation:** relaunch and clear
  `death_timestamps` in the same atomic checkpoint write — an explicit retry
  is new information and grants a genuinely fresh window.
- **Unknown status / unparseable envelope:** park + notify **"I couldn't
  understand the run's result — nothing was applied."** Fail closed; never
  drop an envelope.
- **Superseded envelope** (`item_id` no longer the checkpoint's
  `current_item`, or `run_id` already in the ledger): acknowledge and ignore.

### Completing `chain_intent`: claim → release → launch → confirm

Chain completion is never performed under the arming mutex hold, because
launching is a tool call the scripts cannot make. The protocol (run
identically by the supervisor turn and the tick):

1. `checkpoint.sh claim-chain --expect-next <X>` — under the mutex, sets
   `claim={token, claimed_at, by}`; an expect-failure means another drain
   claimed it or the intent was re-armed, so this drain backs off.
2. Release; the caller runs the standard adopt-or-launch for the bound item
   — if the item is no longer open, the caller clears the intent and logs
   instead.
3. The checkpoint write that arms the chained run carries
   `clear_chain_claim=<token>`, so the same CAS that records the new run
   clears the intent atomically; if the launch fails, the caller runs
   `checkpoint.sh release-chain --expect-token <token>` to unclaim for the
   next drain.

A claim older than 10 min with no recorded run for the bound item is stale
and may be reclaimed with a new token. Re-arming supersedes convergently: if
`chain_intent.next_item` changed, in-flight claims for the old value abort on
CAS and the newest arm wins. An intent survives its armed run being
tombstoned or paused — completion checks the intent, not the run.

### Notify-once, durably

The script reports applied vs skipped (ledger hit, superseded, CAS-abort).
Under the **same mutex hold** as the ledger append, the script appends a
notification record to `notifications.jsonl`
(`{id, run_id, workstream, event, copy, created_at, delivered_at: null}`) —
so a crash after the ledger append but before the announcement still leaves
a durable delivery obligation. A turn announces a terminal event **only
when its own invocation returned applied**, then marks the record delivered
(CAS on `delivered_at=null`). The tick's backfill step (§5) delivers any
record still undelivered and marks it — every terminal event is announced
at-least-once from durable state, exactly-once per chat via the delivery
mark. A late handoff racing a tick that already applied the envelope stays
silent — the user hears the news exactly once, from whoever applied it.

### Needs-review protocol (fresh-context reviewers — never in-session)

A blocked envelope may carry `blocked_details: {review_kind: "plan"|"code",
artifact_path: ...}` — this is the develop skill's factory-worker mode
(Rule 7): the worker never reviews in-session, so at the Phase 2 plan gate
and the Phase 6 code-review gate it returns the plan/diff as a needs-review
blocked item instead. `apply-envelope.sh` parks the checkpoint with
`needs_review` set and keeps the blocked_details. The supervisor MUST then:

1. **Spawn a fresh-context reviewer subagent** with the artifact at
   `blocked_details.artifact_path` plus the develop skill's review brief for
   that `review_kind`. The reviewer gets only the artifact and the brief —
   never your session history, never the worker's session history.
2. **Record the reviewer's findings verbatim** in a review file on the
   item's branch in the worktree (e.g. `reviews/<item-id>-<review_kind>.md`)
   — write it before relaunching so the resume run sees it.
3. **Relaunch the worker with the review results** via adopt-or-launch; the
   resume run re-inspects the branch first and treats the review findings
   like any gate reply — it fixes or continues per the review, it never
   re-reviews.
4. The review is **NEVER done in-session** by the supervisor, the tick, or
   the worker that produced the artifact. If the relaunched run hits
   another review gate, its blocked envelope parks the checkpoint again
   with fresh `blocked_details` and the cycle repeats.

## 4. Directives — the complete table (§8.4)

Directive vocabulary: `stop`, `go` (resume), `retry`, `skip`, `drop`,
`start`. Directive text may name an item (`stop item-x`). **Scoping:**

- In the **project chat**: `stop` is **global** (every workstream, stopped
  sequentially); `go` resumes everything the global stop paused, tracked via
  `paused_by="global-stop"` (with no such workstreams it falls back to the
  paused default workstream). `retry`/`skip`/`drop`/`start` target the
  **default** workstream unless they name an item. Pinned workstreams are
  untouched by project-chat directives except global stop.
- In a **pinned chat**: every directive is local to that workstream.
- In the **main chat**: only routing confirmations, project
  setup/registration, and global status questions. Workstream directives
  (`go`/`stop`/`start`/…) in the main chat get **"That controls the
  <project> workstream — say it in the project chat."**

### stop

- **in_progress:** verify-stop protocol — CAS-write `stopping`
  (+`stopping_since`, and `stopping_by`: `"global-stop"` for a project-chat
  stop, `"local-stop"` for a pinned-chat stop — stop provenance; the tick
  propagates it to `paused_by` when the stop resolves, so a project-chat
  `go` can resume everything the global stop paused) → ack
  **"Stopping the run…"** immediately →
  `workflow.stop` → poll → **reconcile-first**: if the run went terminal on
  its own, apply its envelope (reconcile-only, never chain) before any
  ledger bookkeeping → on confirmed stopped, CAS-write `paused` (expect
  `state=stopping`, `run_id`) + ledger-append the stopped run_id + set
  `paused_by` → ack enumerating the workstream. On failure: roll back to
  `in_progress` + notify.
- **Liveness-first:** stop on a dead/missing run acks **"That run already
  ended — nothing to stop."** and reconciles any terminal envelope.
  Shortcut: no live run → no `workflow.stop` call; checkpoint → `paused`
  (+`paused_by`), ack **"Paused — nothing was running."**
- **Already paused:** ack **"already paused."**
- **Repeat stop while `stopping`:** ack exactly
  **"Still stopping the run — one moment."**; no second `workflow.stop`.
  This is the specified copy — use it verbatim.
- **`go` / `retry` / `start` received while stopping** become **durable
  deferred intents**, completed automatically when the stop resolves
  (`paused` → resume/relaunch; rollback → relaunch). The turn acks
  **"Noted — I'll go as soon as the stop lands."**
- **`skip` / `drop` act immediately and supersede the in-flight stop:**
  the verifier's final CAS (expect `state=stopping`, `run_id`) aborts and it
  writes nothing.
- **Project-chat stop is global:** each workstream is stopped sequentially
  with its own verify; the ack enumerates per-workstream outcomes, including
  partial failures: **"Paused A and B; C's stop failed — it's still
  running."** Pinned-chat stop is local.
- **No workstream:** "Nothing is running."
- **Disarmed (tombstone):** "already disarmed."

### go / resume

- **in_progress (live run):** ack **"Already running."**
- **in_progress (dead run):** adopt-or-launch immediately (never "Already
  running" on a corpse).
- **parked:** relaunch via adopt-or-launch with recorded replies; **quote
  any still-unanswered questions byte-identically**.
- `go <item>` targets that item's workstream (paused/parked) or answers
  **"Nothing paused for <item>."**
- A runtime-paused (foreign) run is resumed via `workflow.resume`; if resume
  fails, adopt-or-launch relaunches (orphan-cleanup fallback). Resume the
  paused run if resumable, else relaunch.
- **Project-chat go after a global stop** resumes everything that stop
  paused (`paused_by="global-stop"`); the ack enumerates each resumed
  workstream.
- If the paused item is already done (its envelope was reconciled while
  paused), `go` starts the **next open item** instead of rerunning it.
- Deferred intent while stopping: recorded as a durable deferred intent;
  completed automatically when the stop resolves. Ack **"Noted — I'll go as
  soon as the stop lands."**
- Default tombstone: re-register fresh (§2 step 6).
- `one_shot_complete`: **"That pinned workstream is complete — say start
  <item> to run it again."** (No re-register, no revive.)
- No workstream: "Nothing to resume."

### retry

- **Liveness-first:** live run → **"Already running — say stop first to
  restart it."** Dead run → adopt-or-launch immediately.
- **parked:** relaunch same item; clears the intensity window.
- Durable deferred intent while stopping; runs when the stop resolves.
- Tombstone: re-register fresh (`one_shot_complete`: same "is complete" ack
  as go).
- No workstream: "Nothing to retry."

### skip

- **in_progress:** stop the run; move item to the bottom of the backlog;
  chain next. Confirm: **"Skipped — moved to the bottom."**
- **parked / paused:** move item to bottom; chain next; confirm.
- **stopping:** acts immediately and supersedes the in-flight stop (CAS-safe
  — the verifier's final write aborts and writes nothing): stop the run if
  still live, move item to bottom, chain next, confirm.
- **No workstream:** apply directly — the supervisor runs `backlog.sh` to
  move the item to the bottom; no workstream, no launch. Confirm:
  **"Skipped — moved to the bottom. Say go to resume the workstream."**

### drop

- **in_progress:** stop the run; remove the item; chain next. Confirm:
  **"Dropped."**
- **parked / paused:** remove the item; chain next; confirm.
- **stopping:** acts immediately and supersedes the in-flight stop
  (CAS-safe): stop the run if still live, remove the item, chain next,
  confirm.
- **No workstream:** apply directly via `backlog.sh`. Confirm: **"Dropped.
  Say go to resume the workstream."**

### start

- **With a named item while busy:** ask for confirmation first (state-aware:
  "The default workstream is <state> on <item>. Start a second concurrent
  workstream for <new-item>?" — yes → pin; no → stay).
- Creates (or re-registers) the workstream for the named item and launches
  it.
- **Unknown item id → no launch:** **"I don't see <id> in the backlog."**
- With no item named: ask which backlog item to start — the initial kickoff
  is an explicit user request, conversational or `start <item-id>`.
- **Empty backlog:** "The backlog is empty — add items first."
- Durable deferred intent while stopping; starts when the stop resolves.
- Tombstone: creates (or re-registers) the workstream for the named item
  and launches it.
- No workstream: ask which item; then arm + launch.

**Empty states all ack in one line** (see table). The go-on-parked message
quotes the byte-identical questions, never a paraphrase.

## 5. Tick precedence — what you must not fight (§11.1)

The per-project liveness tick runs every 5 minutes (token-budget decision 2026-09-14; was 2 minutes). Its sweep order is
explicit:

1. Complete pending `chain_intent` (claim → release → launch → confirm).
   Runs unconditionally — silent-user auto-chain advances the backlog.
2. Terminal reconciliation (state-aware): checkpoint with a terminal
   `run_id` absent from `handled_run_ids` → `apply-envelope.sh` from
   `final_result`. Exceptions: `paused`/`stopping` + run stopped →
   ledger-append only (the stop-verify path owns the user-visible outcome);
   `paused` + late done → reconcile state only, never chain.
3. **Notification backfill:** deliver any `notifications.jsonl` records with
   `delivered_at=null`, then mark them delivered (CAS). Pinned-workstream
   entries also append to `pending_relay`.
4. Death detection (live-excluding-paused runs with stale heartbeat) →
   record death timestamp; relaunch subject to intensity.
5. Orphan scan → strict adoption or relaunch (skips checkpoints armed within
   the last 60 s — in-flight launch grace).
6. Foreign pause: checkpoint `in_progress` + run paused → record
   `paused_observed_at`, notify once, do not touch.
7. Inconclusive-stop re-verify; still inconclusive after 30 min → bounded
   fallback to `in_progress` + notify.
8. Anomaly: `paused` + run_id live-and-running → failed stop; notify, don't
   touch. `parked` + unexpected live run → notify, don't adopt.
9. 7-day disarm: `parked`/`paused` older than 7 days → write tombstone
   (mapping preserved), deliver the verbatim disarm message.
10. Unclaimed-run scan: live runs no checkpoint claims, adoption-fresh only,
    once per run_id → notify only.

Overlapping ticks are safe by construction (every phase re-reads under the
mutex; all phases idempotent; anomaly notices deduped via `tick-health.json` —
the key is cleared when the condition clears, so genuine recurrence
re-notifies exactly once). **Do not work around the tick; converge with it.**

### Clock fields (§9.2)

- `parked_at`: set on every transition into `parked`; cleared on
  resume/relaunch/re-park (re-park restarts the 7-day clock).
- `paused_at`: set on entering `paused`; cleared on go/resume.
- `stopping_since`: set on entering `stopping`; cleared when the stop
  resolves.
- `stopping_by`: written as `"global-stop"` / `"local-stop"` together
  with `stopping` (§4 stop); the tick propagates it to `paused_by` when the
  stop resolves and clears it there.
- `paused_by`: set to `global-stop` / `local-stop` on entering `paused` via
  the stop path; cleared on go/resume/relaunch.
- `armed_at`: refreshed on every (re)launch — anchors the adoption
  start-window.
- Stop-while-parked → paused: clears `parked_at`, sets `paused_at`.
- **7-day boundary:** `6d23h` stays parked; `7d1h` disarms.

## 6. Pinned workstreams (§8.6)

- Explicitly created by you via `chat.create`, named
  `factory/<project>/<item-id>`; one-shot: on terminal, the checkpoint
  becomes a `one_shot_complete` tombstone and the chat is left open (a later
  message there gets "that workstream is complete").
- Tick events for pinned workstreams are delivered to the **project chat**
  (the tick's only channel); the checkpoint carries `pending_relay`, an
  ordered list the tick appends to, and you drain it into the pinned chat on
  your next turn there. Relay is best-effort: if the user never opens the
  pinned chat, entries sit in the list (visible in the project chat as "also
  waiting in the pinned chat" on the next turn); nothing is ever silently
  dropped.
- `pending_relay` append points (tick, pinned only): terminal reconciliation,
  crash-loop escalation, orphan adoption, the stabilized "recovered after N
  restarts" note, and 7-day disarm. Each event is announced at most once per
  chat; a relay entry is consumed (marked relayed) **only by a turn in the
  pinned chat itself**.

### Notification routing table (§14.1)

| Event | Default workstream | Pinned workstream |
|---|---|---|
| Parked with questions / failed prompt | Project chat | Pinned chat |
| Done → chained (per-item note + next started) | Project chat | Pinned chat |
| Tick: terminal reconciled | Project chat via tick delivery; you relay to the pinned chat on your next turn there (`pending_relay`) | same |
| Tick: crash-loop escalation | Project chat: "The run for <item> has died 3 times in 30 minutes. I've parked it — here's the last error: <summary>. Say retry to try again." + relay | same |
| Tick: orphan adoption | Project chat: "Found the run for <item> alive but untracked — I've adopted it, no action needed." + relay | same |
| Tick: death relaunch (below intensity) | Silent; then "Recovered after N restarts." once it stabilizes | same |
| Tick: notification backfill | Project chat via tick delivery; you relay to the pinned chat on your next turn there (`pending_relay`) | same |
| Terminal handoff observed on main | **Applied silently — no message on main.** Notification routes to the workstream's chat | same |
| 7-day disarm | Project chat, verbatim + relay | same |

The tick's delivery reaches the project chat only; anything a pinned chat
must see is relayed by you. Your own notices go directly to the workstream's
own chat.

## 7. Misdirected replies (§8.7)

A reply in the main chat (or project chat) that belongs to a project
workstream: propose the routing and **ask for confirmation once**. On
confirmation, record it under the right item through the same serialized
`record-replies.sh` path (project mutex, message-id dedupe — no "single
writer" exemption), and file it as a `pending_intent` on that workstream's
checkpoint (for a pinned workstream, on the pinned checkpoint). Without
confirmation it stays only in chat history and you note **"I didn't file
that anywhere — say 'file it under X' and I will."** No silent filing, no
nagging.

A project-chat message that clearly answers a pinned workstream's questions
gets the same one-line confirm-and-copy treatment. A reply inside a pinned
chat needs no routing: that chat's own turn protocol files it under the
pinned item verbatim.

## 8. What to do on CAS abort, lock contention, and crashes (§12)

- **CAS abort (exit 3):** re-read the checkpoint. If it became a tombstone,
  follow the tombstone path (§2 step 6) — never retry the original
  transition. Otherwise re-evaluate your intent against fresh state and
  retry once; if it aborts again, tell the user what moved under you and
  stop (the next turn re-drains; nothing is lost).
- **Lock contention:** the mutex acquisition retries internally up to 10 s
  with stale-break at 30 s. Your turn retries the script call with backoff
  up to ~60 s; if still failing, do not advance the cursor — the
  un-advanced cursor is the redrive — and tell the user what blocked.
  Replies are never lost to contention.
- **Crash anywhere before step 5 completes:** the cursor is un-advanced and
  intents are durable, so the next turn re-drains and converges:
  message-id dedupe skips recorded replies; the ledger skips applied
  envelopes; idempotent applies make re-runs safe. Crash **after** step 5
  (cursor advanced, intents cleared) means the work was done — a redrive
  finds nothing to do.
- **Crash between ledger append and announcement** (e.g.
  `CRASH_AFTER_LEDGER_BEFORE_NOTIFY=1`): the notification record was already
  appended under the same mutex hold as the ledger, so the tick's backfill
  delivers it exactly once (delivery mark CAS). Re-running
  `apply-envelope.sh` reports `ALREADY_APPLIED` — never a duplicate apply.
- **Overlapping turns:** converge via CAS aborts and the ledger (see
  same-chat turn overlap in §2). Never hold the mutex across a tool call.
- **DB outage:** file-only mode — read and notify only, no checkpoint
  mutations, no disarms (§11.7). Staleness explained by a recorded
  outage window is exempt from death detection.

## 9. Launch sequence — the only one (§8.1, §8.3)

For initial launches, intent replays, tick relaunches, and chain steps:

```
prepare-launch.sh <project> <workstream> <item-id> --live-runs <file>   # mutex: arm or adopt
# — release the mutex here —
launch_async (your tool call — never inside a script, never under the mutex)
confirm-launch.sh <project> <workstream> <launched-run-id> [--chain-token <tok>]
```

- Zero live candidates → armed (`run_id=null`, `armed_at=now`).
- Exactly one → adopted (record `run_id` + `armed_at`).
- More than one → fail closed with a deduped notification; do not launch.
- Confirm-CAS: recorded == launched → CONFIRMED. A different recorded id →
  `workflow.stop` the just-launched run and adopt the recorded one (the
  stopped loser may have briefly touched the shared item branch — the winner
  treats branch state as-is; intake-resumes-branch covers it).

## 10. Quick checklist (every turn)

1. Does this turn's `chat_id` match a checkpoint `chats[]` or a tombstone
   `chat_id`? If no — the protocol does not run.
2. Handoff present? → `apply-envelope.sh` first (safe to run twice).
3. Tombstone match? → one_shot copy, or re-register fresh, or no-op.
4. Drain since cursor; classify reply / directive / misdirected.
5. Ambiguous approval reply? → one-line confirmation; **never resume**.
6. Record verbatim via `record-replies.sh` **before** any checkpoint write.
7. Only unresolvable/deferred items become `pending_intents`.
8. Complete intents in order (adopt-or-launch for launches) → advance cursor
   → clear intents, one CAS per transition.
9. Directive while `stopping`? → exact copy; `go`/`retry`/`start` become
   durable deferred intents.
10. Announce a terminal event only when your own `apply-envelope.sh` call
    returned applied; then mark the notification delivered.

## 11. Exact copy (verbatim strings — do not paraphrase)

- Repeat stop while stopping: **"Still stopping the run — one moment."**
- Deferred go/retry/start while stopping: **"Noted — I'll go as soon as the
  stop lands."**
- Ambiguous approval, second in a row: re-ask byte-identically +
  **"I still need a clear yes or no."**
- one_shot_complete tombstone: **"That pinned workstream is complete — say
  start <item> to run it again."**
- Mid-run reply ack: **"Noted — the run will see it at its next gate."**
- Stop on dead/missing run: **"That run already ended — nothing to stop."**
- Already paused: **"already paused."**
- No live run shortcut: **"Paused — nothing was running."**
- Unknown envelope: **"I couldn't understand the run's result — nothing was
  applied."**
- Main-chat workstream directive: **"That controls the <project> workstream
  — say it in the project chat."**
- Misdirected, no confirmation: **"I didn't file that anywhere — say 'file
  it under X' and I will."**
- Partial global-stop failure: **"Paused A and B; C's stop failed — it's
  still running."**
- Live run on retry: **"Already running — say stop first to restart it."**
- Unknown item: **"I don't see <id> in the backlog."**
- Empty backlog start: **"The backlog is empty — add items first."**

---

*Probe: `scripts/conformance-probe.py` drives this protocol against a scratch
project and reports PASS/FAIL per case (T5). The conformance probe is not a
substitute for the mandatory fresh-context final code review.*
