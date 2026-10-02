# Concurrent development and the hardware bridge

GitHub issues own tasks, pull requests own implementations, CI owns software
check results, and linked evidence records own hardware observations. Labels are
indexes, not independent evidence. This runbook extends the existing local hub,
worktree, collision, golden-behavior and immutable-package tools; it replaces none
of their safety contracts. See [agent coordination](AGENT_COORDINATION.md).

## Roles

| Role | Default work | Boundary |
|---|---|---|
| Codex Cloud | Assigned isolated issues, regressions, replay/simulation, covered refactoring, static analysis, code documentation, CI | No Ally access, hardware claims, deployment, or hardware-gated merge without recorded local PASS |
| Claude Code | Assigned features, difficult bugs, architecture within approved scope, focused implementation/review | One issue and dedicated branch/worktree; no edits to another owner's checkout |
| Local Codex | GitHub coordination, claims, integration readiness, exact artifacts, local-network capture and hardware evidence | Hardware access does not make it the default implementation worker |
| Ronnie | Product decisions, genuinely risky approvals, physical operations and player observations | One concise physical action per supervised step; agents collect and route evidence |

These are routing defaults, not model rankings. Existing scoped primaries retain
their assignments. A stable session ID identifies the implementation owner;
GitHub accounts alone cannot distinguish two agents using Ronnie's credentials.
Read-only reviewers are not competing owners. Bounded editing delegates must be
named under the task, have disjoint ownership/worktrees, and return committed work
to its one primary owner.

## GitHub task record

Search open and closed issues and current PRs before creating work. Use the
engineering-task issue template. Keep human-readable scope, acceptance criteria,
dependencies, next action and evidence in the issue. One `regear-task` fenced JSON
block is the machine-readable claim. Update it through the **Agent coordination**
workflow, not competing body edits. The validated schema and CLI live in
`scripts/github_coordination.py`.

Every claim includes owner, role, branch, status, change class, hardware
requirement, scope and validation requirement. The workflow serializes updates,
checks the expected revision and conflicting managed claims, preserves issue
prose, and refreshes labels/statuses. A dispatched or queued workflow is not a
claim. Read back the successful run and issue record before implementation.
Only issues opted in with the `agent-task` label enter the managed inventory;
text in an arbitrary public issue cannot claim work or block all PRs.
GitHub may replace an older pending run in a concurrency group; a cancelled run
acquires nothing. Re-read before resubmitting. Never blindly increment revisions.

Create `task-update.json` locally with the workflow inputs (the `record_json`
value is a JSON string containing the complete record). Dispatch without shell
interpolation of issue content:

```text
gh workflow run agent-coordination.yml --repo ronnierosal/Re-Gear --ref main --json < task-update.json
```

In PowerShell, use `Get-Content -Raw task-update.json | gh workflow run
agent-coordination.yml --repo ronnierosal/Re-Gear --ref main --json`.
Inputs are `issue`, `expected_revision`, and `record_json`. Initialization uses
expected revision 0 and an unowned `backlog` record at revision 1. The next update
claims an owner at revision 2 with status `claimed`. Read back the issue and run
result before creating implementation changes. A minimal record is:

```json
{
  "schema": 1,
  "owner": null,
  "agent": "codex-cloud",
  "branch": "agent/codex-cloud/123-example",
  "status": "backlog",
  "class": "A",
  "hardware": "not-required",
  "validation": "Focused regression, architecture, golden gate and required CI",
  "scope": ["tests/test_example.py"],
  "revision": 1
}
```

Evidence fields `software` and `review` contain `result`, full 40-character
`head`/`base`, and an evidence `url`; review also names `reviewer` distinct from
owner. Hardware evidence adds `agent: codex-local`, `tester`, `tested_commit`
matching head, and `artifact: sha256:<64 hexadecimal characters>`. Class D adds
`procedure_approval` linking the approved procedure. Bugs set `bug: true` and a
`regression` statement. B adds a `behavior` citation. The evidence links must
contain actual results, not merely restate PASS. Keep private raw data out.

Lifecycle:

```text
backlog -> claimed -> in-progress -> pr-open -> software-validated -> review-requested
  -> (changes-requested -> new head -> pr-open ...)
  -> ready-to-merge                                    (A/B)
  -> hardware-required -> hardware-validated -> ready-to-merge   (C/D)
  -> merged -> closed
```

