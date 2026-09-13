export const meta = {
  name: "dev-factory",
  description: "Backlog factory: reads a project backlog markdown doc (source of truth), reconciles already-merged work, triages items by maturity, runs each through the develop skill loop with configurable concurrency, and reports. Approvals and questions surface as blocked results for the project side chat.",
  phases: ["intake", "triage", "develop", "report"]
};

const inputs = args ?? {};
const project = inputs.project;
const backlogPath = inputs.backlog_path;
const repoPath = inputs.repo_path;
const concurrency = inputs.concurrency ?? 1;
const mode = inputs.mode ?? "interactive";

if (!project || !backlogPath || !repoPath) {
  throw new Error("dev-factory requires args: project, backlog_path, repo_path (optional: concurrency, mode)");
}

const itemSchema = {
  type: "object",
  required: ["status", "title", "summary"],
  properties: {
    status: { type: "string" },
    title: { type: "string" },
    summary: { type: "string" },
    branch: { type: "string" },
    questions: { type: "array", items: { type: "string" } }
  }
};

phase("intake");
log("dev-factory intake for project: " + project);
const intake = agent(
  "You are intake for the dev-factory workflow.\n" +
  "Project: " + project + "\n" +
  "Backlog doc (source of truth — read it with the file tools): " + backlogPath + "\n" +
  "Repo checkout: " + repoPath + "\n\n" +
  "Tasks:\n" +
  "1. Read the backlog markdown doc. Parse top-level bullets as backlog items, in order. For each: id = slug of the title (lowercase, runs of non-alphanumeric become single hyphens, max 40 chars; append -2, -3 on duplicates), title = first-line text, detail = sub-bullet text joined by newlines (may be empty string).\n" +
  "2. Reconcile: run `git -C " + repoPath + " branch --list 'factory/*'` and `git -C " + repoPath + " branch --merged main --list 'factory/*'`. Match branches to items by id (branch factory/<id>).\n" +
  "3. For any backlog item whose branch is merged into main: remove exactly that item's lines from the backlog doc (targeted edit, touch nothing else) and list it under reconciled.\n" +
  "4. Return a JSON object: { items: [{id, title, detail, repoStatus}], reconciled: [{id, title}] }. repoStatus is \"new\" (no factory branch) or \"active\" (unmerged factory/<id> branch exists).\n" +
  "Do not start any development work.",
  {
    key: "intake", label: "Read backlog and reconcile", phase: "intake", timeoutMs: 300000,
    schema: {
      type: "object",
      required: ["items"],
      properties: {
        items: { type: "array", items: { type: "object", required: ["id", "title"], properties: {
          id: { type: "string" }, title: { type: "string" },
          detail: { type: "string" }, repoStatus: { type: "string" } } } },
        reconciled: { type: "array", items: { type: "object", properties: {
          id: { type: "string" }, title: { type: "string" } } } }
      }
    }
  }
);

const items = intake.items || [];
const reconciled = intake.reconciled || [];
for (const r of reconciled) { log("Reconciled (already merged, removed from backlog): " + r.title); }

phase("triage");
const triage = agent(
  "You are triage for the dev-factory workflow. Project: " + project + ".\n" +
  "Items (JSON): " + JSON.stringify(items) + "\n\n" +
  "For each item with repoStatus \"new\", classify maturity:\n" +
  "- \"sketch\": one-liner or vague; needs the full develop loop. entryPhase = 1.\n" +
  "- \"spec\": detailed sub-bullets; entryPhase = 2 (plan), or 3 (plan review) if the detail is already plan-like.\n" +
  "For repoStatus \"active\": resume = true, entryPhase = 1 (the worker inspects the branch and continues from the right phase).\n" +
  "Park any item too vague to act on, with a one-line question for the user.\n" +
  "Return JSON: { queue: [{id, title, detail, maturity, entryPhase, resume}], parked: [{id, title, question}] }.",
  {
    key: "triage", label: "Classify backlog maturity", phase: "triage", timeoutMs: 300000,
    schema: {
      type: "object",
      required: ["queue"],
      properties: {
        queue: { type: "array", items: { type: "object", required: ["id", "title", "entryPhase"], properties: {
          id: { type: "string" }, title: { type: "string" }, detail: { type: "string" },
          maturity: { type: "string" }, entryPhase: { type: "number" }, resume: { type: "boolean" } } } },
        parked: { type: "array", items: { type: "object", properties: {
          id: { type: "string" }, title: { type: "string" }, question: { type: "string" } } } }
      }
    }
  }
);

const queue = triage.queue || [];
const parked = triage.parked || [];
for (const p of parked) { log("Parked (needs user input): " + p.title + " — " + p.question); }

phase("develop");

