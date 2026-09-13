# Response Examples

## Performative agreement (bad) vs. technical verification (good)

```
Reviewer: "Remove legacy code"
BAD:  "You're absolutely right! Let me remove that..."
GOOD: "Checking... build target is 10.15+, this API needs 13+. Need the legacy
      path for backward compat. The current impl has the wrong bundle ID though —
      fix it, or drop pre-13 support?"
```

## YAGNI check

```
Reviewer: "Implement proper metrics tracking with database, date filters, CSV export"
GOOD: "Grepped the codebase — nothing calls this endpoint. Remove it (YAGNI)?
      Or is there usage I'm missing?"
```

## Unclear items

```
User: "Fix items 1-6"
You understand 1,2,3,6. Unclear on 4,5.
GOOD: "Understand 1,2,3,6. Need clarification on 4 and 5 before implementing."
BAD:  implement 1,2,3,6 now and ask about 4,5 later.
```

## Acknowledging correct feedback

```
GOOD: "Fixed. Moved the validation into create_project() (proj.py:41)."
GOOD: "Good catch — off-by-one in the retry loop. Fixed in retry.py:18."
GOOD: [just fix it and show in the code]

BAD:  "You're absolutely right!" / "Great point!" / "Thanks for catching that!"
      (any gratitude expression — delete it and state the fix instead)
```

## Gracefully correcting your own pushback

```
GOOD: "You were right — I checked the caller and it does pass an empty string.
      My initial understanding was wrong because I only read the callee.
      Implementing now."
BAD:  long apology, defending why you pushed back, over-explaining.
```
