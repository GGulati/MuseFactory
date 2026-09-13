# Condition-Based Waiting

**Core principle:** wait for the actual condition you care about, not a guess about how long it takes. Arbitrary sleeps create flaky tests that pass on fast machines and fail under load or in CI.

## When to use

- Tests use arbitrary delays (`time.sleep`, `setTimeout`).
- Tests are flaky (pass sometimes, fail under load or in parallel).
- Waiting for async operations to complete.

Do not use it when testing actual timing behavior (debounce, throttle intervals). If you do use an arbitrary timeout there, document exactly WHY.

## The pattern

```python
# BAD: guessing at timing
time.sleep(0.05)
result = get_result()
assert result is not None

# GOOD: waiting for the condition
deadline = time.time() + 5.0
while get_result() is None:
    if time.time() > deadline:
        raise TimeoutError("Timed out waiting for result after 5s")
    time.sleep(0.01)
result = get_result()
assert result is not None
```

Useful reusable shape:

```python
def wait_for(condition, description, timeout_s=5.0, poll_s=0.01):
    deadline = time.time() + timeout_s
    while True:
        result = condition()
        if result:
            return result
        if time.time() > deadline:
            raise TimeoutError(f"Timed out waiting for {description} after {timeout_s}s")
        time.sleep(poll_s)
```

| Scenario | Condition |
|---|---|
| Wait for event | `wait_for(lambda: find_event(events, "DONE"))` |
| Wait for state | `wait_for(lambda: machine.state == "ready")` |
| Wait for count | `wait_for(lambda: len(items) >= 5)` |
| Wait for file | `wait_for(lambda: os.path.exists(path))` |

## Common mistakes

- **Polling too fast** (`sleep(0.001)`) wastes CPU — poll around every 10ms.
- **No timeout** loops forever if the condition never holds — always include a timeout with a clear error message.
- **Stale data** — call the getter inside the loop for fresh state; do not cache it before the loop.

## When an arbitrary timeout is correct

1. First wait for the triggering condition with `wait_for`.
2. Then sleep, based on known timing (not a guess) — e.g. a tool ticks every 100ms, so 200ms covers 2 ticks.
3. Comment explaining WHY: the known interval and what it covers.
