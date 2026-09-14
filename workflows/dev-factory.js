export const meta = {
  name: "dev-factory",
  description: "Single-item factory worker: implement one backlog item to a terminal envelope.",
  phases: ["orient", "implement", "verify", "report"]
};

// ---------------------------------------------------------------------------
// Contract (plan §7.1):
//  - Fail fast (M17): args.project / args.item_id must match
//    ^[a-z0-9][a-z0-9-]*$ (path-traversal allowlist); paths must be absolute.
//  - One item, then out. This script never loops over a backlog, never
//    chains, never relaunches itself.
//  - Gates read replies: before each approval-gated step the run re-reads
//    <user-replies-dir>/<item-id>.md (workspace path, never the branch).
//  - Terminal envelope only: the top-level return is exactly the envelope
//    (plan §5.3). Mid-run stalls the supervisor must see use the blocked
//    control return.
//  - No side effects outside the item branch. No pushes, merges, branch
//    deletions, backlog edits. Ever.
// Lessons carried from the retired whole-queue workflow (T0 diff):
//  - agent() returns a Promise in the workflow runtime — ALWAYS await it.
//    A non-awaited result silently yields undefined fields.
//  - Child-agent payloads use the field name "outcome", never "status": a
//    top-level "status" key makes the runtime treat the child's JSON as a
//    status envelope instead of handing us the payload. The workflow's own
//    top-level return is the terminal envelope, which legitimately carries
//    "status" (verified: it lands in final_result, plan §5.3/C3).
// ---------------------------------------------------------------------------

const inputs = args ?? {};
const project = inputs.project;
const itemId = inputs.item_id;
const backlogPath = inputs.backlog_path;
const repoPath = inputs.repo_path;
const worktreePath = inputs.worktree_path;
const baseBranch = inputs.base_branch || "main";
const repliesDir =
  inputs.user_replies_dir ||
  "/home/hatch/workspace/dev-factory/projects/" + project + "/user-replies";
const repliesFile = repliesDir + "/" + itemId + ".md";
const branchName = "factory/" + itemId;

// --- M17 fail-fast arg validation (first statements) ---
const SLUG_RE = /^[a-z0-9][a-z0-9-]*$/;
if (typeof project !== "string" || !SLUG_RE.test(project)) {
  throw new Error("dev-factory: args.project must match ^[a-z0-9][a-z0-9-]*$ (got " + JSON.stringify(project) + ")");
}
if (typeof itemId !== "string" || !SLUG_RE.test(itemId)) {
  throw new Error("dev-factory: args.item_id must match ^[a-z0-9][a-z0-9-]*$ (got " + JSON.stringify(itemId) + ")");
}
for (const entry of [["backlog_path", backlogPath], ["repo_path", repoPath], ["worktree_path", worktreePath]]) {
  const key = entry[0];
  const value = entry[1];
  if (typeof value !== "string" || !value.startsWith("/") || value.includes("..")) {
    throw new Error("dev-factory: args." + key + " must be an absolute path without '..' (got " + JSON.stringify(value) + ")");
  }
}

// --- envelope helpers ---
function envelope(status, fields) {
  const f = fields || {};
  const env = {
    status: status,
    item_id: itemId,
    questions: f.questions || [],
    reconciliations: f.reconciliations || {},
    failure_summary: f.failure_summary || "",
    branch: f.branch || branchName,
    commit: f.commit || null
  };
  // needs-review passthrough (M4): a blocked review-gate return carries
  // blocked_details so apply-envelope.sh can park with needs_review and the
  // supervisor can run the fresh-context reviewer protocol.
  if (f.blocked_details) {
    env.blocked_details = f.blocked_details;
  }
  return env;
}

// Mid-run stall the supervisor must see: blocked control return, not a
// throw, so the typed payload survives in final_result.
function stalled(reason) {
  log("dev-factory stalled: " + reason);
  return {
    __hatchWorkflowControl: "blocked",
    result: envelope("blocked", { failure_summary: "stalled: " + reason })
  };
}

