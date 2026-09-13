# Brief template and examples (dispatching-parallel-agents)

## Brief template

Every child brief follows this shape. A child that inherits your context is a child that surprises you.

```
TASK (one clear problem domain):
<what to do, scoped to one subsystem / file / test>

CONTEXT (paste everything it needs):
- File paths: <exact paths>
- Failing output / spec: <copy the relevant error text verbatim>

CONSTRAINTS:
- Do not edit files outside <scope>
- Do not push to GitHub, open PRs, merge, or delete branches
- <any domain constraints, e.g. "tests only, no production code">

RETURN (exactly this):
- Root cause
- What you changed (file + what)
- Test outcome after your change
```

## Good vs bad briefs

**Bad (too broad):** "Fix all the failing tests." — the child has no scope and will wander.

**Good (focused):**
```
TASK: Fix the 2 failing tests in src/billing/invoice.test.ts.

CONTEXT:
- src/billing/invoice.test.ts, src/billing/invoice.ts
- Failures:
  1. "applies early-payment discount" — expected 95, got 100
  2. "rejects negative line items" — no error thrown

CONSTRAINTS:
- Do not edit files outside src/billing/
- Do not push to GitHub or open PRs

RETURN:
- Root cause of each failure
- What you changed (file + line range)
- Test command output after the change
```

**Bad (no context):** "Fix the race condition." — the child doesn't know where.

**Good (self-contained):** paste the failing test names, the error messages, and the files involved, as above.

## Chaining dependent work

When task B needs task A's output, run them sequentially and carry the result forward:

```
Agent 1: "Investigate why auth tests fail. RETURN: root cause and failing lines."
  -> Agent 2 (after Agent 1 returns): "Fix auth/tests/login.test.ts.
       ROOT CAUSE FROM AGENT 1: <paste>. CONSTRAINTS: ..."
```

In a JS workflow: `pipeline([() => agent(briefA), (resA) => agent(briefB(resA))])`.
For independent sets: `parallel([() => agent(brief1), () => agent(brief2), () => agent(brief3)])`.

## Review checklist (per child)

1. Summary understood — can you state the root cause in one sentence?
2. Scope respected — did it stay inside its files?
3. No conflicts — did two children edit the same code?
4. Tests — run the full suite yourself after integrating.
5. Spot-check — read the actual diff; children can make systematic errors.
