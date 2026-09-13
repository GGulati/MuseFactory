# Test Quality Rules (compressed from writing-good-tests.md)

Two principles govern everything: **every test names the break it catches**, and **every test exercises the real thing**.

## Gate: name the break before writing the test body

Ask: what production change should make this test fail — and is that change a bug or a decision?

- Cannot name one → redesign around an observable behavior.
- "The source text changed" → run the artifact and assert its effects instead of grepping text.
- Only intentional decisions could fail it (constant's value, exact message wording, private structure) → it is a change detector; test the behavior that depends on the decision instead.

Derive expectations independently. Use literals and hand-checked fixtures; table-driven tests with literal `want` values are the preferred shape. An expectation computed by the code under test passes no matter what that code does:

```python
# BAD: mirror assertion — the same builder computes both sides, always true
expected = build_search_query(tag="urgent")
assert build_search_query(tag="urgent") == expected

# GOOD: hand-derived literal
assert build_search_query(tag="urgent") == 'tag:"urgent"'
```

## Gate: before adding a mock or test-only helper

- List the real method's side effects. Keep the ones the test depends on real; mock only the slow or external level below them.
- Mock responses mirror the complete real structure (all documented fields, not just the ones your test reads) — partial mocks fail silently when downstream code reads an omitted field.
- Cleanup that only tests need lives in test utilities, never as a production method. Ask: is this method called only from tests? Does this class own this resource's lifecycle?
- About to assert on the mock itself? Unmock it or delete the assertion — a mock assertion passes when the mock is present and fails when it is absent, saying nothing about the component.

## Quick rules

| When you... | Do |
|---|---|
| Build an expected value | Derive it by hand; never with the code under test |
| Test a script or config | Run it against controlled inputs; assert outputs, side effects, exit codes — never grep its text |
| Reach for a dependency test | Test your boundary contract (route, query, payload) — not the framework's documented mechanics |
| Mock setup outgrows the test logic | Switch to an integration test with real components |
| Need cleanup only tests use | Put it in test utilities |

## The mutation check

Before finishing, mentally mutate the production code; at least one test should fail for each realistic mutation:

- Wrong constant or argument
- Wrong branch handler
- Missing state change or side effect
- Empty or default return
- Missing validation for zero, empty, nil, unauthorized, or malformed input

A mutation nothing catches marks the behavior as unprotected — or the test as tautological.

## Warning signs

- Setup and assertion share the same object, guaranteeing equality.
- The test fails on every intentional change, never on accidental breakage.
- Expected values hidden behind loops, builders, or helpers.
- An assertion checks a `*-mock` test ID, or fails if you remove the mock.
- Mock setup is more than half the test, or you cannot explain why the mock is needed.
- Mocking "just to be safe."