function preview(value) {
  try {
    return JSON.stringify(value).slice(0, 400);
  } catch (e) {
    return String(value).slice(0, 400);
  }
}

// ---------------------------------------------------------------------------
// orient: read the backlog item, repo/branch context, and any user replies.
// ---------------------------------------------------------------------------
phase("orient");
log("dev-factory orient: project=" + project + " item=" + itemId);

const orient = await agent(
  "You are orient for the dev-factory single-item worker.\n" +
  "Project: " + project + ". Item id: " + itemId + ".\n" +
  "Backlog doc (source of truth — read it with the file tools): " + backlogPath + "\n" +
  "Worktree checkout: " + worktreePath + " (base branch: " + baseBranch + ").\n" +
  "User replies file (may not exist — that is normal): " + repliesFile + "\n\n" +
  "Tasks (read-only — change nothing):\n" +
  "1. Read the backlog doc. Top-level bullets are items in priority order; sub-bullets are detail. " +
  "Item id = slug of the title (lowercase, runs of non-alphanumeric become single hyphens, max 40 chars).\n" +
  "2. Find the item whose id equals \"" + itemId + "\". If no bullet matches, return { \"outcome\": \"not-found\" }.\n" +
  "3. In the worktree, run: `git status --short --branch`, `git log --oneline -8`, " +
  "`git branch --list '" + branchName + "'`, `git rev-parse " + baseBranch + "`.\n" +
  "4. Read the user replies file verbatim if it exists; otherwise use an empty string. " +
  "Never invent replies — report exactly what the file contains.\n\n" +
  "Return ONLY this JSON object (no wrapping envelope, no field named \"status\"):\n" +
  "{ \"outcome\": \"ready\", \"item\": { \"id\": \"" + itemId + "\", \"title\": \"...\", \"detail\": \"...\" }, " +
  "\"branch_exists\": true/false, \"base_commit\": \"...\", \"recent_commits\": [\"...\"], \"replies\": \"...\" }",
  { key: "orient-" + itemId, label: "Orient: " + itemId, phase: "orient", timeoutMs: 600000 }
);

if (!orient || orient.outcome !== "ready") {
  if (orient && orient.outcome === "not-found") {
    log("dev-factory: item not found in backlog: " + itemId);
    phase("report");
    return envelope("failed", {
      failure_summary: "item \"" + itemId + "\" not found in backlog doc " + backlogPath
    });
  }
  return stalled("orient child returned no usable payload: " + preview(orient));
}

const item = orient.item;
log("dev-factory: working item \"" + item.title + "\" (branch exists: " + orient.branch_exists + ")");

// ---------------------------------------------------------------------------
// implement: one child worker runs the develop loop on the item branch.
// Approval gates and question gates terminate the run — the supervisor
// relaunches a fresh run on resume, which re-reads the replies.
// ---------------------------------------------------------------------------
phase("implement");

