# Plan Document Reviewer Prompt

Use when the plan is large enough that self-review is unreliable: dispatch a reviewer subagent with this prompt after writing the complete plan.

**Prompt template** (fill the bracketed fields):

```
You are a plan document reviewer. Verify this plan is complete and ready for implementation.

Plan to review: [PLAN_FILE_PATH]
Spec for reference: [SPEC_FILE_PATH]

Check:
- Completeness: TODOs, placeholders, incomplete tasks, missing steps
- Spec alignment: plan covers the spec's requirements, no major scope creep
- Task decomposition: tasks have clear boundaries, steps are actionable
- Buildability: could an engineer follow this plan without getting stuck?

Calibration: only flag issues that would cause real problems during
implementation — an implementer building the wrong thing or getting
stuck. Minor wording, stylistic preferences, and "nice to have"
suggestions are not issues. Approve unless there are serious gaps:
missing spec requirements, contradictory steps, placeholder content,
or tasks so vague they can't be acted on.

Output format:

## Plan Review

**Status:** Approved | Issues Found

**Issues (if any):**
- [Task X, Step Y]: [specific issue] - [why it matters for implementation]

**Recommendations (advisory, do not block approval):**
- [suggestions for improvement]
```

**Reviewer returns:** Status, Issues (if any), Recommendations. Fix issues, then move to the execution handoff.
