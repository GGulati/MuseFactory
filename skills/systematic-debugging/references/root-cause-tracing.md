# Root-Cause Tracing

**Core principle:** trace backward through the call chain until you find the original trigger, then fix at the source. Fixing where the error appears treats a symptom.

## When to use

- Error happens deep in execution (not at the entry point).
- Stack trace shows a long call chain.
- Unclear where invalid data originated.
- Need to find which test or call site triggers the problem.

## The tracing process

1. **Observe the symptom.** e.g. `git init` failed, running in the wrong directory.
2. **Find the immediate cause.** What code directly causes it? e.g. `execFile('git', ['init'], { cwd: projectDir })`.
3. **Ask: what called this?** Walk up the call chain. e.g. `WorktreeManager.createSessionWorktree(projectDir)` → called by `Session.initializeWorkspace()` → called by `Session.create()` → called by the test.
4. **Keep tracing up.** What value was passed? e.g. `projectDir = ''` (empty string); an empty `cwd` resolves to `process.cwd()` — the source tree.
5. **Find the original trigger.** Where did the empty string come from? e.g. the test accessed `context.tempDir` before `beforeEach` ran, so it was still `''`.
6. **Fix at the source.** e.g. make `tempDir` a getter that throws when accessed before setup.
7. **Add defense-in-depth** ([defense-in-depth.md](defense-in-depth.md)) so the bug becomes structurally impossible: validation at each layer the data passes through.

## Instrumenting when you cannot trace manually

Log **before** the dangerous operation, not after it fails. Include the full context and a captured stack:

```python
import traceback
print(f"DEBUG git init: directory={directory} cwd={os.getcwd()} "
      f"stack={traceback.format_stack()}", file=sys.stderr)
```

Run once, then grep the output for your marker. Analyze the stack traces: look for test file names, the triggering line number, and repeating patterns (same test? same parameter?). In tests, print to stderr — a logging framework may be suppressed.

## Finding which test pollutes shared state

If something bad appears during a test run and you do not know which test causes it: bisect. Run test files one at a time (or halves of the suite) until the first file/test that triggers the pollution is isolated, then trace from there.
