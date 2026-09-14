# MuseFactory

A personal software factory: a backlog markdown doc goes in, reviewed and verified code comes out — built on the [Erlang/OTP design principles](https://www.erlang.org/doc/design_principles/des_princ.html): files are message queues, workers are workers, and everything is designed to crash and recover.

**How it works**

1. The user keeps a plain markdown backlog — top-level bullets are items, sub-bullets are detail, order is priority. The backlog is the message queue; nothing reads it "live" or triages the whole thing anymore.
2. One `dev-factory` workflow run processes **exactly one** backlog item, then terminates with a typed terminal envelope (`done`, `awaiting-approval`, `blocked`, or `failed`). The run works the item through the `develop` skill: orient → plan → dual plan review (product + technical) → isolated worktree → TDD implementation → debugging → code review → verification → report.
3. The **supervisor** (an LLM, following `SUPERVISOR.md`) applies the envelope to the backlog and checkpoint state via deterministic scripts, and asks any unanswered questions again — byte-identically — in the project side chat. A reply in that chat is the real-time event; resume happens inline in that chat turn.
4. A per-project **liveness tick** (2-minute cron, delivered to the project side chat) exists for exactly one reason: silent worker death has no event. The tick detects dead runs, crash loops, and week-long stalls — nothing else.

**Design principles**

- **Files are message queues, workers are workers** (Erlang/OTP). Checkpoints and backlogs are state, not orchestration; the workflow does no supervision and the supervisor does no work.
- **One run = one item.** No queue loops, no self-relaunch, no backlog edits by workers.
- **Nothing is implicitly approved.** An ambiguous reply to an approval gate gets a one-line confirmation question, never a resume.
- **Crash-only design.** Every race-sensitive protocol is a deterministic script, not LLM prose. A crash at any point converges on re-run: mutations are idempotent, envelopes are applied exactly once via a `handled_run_ids` ledger, and all shared-state changes go through a single project-wide mutex with compare-and-swap preconditions.
- **The supervisor supervises; scripts serialize.** The LLM never edits state directly — every mutation is a script invocation held for milliseconds.
- **Reviews are always fresh-context.** Workers never review in-session; a `needs-review` blocked envelope routes to a fresh reviewer subagent.

**What's in this repo**

- `workflows/dev-factory.js` — the saved-workflow script: pure task worker, one item to a terminal envelope. Phases: `orient, implement, verify, report`. It never launches subagents-of-subagents, never pushes/merges/deletes branches, never edits the backlog.
- `scripts/` — the serialized mutation layer: `mutex.sh` (project-wide lock), `checkpoint.sh` (workstream state machine), `apply-envelope.sh` (terminal-envelope reconciliation), `backlog.sh`, `notify.sh` (crash-safe notification queue), `tick.sh` (liveness sweep), and the launch protocol (`prepare-launch.sh` → launch → `confirm-launch.sh`, `adopt-or-relaunch.sh`). Shared logic lives in `scripts/lib/`, sourced, never re-acquired.
- `SUPERVISOR.md` — the supervisor runbook: the turn protocol, directive table, exact ack copy, and crash/lock/CAS recovery. Everything an LLM supervisor needs, distilled from the design.
- `skills/develop/` — the end-to-end `develop` skill the worker composes.
- `AGENTS.md` — setup-from-scratch guide for a Muse agent, plus the operating contract.

**Dependencies** (installed during setup, not vendored): the [obra/superpowers](https://github.com/obra/superpowers) skills (MIT), which `develop` composes.

**Setup**

If you're a Muse agent, follow `AGENTS.md`. If you're a human: clone, install the superpowers skills, copy `skills/develop` into `~/workspace/skills/`, register `workflows/dev-factory.js` as a saved workflow named `dev-factory`, register a project with `scripts/register-project.sh`, and create its 2-minute tick cron with delivery to the project side chat.

## License

MIT — see `LICENSE`.
