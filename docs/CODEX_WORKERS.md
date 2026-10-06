# Scheduled Codex software workers

The Codex software worker launches a **fresh GitHub-hosted Codex process**, not
an existing ChatGPT conversation. It consumes the existing coordination
orchestrator's `next_actions`, canonical task records and durable update
acknowledgements. It is a separate execution adapter, not a second coordinator.
Dependency: the orchestration implementation in #456 / PR #458 must be integrated
before this workflow. This launcher also needs independent review and separate
integration; it cannot bootstrap its own authority.

The workflow is disabled unless repository variable
`REGEAR_CODEX_WORKERS_ENABLED` is exactly `true`. While enabled, issue/PR/comment
and CI/coordinator completion events plus an hourly fallback reconsider live
work. A single concurrency group serializes launches, with no cancellation of a
running worker. Each launch does one task; existing coordinator WIP limits apply.

## Authority and routing

The stable session is `codex-actions-worker`. It can claim only an eligible
unowned, managed `codex-cloud`, class A, software-only task, or resume its own
implementation/rework. Other chats' or Local Codex's tasks are never transferred
automatically. Transfers require the existing recorded offer and acceptance.
The scope must exclude coordination/worker execution paths. Those changes need
an explicit chat owner, review and separate integration.

Opposite-family review requests are retrieved with their exact head/base and
published as `regear-review` comments. Reviews do not change implementation
ownership. Changed task revisions, hold labels, head/base, or default-branch tip
stop publication. Reviews can identify hardware limitations but cannot establish
physical PASS. The coordinator remains responsible for CI evidence, review
routing, hardware queues and permitted integration. This adapter never merges,
closes issues, deploys or runs device operations.

The trusted planning job submits durable `regear-update` comments. It launches
no model until the coordinator's bot acknowledges acceptance and the issue
record reads back identically. Pending/refused/stale intent stops the run.
Two attempts per task/candidate/base are recorded in GitHub issue comments
by the configured writer; public commenters cannot consume that budget.
further automatic attempts on that candidate stop for inspection, while other
eligible reviews can continue. A changed candidate/base gives
a new attempt budget. There is no local task database. GitHub workflow runs
contain failure details; retries are bounded, not a promise that every task can
be repaired without intervention. Waiting tasks are left to the coordinator;
failed CI or base-refresh states not returned by `next_actions` still require
owner attention. This gap is tracked by #462 with the orchestration owner; this
adapter does not invent a second routing policy.

## Isolation and publication

Planning and publication use the writer credential; the intervening model job
has only the default read token and the Codex API credential. Checkout does not
persist GitHub credentials. Dependency installation uses the trusted baseline
lockfile before the task candidate is checked out. The Codex Action uses its
workspace permission profile and drops sudo on a disposable Linux runner.
For independent review the working tree stays on trusted main; candidate Git
objects are inspected as data, and exact-head CI is rechecked before publication.
The model's final JSON reports checks and limitations; those assertions do not
constitute CI or independent acceptance of its implementation.

The exported proposal is bounded UTF-8 file content, with no symlink, submodule,
binary, path traversal, duplicate path, out-of-scope or protected-path changes.
Publication uses a fresh default-branch checkout and the immutable planning
artifact ID. It does not execute generated code. It reconstructs the normal
merged baseline and publishes Git objects with a non-force branch update. A
concurrent branch change refuses publication. Source already in the worker's
branch is preserved. New PRs carry `Task: #N`, run evidence, limitations and
existing issue labels. The coordinator discovers them and advances state.
Model report text cannot inject reserved coordination blocks.

This is a cooperative trusted-writer workflow, consistent with the repository's
existing session-ID model; it does not authenticate the model's reasoning or
promise fault-free unattended development. Existing required checks, review and
hardware gates continue to apply.

## Activation checklist

An authorized repository operator must:

1. Integrate #458 and this independently reviewed launcher, then confirm the
   workflow and scripts are on the default branch.
2. Configure `OPENAI_API_KEY` as an Actions secret. Codex Action uses API billing,
   separately from a ChatGPT subscription. Set an API project budget appropriate
   for the schedule; the job timeout and attempt cap are not a token/spend cap.
3. Configure `REGEAR_CODEX_GITHUB_TOKEN` as an Actions secret belonging to a
   repository writer. It needs contents read/write, issues read/write and pull
   requests read/write, plus Checks read for current CI evidence. A fine-grained
   PAT should target only this repository.
   Current durable intents ignore bots, so the workflow's ordinary
   `GITHUB_TOKEN` is insufficient for claims/review comments. No hardware,
   installation, release or branch-protection credentials belong here.
4. Leave the enable variable unset; run local deterministic tests and inspect
   the reviewed job permissions and intended eligible backlog task.
5. Set the enable variable to `true`, dispatch once, and verify accepted claim,
   worker logs, PR candidate, required CI and opposite-family review. Do not
   infer success from a queued workflow or a model's PASS report.

Repository secret/variable metadata returned HTTP 403 during development;
existing configuration could not be inspected. No credentials or settings were
changed and no paid worker was launched by this implementation session.

Disable the enable variable to stop new launches. It does not cancel a running
job; cancel that run explicitly if needed. Disabling the workflow or reverting
these four files removes the layer. Existing issue records, branches, review
history and hardware queues survive. To resume a capped unchanged candidate,
inspect the two linked runs and use an explicit chat worker rather than erasing
attempt history.

## Source credit

Execution depends on **OpenAI Codex Action**, by OpenAI and contributors:
https://github.com/openai/codex-action/tree/86365089eb2b84e0a8fb0717b304f8bdcb13b20e
(Apache-2.0). Reuse type: pinned workflow dependency and documented setup/API
interface inspiration; no upstream source is vendored. GitHub Actions runtime
restrictions and credential routing follow its official guidance. Delivered
credit also belongs in `THIRD_PARTY_NOTICES.md`, coordinated with that file's
current owner (#438).