Software-only work skips hardware states. From `pr-open` onward the
[orchestrator](#automatic-handoffs) advances states; agents dispatch claims,
transfers, `blocked`/`cancelled` and hardware evidence. `blocked` retains ownership and names
the missing evidence/next action; `cancelled` preserves the reason and successor.
Do not promote a status just to make CI green. The checker validates required
evidence, but cannot establish that a human or agent's assertion is true.

Add one standalone `Task: #123` line to the PR. The `coordination/pr` status checks
its canonical issue, branch and exact head/base evidence. Issue updates refresh
open PR statuses. Existing required `foundation` and `privileged-user-delivery`
checks remain. A new commit/base invalidates old acceptance. Re-read the issue,
open PR collisions and required checks immediately before merging; a cached green
status alone is insufficient.

## Merge classes

| Class | Meaning | Merge evidence |
|---|---|---|
| A | Software only: documentation, deterministic tests, tooling, pure refactoring with no hardware behavior change | Exact candidate software PASS, independent review, required CI, current base, clear ownership |
| B | Hardware related, established behavior preserved | A gates plus a specific established-behavior evidence citation and reviewer justification; use C if actual behavior remains uncertain |
| C | Correctness depends on physical hardware/native runtime behavior | A gates plus local hardware PASS for the exact candidate and immutable artifact |
| D | High risk: USB4 resets, live detach, display/session mutation, shutdown/suspend or possible loss of usability | C gates plus explicit supervised safety procedure/approval and rollback |

Classification follows the behavior changed, not directory names. Tests for a
hardware feature may be A; changing its device writer is D. No blanket hardware
gate for every PR. Reviewers challenge underclassification. Class B is not a way
to bypass a known unvalidated path. Unknown classification stays out of merging.

Owners may autonomously implement, commit, push and open PRs for claimed work.
The assigned integration driver may merge A, and justified B, when these gates
pass; no additional Ronnie approval is needed. C/D merge only after their exact
hardware gates pass. Deployment and physical actions remain separately governed
by [deployment validation](DEPLOYMENT_VALIDATION.md). Only the Coordination
orchestrator merges, and only eligible class A work as described below. No
workflow installs, executes hardware commands, or merges B/C/D.

## Automatic handoffs

GitHub is the message bus. Chat sessions are workers that read it; no agent
messages another agent's chat, and Ronnie does not relay results.
`.github/workflows/coordination-orchestrator.yml` runs
`scripts/coordination_orchestrator.py reconcile` on CI completion, PR events,
PR/issue comments, every 30 minutes and on demand. Each run recomputes every
managed task from live state (it is *level-triggered*), so a cancelled or
replaced run loses nothing and duplicate runs act once. For each task with one
open `Task: #N` PR on its branch:

| When | The orchestrator |
|---|---|
| PR is not a draft and the task is `claimed`/`in-progress` | records `pr-open` |
| `foundation` and `privileged-user-delivery` pass on the exact head, nothing else on it failed | records `software` PASS for that head/base and the CI link |
| `software-validated`, no review request for this head/base | posts one compact request, assigned to the other agent family (Claude ↔ Codex), and records `review-requested` with `review_request` |
| A valid `regear-review` PASS for this exact head/base | records `review`; A/B → `ready-to-merge`; C/D → `hardware-required` plus a hardware card on the issue |
| A valid FAIL | records `changes-requested` and points the owner at the findings |
| Any new head or base | drops software/review/hardware evidence and returns to `pr-open`, which repeats CI and review |
| `hardware-validated` with exact local hardware PASS | promotes to `ready-to-merge` for the integration driver (never auto-merged) |
| `ready-to-merge`, eligible class A | re-plans from fresh state, publishes `coordination/pr` and merges exactly the reviewed head only if that gate passed and the record is unchanged since, then records `merged` |
| The PR was merged by anyone | records `merged` with the merge commit |

Every record writer, meaning this workflow and Agent coordination, runs in
the one `github-task-record-writer` concurrency group, so two writers never
interleave. Each write also re-checks that the body still equals what the run
read, increments the revision once and rechecks owner/scope collisions. GitHub
has no conditional issue PATCH, so serialization, not the check alone, makes
this safe. A human editing a record body directly remains outside the
cooperative guard. Comments carry a hidden marker per task and exact head/base,
so a request or card is posted once even after a lost race. Untrusted triggers
(for example a comment by a non-writer) run read-only.

**Durable agent intent.** GitHub keeps one pending run per concurrency group,
so a queued `agent-coordination` dispatch can be replaced and lost. Prefer a
comment on the task issue, which no run can cancel:

````text
```regear-update
{"task": 456, "expected_revision": 3, "record": { ...complete next record, revision 4... }}
```
````

The reconciler applies pending updates oldest first with exactly the dispatch
workflow's validation: the expected revision, transfer rules and collisions.
It replies once per comment with `APPLIED as revision N` or `REFUSED: reason`.
The reply is posted only after the record write succeeded, and only the
reconciler's own replies count: those from `github-actions[bot]`, the
workflow token's identity, not any other installed bot. A failed write therefore leaves the intent
pending for the next run, and a hand-written acknowledgement cannot suppress
one.

After a claim, changing a task's class, hardware requirement, branch, scope,
agent, behavior citation, procedure approval, validation requirement or
bug/regression statement is accepted only if the update
also drops all software/review/hardware evidence and leaves the candidate
states. Validation then restarts from CI and review under the new
classification. A downgrade such as D → A can never carry old evidence into a
weaker gate.
A refused or stale intent changes nothing; re-read and post a new one. Of two
competing claims at the same revision, only the first can apply. The dispatch
workflow remains supported; re-read after it, because a replaced run acquires
nothing.

**Labels.** Every run repairs the mirrors: exactly one `task:`, `agent:`,
`risk:` and `hardware:` label from the record on the issue and its PR. The PR
also gets the issue's type, `area:` and `P0`–`P3` labels. Repair re-reads the
current labels, then adds and removes individual labels. It never replaces the
whole set, so descriptive labels, and a `merge-hold` added at the same moment,
are kept. Labels are a readable mirror only. A misleading label grants
nothing, and only `merge-hold`, `hold` or `needs-decision` can affect
automation, by stopping it. Any agent creating a GitHub issue or pull request
applies the existing type, area, priority/readiness and hardware labels at
creation when known, and reuses a canonical label instead of inventing one. Managed tasks
also go through the coordination record. The reconciler is the backstop, not
the plan.

### Review

Every review needs an exact candidate and an identity independent of the
owner, from the opposite agent family: Claude tasks are reviewed by Codex
(`codex-cloud` or `codex-local`), Codex tasks by `claude`. A second session of
the implementing family does not qualify, and `review_request.reviewer_agent`
can only name the opposite family. `next` routes the request to
`codex-cloud` or `claude` by default. To submit, review the
exact head against its base according to AGENTS.md and this runbook. Post
findings as normal PR comments, then one comment containing:

````text
```regear-review
{"task": 447, "head": "<40-hex head>", "base": "<40-hex base>",
 "result": "PASS", "reviewer": "<your stable session id>", "agent": "codex-cloud"}
```
````

Use `"result": "FAIL"` with blocking findings. A block counts only when it is
from a repository writer (not a bot), names this task, matches the current head
and base, names a reviewer other than the owner, and declares the requested
opposite `agent` family. Like reviewer IDs, the family is a cooperative
declaration, not authentication. The newest valid block for the candidate wins,
so a reviewer can retract a mistaken FAIL with a later PASS. The live comment
content governs: editing a block from PASS to FAIL (or back) takes effect on
the next run. Every recorded review must stay backed by a live valid block for
the candidate: one edited invalid, deleted or recorded from anywhere else is
withdrawn and the review requested again. The only exemption is the two
adopted pre-workflow prose reviews of #441 and #447, listed exactly in
`LEGACY_REVIEWS`; it ends with their current candidate. A live structured
review also stamps a missing `review_request`, and once set, `review_request`
can be removed or changed only together with dropping review and hardware
evidence and leaving the review states, or by a request for a new candidate
head/base.
The newest valid block governs every candidate state. A FAIL posted after
`ready-to-merge` or a hardware state withdraws that acceptance and returns
the task to `changes-requested`. A review of an old head is ignored. The
rework cycle needs no human: FAIL → owner pushes a fix → new head → CI → new
review request.

### Class A integration

Immediately before merging, the orchestrator re-reads the issue, labels, PR,
files, CI, reviews and base, and plans again from that live state. It merges
only if the fresh plan still produces the same merge. It then publishes the
PR's `coordination/pr` status from that state and merges through the
protected-branch PR merge API with the reviewed `sha`. The exact-base guard is
GitHub's own:

- The orchestrator first reads the base branch rules and auto-merges only if
  they require pull-request integration and **strict** (up-to-date)
  `foundation`, `privileged-user-delivery` and `coordination/pr` checks, as
  `main`'s ruleset does today.
- With that policy, GitHub refuses a branch that is not current with the base
  at merge time, and `sha` refuses a moved head.
- If the rules weaken, automatic integration stops with a reported blocker
  instead of merging unguarded.

The orchestrator records `merged` only after GitHub confirms it. A check that
ends in anything other than success, neutral or skipped (including
`startup_failure`) is never green. The plan requires all of these:

- the class is A, `hardware` is `not-required`, and the task does not set `"auto_merge": false`;
- there is no `merge-hold`, `hold` or `needs-decision` label on the issue or PR;
- the PR changes no protected merge-authority path: `.github/`, the coordination
  and orchestrator scripts, `AGENTS.md`, `CLAUDE.md`, this runbook,
  `docs/AGENT_COORDINATION.md` or `contracts/coordination-workers.json`. Those
  changes need independent review and separate integration, so the automation
  can never bootstrap its own authority;
- the PR is not a draft;
- the full `coordination/pr` gate passes: owner, branch, scope, exact software and review evidence, independent reviewer, collisions;
- required CI is green on the head;
- GitHub reports the PR mergeable and the head contains the current base tip.

If the base moved, it asks the owner once to merge the current base. The new
head then repeats CI and review. A GitHub-token merge triggers no push
workflows, so the orchestrator dispatches `CI` for both profiles on the base
branch and refreshes PR gates itself. B is merged by the assigned integration
driver after the same gates. C/D wait for exact-candidate local hardware PASS.
Closing the issue stays with its owner, because merging does not mean every
acceptance criterion is met.

### Agent loop and work in progress

```text
python scripts/coordination_orchestrator.py next --repo ronnierosal/Re-Gear --agent claude --session <id>
python scripts/coordination_orchestrator.py reconcile --repo ronnierosal/Re-Gear --dry-run
python scripts/coordination_orchestrator.py watchdog --repo ronnierosal/Re-Gear
```

`next` lists, in order: rework on your tasks, your unfinished implementation,
review requests for your agent family, hardware and B/C/D integration for
`codex-local`, and then at most one eligible backlog claim. A claim is offered
only when you have no implementation in progress and at most one task waiting.
It matches the record's `agent` (explicit routing overrides domain defaults),
avoids scope collisions, and is ordered by `P0`–`P3` labels. When your task is
waiting on CI, review or hardware, run `next` again rather than going idle.

`watchdog` runs after every reconcile and writes a job summary. It reports
tasks waiting longer than their normal window: one hour without a review
request, a day without a review, two days without rework, six hours
ready-to-merge, three days for hardware. It also reports failed required CI
and conflicted PRs. Ordinary waiting inside those windows is not reported.

### Remaining human touchpoints and limits

Ronnie is still needed for:

- product decisions (`needs-decision` holds integration);
- physical device actions;
- class D procedure approval;
- credential, branch-protection and repository-setting changes;
- conflicts the owners cannot settle.

Limits:

- Nothing here starts an agent. Sessions find work through `next`, PR
  subscriptions or scheduled sessions configured outside this repository.
- All agents share one GitHub account, so reviewer identity is the declared
  session ID. Like the task records, this is a cooperative guard, not
  authentication.
- Branch protection that requires an approving GitHub review blocks the
  automatic merge. The task then stays `ready-to-merge`, and `watchdog`
  reports it.

## Regression-first bugs

1. Capture a bounded failure with revision, inputs, expected/actual behavior and
   timestamps. Redact identifiers; link the approved evidence artifact.
2. Reduce the earliest failing interaction to an existing fixture, integration
   test or deterministic replay. Reuse actual admission/dispatch boundaries.
3. Demonstrate failure before the fix when practical, then implement the smallest
   fix and demonstrate PASS. If reproduction is impossible, record the precise
   gap and substitute evidence; do not invent a passing reproduction.
4. Run affected regressions and golden behaviors, then full required CI at the
   integration gate. Preserve demonstrated successful journeys and their timing.
5. Only then queue a hardware-dependent candidate. FAIL becomes a focused linked
   follow-up or reopens the same issue; INCONCLUSIVE identifies the evidence gap.

Do not ask Ronnie to repeat an unchanged failing trial. A new trial needs a new
candidate or a specific observation that distinguishes competing explanations.

## Hardware queue

```text
python scripts/github_coordination.py queue --repo ronnierosal/Re-Gear
gh issue list --label task:hardware-required --state open
```

The JSON record is authoritative if labels drift. Queue cards include:

```text
Issue / implementation owner / local test driver:
PR / exact head and base:
Software checks and independent review links:
Artifact URL or immutable local path / version / SHA-256:
Test and expected behavior:
Baseline, evidence to collect and stop conditions:
Risk class / approved procedure:
Rollback artifact, hash and recovery procedure:
Next single physical action:
```

The local driver fetches, verifies exact commits and dependencies, runs applicable
local checks, and either verifies the controlled CI artifact or packages once
under [release coordination](CHAT_COORDINATION.md). Recheck installed ancestry;
stage immutably with SHA-256 readback. Staging, installation and hardware success
are separate claims. Ronnie currently installs through Decky; remote installation
requires its own explicit authorization. Cloud runners receive no Ally secrets.

Verify installed revision before establishing the baseline. Start an approved
bounded read-only capture and confirm its first sample before saying monitoring
is armed. Use existing diagnostic/capture tools from [diagnostics](DIAGNOSTICS.md),
[remote validation](REMOTE_VALIDATION.md) and [operator handoff](OPERATOR_HANDOFF.md).
Give Ronnie one physical action, observe the result, then decide the next action.
Never equate software removal with physical absence or infer safety from silence.

Record PASS / FAIL / INCONCLUSIVE with tested commit, artifact hash, device/profile,
installed identity, expected/actual behavior, redacted evidence, limits and next
action. Hardware evidence belongs in a GitHub issue/PR comment or linked approved
artifact, not only local chat. The driver collects logs; Ronnie need not shuttle
them. Attach a minimized reproducible fixture to the implementation owner when
safe. Preserve failed history and rollback packages. No unattended powered tests.

## Existing deterministic coverage

The setup changes no lifecycle implementation. Existing tests already cover:

| Journey segment | Existing suites / infrastructure |
|---|---|
| Portable, attachment, transport, GPU and TV readiness | `test_mode_inference.py`, `test_attach_readiness.py`, `test_connection_readiness.py`, `test_topology_event_detection.py` |
| Requested switch, TV state, stale observation and failures | `test_transition_replay.py`, `test_transition_orchestrator.py`, `test_supervised_transition.py`, JSON snapshots in `tests/fixtures/` |
| Running game and process/resource release | `test_game_close_consent.py`, `test_process_release_replay.py`, `test_disconnect_sequence.py` |
| Portable return, guarded device removal and unplug | `test_main_disconnect_portable_order.py`, `test_whole_dock_runtime.py`, `test_main_physical_unplug_sleep.py` |
| Reconnect, unexpected loss and boot/recovery | `test_automatic_recovery_lifecycle.py`, `test_unexpected_removal_recovery.py`, `test_interrupted_docked_sleep.py` |
| Sleep partial order and failure replay | `test_canonical_sleep_replay_integration.py`, `canonical_sleep_replay_support.py`, `tests/fixtures/replay/canonical-sleep.json` |

These test policy, fixtures and mocked mechanisms. They do not emulate USB4/kernel
timing, native Steam/Decky rendering, controller focus, actual suspend, or thermal
behavior. Extend this infrastructure with redacted captured inputs and explicit
timing/failure injection before considering a new simulator. UI mocks must load
real styles and real payloads; native evidence remains necessary where relevant.

## Adoption and continuous work

This system enables concurrent work; it does not schedule agents, buy cloud
capacity or assume a Codex Cloud environment exists. Assign cloud tasks through
the available GitHub/Codex integration with the issue URL, exact base, acceptance
criteria and command list. Use Python 3.11+, Node 24 and pinned pnpm from
`package.json`; `pnpm install --frozen-lockfile`, then `pnpm build` before bundle
tests. Hardware credentials and deployment helpers are not cloud setup steps.

At rollout, preserve existing branches, hub claims and uncommitted experiments.
Backfill canonical issues with their current owners before advancing those PRs;
do not bulk reassign or label historical green CI as hardware validation. Old
checkouts must reload `origin/main:AGENTS.md`. The local hub remains useful for
notifications and path collision checks, but cannot grant a competing claim.

The coordination workflow is a cooperative engineering guard, not an identity
service: repository writers can edit issue metadata. Required status checks and
independent review enforce the agreed process; they cannot prove an experiment
happened. Status changes need live revalidation at merge. Do not promise automatic
agent wake-up, automatic log capture without connectivity, or hardware completion.
