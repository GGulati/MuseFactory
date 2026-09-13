# MuseFactory

A personal software factory: a backlog markdown doc goes in, reviewed and verified code comes out.

**How it works**

1. The user keeps a plain markdown backlog — top-level bullets are items, sub-bullets are detail, order is priority. It lives in their Library app as an editable doc and is the source of truth.
2. The `dev-factory` saved workflow reads it live, triages items by maturity (sketch → full loop, spec → straight to planning), and runs each through the `develop` skill: brainstorm → plan → dual plan review (product + technical) → isolated worktree → TDD implementation → debugging → code review → verification → PR prep.
3. Approvals and questions surface as one grouped report; the user answers, the factory resumes.

**What's in this repo**

- `skills/` — 12 engineering skills. Eleven are adapted from [obra/superpowers](https://github.com/obra/superpowers) (MIT); `develop` composes them into the end-to-end loop.
- `workflows/dev-factory.js` — the saved-workflow script (deterministic orchestration).
- `AGENTS.md` — setup-from-scratch guide for a Muse agent, plus the operating contract.

**Setup**

If you're a Muse agent, follow `AGENTS.md`. If you're a human: clone, copy `skills/` into `~/workspace/skills/`, register `workflows/dev-factory.js` as a saved workflow named `dev-factory`, then point it at a backlog doc and a repo.

## License

MIT — see `LICENSE`. The adapted skills retain their attribution to obra/superpowers (MIT © 2025 Jesse Vincent).
