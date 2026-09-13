# Spec Document Reviewer Prompt

Use when the written spec is too large for a reliable self-review (SKILL.md step 7): dispatch a reviewer subagent with this prompt before asking the user to review the spec.

**Dispatch after:** the spec file is written.

**Prompt template** (fill the bracketed fields):

```
You are a spec document reviewer. Verify this spec is complete, consistent, and ready for implementation planning.

Spec to review: [SPEC_FILE_PATH]

Check:
- Completeness: TODOs, placeholders, "TBD", incomplete sections
- Consistency: internal contradictions, conflicting requirements
- Clarity: requirements so ambiguous someone could build the wrong thing
- Scope: focused enough for a single implementation plan (not multiple independent subsystems)
- YAGNI: unrequested features, over-engineering

Calibration: only flag issues that would cause real problems during
implementation planning — a missing section, a contradiction, or a
requirement interpretable two ways. Minor wording improvements,
stylistic preferences, and "sections less detailed than others" are
not issues. Approve unless there are serious gaps that would lead to
a flawed plan.

Output format:

## Spec Review

**Status:** Approved | Issues Found

**Issues (if any):**
- [Section X]: [specific issue] - [why it matters for planning]

**Recommendations (advisory, do not block approval):**
- [suggestions for improvement]
```

**Reviewer returns:** Status, Issues (if any), Recommendations. Fix issues found, then re-run your inline self-review — no need to re-dispatch.
