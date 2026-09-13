# Defense-in-Depth Validation

**Core principle:** when a bug is caused by invalid data, validate at EVERY layer the data passes through. Make the bug structurally impossible, not merely fixed once. A single check can be bypassed by other code paths, refactoring, or mocks.

Different layers catch different cases:

| Layer | Purpose | Example |
|---|---|---|
| 1. Entry-point validation | Reject obviously invalid input at the API boundary | `if not working_dir or not os.path.isdir(working_dir): raise ValueError(...)` |
| 2. Business-logic validation | Ensure the data makes sense for this operation | `if not project_dir: raise ValueError("project_dir required for workspace init")` |
| 3. Environment guards | Prevent dangerous operations in specific contexts | In tests, refuse `git init` outside the temp dir |
| 4. Debug instrumentation | Capture context for forensics when other layers fail | Log directory, cwd, and a captured stack before the operation |

## Applying the pattern

1. **Trace the data flow** — where does the bad value originate? Where is it used?
2. **Map all checkpoints** — list every point the data passes through.
3. **Add validation at each layer** — entry, business logic, environment, debug.
4. **Test each layer** — try to bypass layer 1 and verify layer 2 catches it.

## Worked example

Bug: an empty `projectDir` caused `git init` to run in the source tree.

Data flow: test setup → empty string → `Project.create(name, '')` → `WorkspaceManager.createWorkspace('')` → `git init` runs with `cwd=''` → resolves to `process.cwd()`.

Layers added:

- Layer 1: `Project.create()` validates the directory is non-empty, exists, and is writable.
- Layer 2: `WorkspaceManager` validates `projectDir` is non-empty.
- Layer 3: refuses `git init` outside the temp directory during tests.
- Layer 4: logs the directory, cwd, and stack trace before `git init`.

Result: the bug became impossible to reproduce; when new code paths bypassed one layer, another caught them during testing.

## Key insight

Do not stop at one validation point. During real debugging sessions, each layer has caught bugs the others missed: different code paths bypass entry validation, mocks bypass business-logic checks, edge cases on different platforms need environment guards, and debug logging identifies structural misuse.