function developItem(item) {
  const resumeNote = item.resume
    ? "A branch factory/" + item.id + " already exists. Inspect it and its worktree first, then continue the develop loop from the appropriate phase — do not start over."
    : "No branch exists yet for this item.";
  const dev = agent(
    "You are a factory worker. Read and follow the develop skill at ~/workspace/skills/develop/SKILL.md exactly.\n" +
    "Project: " + project + ". Repo: " + repoPath + ". Mode: " + mode + ".\n" +
    "Backlog item: \"" + item.title + "\". Detail:\n" + (item.detail || "(none)") + "\n" +
    "Maturity: " + (item.maturity || "sketch") + ". Enter the develop loop at Phase " + item.entryPhase + ". " + resumeNote + "\n" +
    "Isolation: follow the using-git-worktrees skill; branch name factory/" + item.id + ".\n" +
    "Gates: at every develop-skill approval gate (end of Phase 1 design, end of Phase 3 plan, Phase 8 push/PR) and on any ambiguity you cannot resolve from the repo, STOP and return a blocked envelope — do not wait, do not ask the user yourself.\n" +
    "Never push, merge, or delete branches. Never edit the backlog doc.\n" +
    "Go as far as you can without user input (through Phase 7 code review and Phase 8 verification + progress log). If the only thing left is PR/push approval, return status \"awaiting-approval\".\n" +
    "Return a JSON object: { status, title, summary, branch, questions }. status is one of: done (fully complete and merged — rare), awaiting-approval (work complete, needs PR/merge approval), blocked (needs input mid-loop), failed (retries exhausted or non-retryable). questions is an array of strings (empty unless blocked or awaiting-approval).",
    { key: "develop-" + item.id, label: "Develop: " + item.title, phase: "develop", timeoutMs: 1800000, schema: itemSchema }
  );
  if (!dev) { log("Worker returned nothing: " + item.title); return null; }
  if (dev.status === "failed") { log("Item failed: " + item.title + " — " + dev.summary); return dev; }
  const rec = agent(
    "Append one progress-log entry for this factory item.\n" +
    "Project: " + project + ". Repo: " + repoPath + ".\n" +
    "Item: \"" + item.title + "\" (branch " + (dev.branch || "factory/" + item.id) + "). Outcome: " + dev.status + ". Summary: " + dev.summary + "\n" +
    "Write to " + repoPath + "/progress.md if that file exists, otherwise to ~/workspace/dev-factory/projects/" + project + "/progress.md. Append a dated entry: what was done, key decisions, and a Verification line (tests/build/browser checks). Create the file and directories if needed.\n" +
    "Return JSON, passing the worker's values through unchanged: { status, title, summary, branch, questions }.",
    { key: "record-" + item.id, label: "Record: " + item.title, phase: "develop", timeoutMs: 300000, schema: itemSchema }
  );
  return rec || dev;
}

let results;
if (concurrency <= 1) {
  results = [];
  for (let i = 0; i < queue.length; i++) { results.push(developItem(queue[i])); }
} else {
  const thunks = [];
  for (let i = 0; i < queue.length; i++) {
    const item = queue[i];
    thunks.push(() => developItem(item));
  }
  results = parallel(thunks, { concurrency: concurrency });
}

phase("report");
const done = [], awaiting = [], blocked = [], failed = [];
for (const r of (results || [])) {
  if (!r) { continue; }
  if (r.status === "done") { done.push(r); }
  else if (r.status === "awaiting-approval") { awaiting.push(r); }
  else if (r.status === "blocked") { blocked.push(r); }
  else { failed.push(r); }
}

let message = "dev-factory run for " + project + ": " + queue.length + " item(s) processed — " +
  done.length + " done, " + awaiting.length + " awaiting approval, " +
  blocked.length + " blocked, " + failed.length + " failed.";
if (reconciled.length > 0) { message += " Reconciled " + reconciled.length + " already-merged item(s) off the backlog."; }
if (parked.length > 0) {
  message += " Parked " + parked.length + " item(s) needing input:";
  for (const p of parked) { message += " [" + p.title + ": " + p.question + "]"; }
}

const needsInput = blocked.concat(awaiting);
if (needsInput.length > 0) {
  let detail = "";
  for (const r of needsInput) {
    detail += "\n\n## " + r.title + " (" + r.status + ", branch " + (r.branch || "n/a") + ")\n" + r.summary;
    for (const q of (r.questions || [])) { detail += "\n- " + q; }
  }
  return {
    __hatchWorkflowControl: "blocked",
    result: {
      blocked_reason: needsInput.length + " item(s) need input before the factory can continue",
      message: message + detail
    }
  };
}

return message + (failed.length > 0 ? " Failures logged above need attention." : " All clear.");