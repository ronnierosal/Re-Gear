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
backlog -> claimed -> in-progress -> pr-open -> software-validated
  -> hardware-required -> hardware-validated -> ready-to-merge -> merged -> closed
```

Software-only work skips hardware states. `blocked` retains ownership and names
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
by [deployment validation](DEPLOYMENT_VALIDATION.md). No workflow introduced here
installs, executes hardware commands, or automatically presses Merge.

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