const implement = await agent(
  "You are a factory worker. Read and follow the develop skill at ~/workspace/skills/develop/SKILL.md exactly.\n" +
  "Project: " + project + ". Repo worktree: " + worktreePath + ". Base branch: " + baseBranch + ".\n" +
  "Backlog item: \"" + item.title + "\" (id: " + itemId + "). Detail:\n" + (item.detail || "(none)") + "\n" +
  "User replies to this item (verbatim, may be empty — they answer earlier questions):\n" + (orient.replies || "(none)") + "\n\n" +
  "Isolation: work ONLY on branch \"" + branchName + "\" in the worktree. " +
  (orient.branch_exists
    ? "The branch already exists (crash recovery or resume): inspect it and `git log --oneline` FIRST, then continue the develop loop from the appropriate phase — do not start over, do not duplicate commits already on the branch."
    : "No branch exists yet: create \"" + branchName + "\" from " + baseBranch + ".") + "\n" +
  "Commit per completed phase with deterministic messages like \"factory(" + itemId + "): <phase> — <short description>\". " +
  "Crash-window rule: only your commits and the final envelope survive a crash, so before committing check `git log` " +
  "and never create a duplicate commit for work already committed.\n\n" +
  "Reply gates (read " + repliesFile + " fresh before EACH gate and before your final return — it may have changed):\n" +
  "- If the file contains answers to your outstanding questions, incorporate them and CONTINUE. " +
  "Never re-ask a question the replies already answer; preserve already-answered material and ask only what is still unanswered.\n" +
  "- At every develop-skill approval gate (end of Phase 1 design, end of Phase 3 plan, Phase 8 push/PR) and on any ambiguity " +
  "you cannot resolve from the repo, STOP and return a blocked/awaiting-approval outcome — do not wait, do not ask the user yourself.\n" +
  "- Review gates (develop skill Rule 7, factory-worker mode): reviewers must ALWAYS be fresh-context subagents — " +
  "you NEVER review your own work in-session. At the Phase 2 plan gate and the Phase 6 code-review gate, STOP and return " +
  "\"outcome\": \"blocked\" with \"review_kind\": \"plan\" | \"code\" and \"review_artifact\": \"<path to the artifact — the plan doc or diff file — on your branch>\". " +
  "The supervisor spawns a fresh reviewer and relaunches you with the findings. Never attempt the review yourself.\n\n" +
  "Hard prohibitions: never push, merge, or delete branches. Never edit the backlog doc (" + backlogPath + "). " +
  "No side effects outside branch \"" + branchName + "\".\n\n" +
  "Outcome meanings: \"done\" = implemented and self-verified, no approval needed. " +
  "\"awaiting-approval\" = stopped at a develop-skill gate needing the user's explicit approval. " +
  "\"blocked\" = needs answers to the listed questions, OR a review gate (then review_kind + review_artifact must be set). " +
  "\"failed\" = non-retryable or retries exhausted.\n\n" +
  "Your return value must ALWAYS be exactly the JSON object below — never a workflow control envelope, never any other shape, " +
  "and it must not contain a field named \"status\". Return ONLY that JSON object as your final response:\n" +
  "{ \"outcome\": \"done\" | \"awaiting-approval\" | \"blocked\" | \"failed\", " +
  "\"title\": \"" + item.title.replace(/"/g, "'") + "\", \"summary\": \"...\", " +
  "\"branch\": \"" + branchName + "\", \"commit\": \"<full sha of your latest commit or empty>\", " +
  "\"questions\": [\"...\"], \"reconciliations\": {}, " +
  "\"review_kind\": \"plan\" | \"code\" (ONLY when outcome is blocked at a review gate — omit otherwise), " +
  "\"review_artifact\": \"<artifact path, only when outcome is blocked at a review gate>\" }",
  { key: "develop-" + itemId, label: "Develop: " + item.title, phase: "implement", timeoutMs: 2700000 }
);

if (!implement || !implement.outcome) {
  return stalled("implement child returned no usable payload: " + preview(implement));
}
const validOutcomes = ["done", "awaiting-approval", "blocked", "failed"];
if (validOutcomes.indexOf(implement.outcome) === -1) {
  return stalled("implement child returned invalid outcome: " + preview(implement));
}
log("dev-factory: implement outcome=" + implement.outcome + " commit=" + (implement.commit || "none"));

// ---------------------------------------------------------------------------
// verify: tests / typecheck per repo, with a bounded repair loop (T2).
// Only runs when the worker claims done — gates (awaiting-approval/blocked)
// and failures terminate the run as-is; the resume run re-verifies.
// ---------------------------------------------------------------------------
let finalCommit = implement.commit || null;
let failureSummary = implement.outcome === "failed" ? (implement.summary || "worker reported failed") : "";

if (implement.outcome === "done") {
  phase("verify");
  const MAX_VERIFY_ATTEMPTS = 3;
  let verified = false;
  let lastFailures = "";
  for (let attempt = 1; attempt <= MAX_VERIFY_ATTEMPTS; attempt++) {
    log("dev-factory: verify attempt " + attempt + "/" + MAX_VERIFY_ATTEMPTS);
    const check = await agent(
      "You are the verifier for factory item \"" + item.title + "\" (id: " + itemId + ").\n" +
      "Worktree: " + worktreePath + ". Branch under test: " + branchName + ".\n\n" +
      "1. Discover the repo's test/typecheck commands read-only: check AGENTS.md, CONTRIBUTING.md, package.json scripts, " +
      "Makefile, or pyproject.toml in the worktree. Do not guess — if no test command is documented, say so.\n" +
      "2. Run the full relevant suite (tests + typecheck/lint if documented). Capture failures verbatim.\n" +
      "3. Change nothing. Commit nothing.\n\n" +
      "Return ONLY this JSON (no field named \"status\"): " +
      "{ \"outcome\": \"pass\" | \"fail\", \"summary\": \"...\", \"failures\": \"<verbatim failure output, truncated to ~4000 chars>\" }",
      { key: "verify-" + itemId + "-a" + attempt, label: "Verify: " + item.title, phase: "verify", timeoutMs: 900000 }
    );
    if (!check || (check.outcome !== "pass" && check.outcome !== "fail")) {
      return stalled("verify child returned no usable payload on attempt " + attempt + ": " + preview(check));
    }
    if (check.outcome === "pass") {
      log("dev-factory: verify passed on attempt " + attempt);
      verified = true;
      break;
    }
    lastFailures = check.failures || check.summary || "(no failure detail)";
    log("dev-factory: verify failed on attempt " + attempt);
    if (attempt < MAX_VERIFY_ATTEMPTS) {
      const repair = await agent(
        "You are the repair agent for factory item \"" + item.title + "\" (id: " + itemId + ").\n" +
        "Worktree: " + worktreePath + ". Work ONLY on branch \"" + branchName + "\" — never push, merge, or touch other branches.\n\n" +
        "The verifier failed with this output:\n" + String(lastFailures).slice(0, 4000) + "\n\n" +
        "Fix the failures with minimal changes on the branch. Do not re-architect. " +
        "Commit the fix as \"factory(" + itemId + "): repair — <short description>\" (check `git log` first; never duplicate a commit).\n\n" +
        "Return ONLY this JSON (no field named \"status\"): " +
        "{ \"outcome\": \"repaired\", \"commit\": \"<full sha of the fix commit>\", \"summary\": \"...\" }",
        { key: "repair-" + itemId + "-a" + attempt, label: "Repair: " + item.title, phase: "verify", timeoutMs: 1200000 }
      );
      if (!repair || repair.outcome !== "repaired") {
        return stalled("repair child returned no usable payload on attempt " + attempt + ": " + preview(repair));
      }
      finalCommit = repair.commit || finalCommit;
      log("dev-factory: repair commit=" + (repair.commit || "none"));
    }
  }
  if (!verified) {
    failureSummary =
      "verification failed after " + MAX_VERIFY_ATTEMPTS + " attempts; last failures:\n" +
      String(lastFailures).slice(0, 2000);
  }
}

// ---------------------------------------------------------------------------
// report: the top-level return is exactly the terminal envelope (plan §5.3).
// ---------------------------------------------------------------------------
phase("report");

if (failureSummary) {
  log("dev-factory: terminal=failed");
  return envelope("failed", {
    questions: implement.questions || [],
    failure_summary: failureSummary,
    commit: finalCommit
  });
}

log("dev-factory: terminal=" + implement.outcome);
// needs-review passthrough (M4): a blocked review-gate return carries
// blocked_details into the terminal envelope so apply-envelope.sh can park
// with needs_review and the supervisor can run the fresh-reviewer protocol.
const reviewKind = implement.review_kind;
if (implement.outcome === "blocked" &&
    (reviewKind === "plan" || reviewKind === "code")) {
  log("dev-factory: terminal=blocked needs-review kind=" + reviewKind +
      " artifact=" + (implement.review_artifact || "(none)"));
  return envelope("blocked", {
    questions: implement.questions || [],
    reconciliations: implement.reconciliations || {},
    commit: finalCommit,
    blocked_details: {
      review_kind: reviewKind,
      artifact_path: implement.review_artifact || null
    }
  });
}
return envelope(implement.outcome, {
  questions: implement.questions || [],
  reconciliations: implement.reconciliations || {},
  commit: finalCommit
});
