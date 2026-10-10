# Shared hub commands

GitHub issues are authoritative for task ownership across machines. This hub
remains a local notification and collision-checking aid. Mirror canonical issue
IDs, owners and accepted GitHub transfers; a local claim does not override them.
Do not initialize private hubs in cloud clones. Existing records and audit
history are retained; see `docs/CONTINUOUS_DEVELOPMENT.md` in the repository.

## Setup and adoption

Canonical source is this directory; install `hub.py` and `hub.ps1` into the existing
workspace-level `agent-hub/` after tests. Do not replace its `data/` directory.
Run `hub.ps1 init` only for first setup (it is idempotent and preserves existing
records). Python 3.11+ and its standard library are sufficient. The installed
PowerShell wrapper prefers Python on PATH and falls back to the desktop runtime.
For a portable shell use `python3 -B /workspace/agent-hub/hub.py <command>`.

The source copy requires an explicit `--db /workspace/agent-hub/data/hub.sqlite3`.
This prevents accidentally creating independent databases inside worktrees.
Installed copies use `data/hub.sqlite3` relative to the script, never the caller.
Update the workspace `AGENTS.md` to point to the canonical repository `AGENTS.md`
and `CLAUDE.md` to point to that workspace entry. During an unmerged policy rollout,
record the precise policy worktree/branch there; after merge switch to `main/AGENTS.md`.
Do not silently edit other agents' instruction files or checkouts.

## Start / resume

From the shared workspace root (replace session and worktree placeholders):

```powershell
.\agent-hub\hub.ps1 status
.\agent-hub\hub.ps1 register --session codex-SESSION --agent codex --label "Task owner" --worktree "my-task"
.\agent-hub\hub.ps1 inbox --session codex-SESSION
.\agent-hub\hub.ps1 snapshot
```

Claude uses the same commands with `--session claude-SESSION --agent claude`.
Use your stable actual session ID; agent names are not identities. Registration
is idempotent with identical metadata. Never borrow an existing ID. Stream leads
route shared inboxes. Under the shared policy, workers claim primary-assigned
tasks or explicit Ronnie assignments. `primary-<scope>` records the designated
Codex coordinator for that focused project/workstream; a technically available claim is not assignment authority.
See [primary workflow](../../docs/AGENT_COORDINATION.md#project-primary-and-delegation)
in the repository source (installed copies use the fetched repository policy).

## Requests

Write a UTF-8 JSON request file, then apply it with your registered identity:

```powershell
.\agent-hub\hub.ps1 apply --session codex-SESSION --request .\request.json
```

Python also accepts JSON on stdin. Unknown fields are rejected. Request examples:

```json
{"op":"create_task","id":"bounded-task","stream":"coordination","title":"A bounded problem","branch":"codex/bounded-task","paths":["docs/example.md"],"dependencies":[],"note":"Scope: ... Out: ... Done when: ... Next: claim and inspect."}
```

Use [task.example.json](task.example.json) as a starting point. Optional `issue`
and `pr` fields link external records. Tasks need scope and acceptance in `note`;
paths list likely files/modules, not every eventual edit. Dependencies reference
existing tasks and are immutable to avoid cycles; split a changed problem into a
new task. A distinct assigned subproject may use `create_stream` with `id` and
`title`; search existing streams first. `claim_stream` takes `stream` and `rev`
and only claims an unowned stream. It is unnecessary to claim tasks.

```json
{"op":"claim_task","id":"bounded-task","rev":1}
```

Claims atomically establish one owner, check completed dependencies and overlapping
active paths. `src` overlaps `src/a.py`, case-insensitively. Exact relative paths
only; no traversal or glob patterns. These are cooperative collision guards, not
editor locks. Empty paths still require semantic overlap review.

```json
{"op":"update_task","id":"bounded-task","rev":2,"paths":["docs/example.md","docs/index.md"],"note":"Scope unchanged; index link is necessary. Other claims checked. Next: validate."}
```

Only the current owner may update. Path changes require in-progress state and a
reason; conflicting expansion fails without changing state. For shared files,
sequence/split with the other owner or use accepted transfer; do not evade a
conflict by dropping paths while still editing them.

```json
{"op":"update_task","id":"bounded-task","rev":3,"state":"blocked","note":"Waiting for task X. Next: recheck its acceptance evidence."}
```

```json
{"op":"update_task","id":"bounded-task","rev":4,"state":"in_progress","note":"Dependency resolved. Next: run focused checks."}
```

```json
{"op":"update_task","id":"bounded-task","rev":5,"state":"review","evidence":"Head abc123: tests passed; PR linked. CI/merge pending.","note":"Next: check final-head CI and current base, then merge."}
```

```json
{"op":"update_task","id":"bounded-task","rev":6,"state":"done","evidence":"Head abc123: checks and CI passed; merged as def456. Acceptance met.","note":"Complete; no remaining work."}
```

States: `todo -> in_progress -> review -> done`; review is optional. `blocked`
resumes through in-progress. `cancelled` requires a reason. Done/cancelled release
scope and are terminal; cancelled dependencies never count as done. Review/done
require evidence. Resuming clears evidence. Use actual current revisions; reread
and reassess stale failures, never blindly increment the request.

## Inbox and accepted ownership transfer

```json
{"op":"send","stream":"coordination","to":"recipient-session","subject":"Review request","body":"Scope, revision, checks, and one next action."}
```

Omit `to` for the stream's shared inbox. Only its current lead receipts shared
messages; direct recipients receipt their own. All are visible in `status`.

```json
{"op":"receipt","id":"message-id","state":"read"}
```

Use `acknowledged` after accepting the meaning of a handoff; neither receipt
completes work. Reply using `send` with `reply_to`, the same stream and original
sender as `to`; this atomically marks the original `replied`. Receipts do not go
backwards or transfer to new owners. Viewing status never creates a receipt.

```json
{"op":"offer_transfer","kind":"task","id":"bounded-task","rev":2,"to":"recipient-session","note":"Branch/head, scope, checks, blockers, next action."}
```

```json
{"op":"accept_transfer","id":"transfer-id"}
```

The recipient must accept before ownership changes. Changed task revisions
invalidate offers. The sender may `cancel_transfer` with its ID. Use kind `stream`
for lead transfer; this does not transfer tasks.

## Views, storage and limits

`status` returns full JSON. `snapshot` returns concise dated text suitable for
ChatGPT/voice. `export` generates a read-only escaped `dashboard.html`; regenerate
to refresh. `history` returns the latest 100 events; older audit events remain in
SQLite. Views do not mutate ownership or receipts. A snapshot is never a live lock.

The database must stay on local disk (no cloud-sync/network share). Back up with
SQLite's backup API or stop writers and use a quiescent backup; do not copy only
the database during WAL writes. IDs are self-declared, not authentication. No
credentials, private account data or raw device logs belong here. No network,
model launch, polling, or hardware execution is implemented. GitHub remains the
cross-machine coordination record. Hub claims never bypass `AGENTS.md` gates.

## Verification

From the repository root:

```text
python -B -m unittest discover -s tests -p test_agent_hub.py -v
```

Disposable databases test concurrent claims, scope conflicts, revisions, accepted
transfers, dependencies, evidence, receipts, safe rendering, and CLI round trips.

## Engineering completion and documentation review

Claude and other implementation owners supply concise results, behavior changes,
limitations and exact commit/PR/test evidence, not polished public copy. Add one
standalone `Documentation impact: none|README|Wiki|Discussion|multiple` line to the
existing task note. See [completion.example.json](completion.example.json).

`hub.ps1 docs-queue` lists completed engineering tasks needing review, including
missing/invalid impact labels as `unassessed`. It is read-only. Codex/ChatGPT uses
an ordinary documentation task with the source dependency and a standalone
`Documentation review: <source-id>` line (see [review.example.json](review.example.json)).
A completed linked review clears the item; blocked/cancelled reviews do not.

The shared repository `docs/DOCUMENTATION_WORKFLOW.md` defines layer triggers,
validation, publication evidence and the standing routine-doc delegation. The
queue neither schedules agents nor publishes to GitHub. No schema migration is
needed; existing task records and ownership behavior remain compatible.


## Bounded #497 canonical recovery mirror (#532)

`mirror-accepted-497-recovery` is a single compiled maintenance capability for
`tdp-runtime-expressible-range-admission`. It records an accepted canonical
maintainer recovery, rather than an ordinary transfer offered by the old owner.
Normal `offer_transfer` and `accept_transfer` semantics remain unchanged.

The source capability is **disabled**: both the separate invocation approval and
the exact live maintenance-assignment digest are unset. Testing and adopting this
code grant no permission to invoke it. No source-development test uses the real
workspace database; all recovery tests use temporary synthetic databases.

A separately reviewed invocation requires the actual designated maintenance
actor, a registered fixed recipient, the exact complete local revision-4 row
hash, the exact accepted canonical #497 revision-7 record hash, and the fixed
public authority/acceptance/handoff receipt references. It rejects stale or
altered bindings, replay, terminal records, pending authentic transfers and
other active overlapping paths/branches. An immediate transaction, conditional
update and audit insertion make failures atomic. Only owner and revision change;
all other local row fields, historical events and old-owner provenance remain.
The result includes the complete row for private readback; do not publish private
row contents or local workspace/session metadata. The audit contains digests and
public authority references and identifies the actual maintenance actor.

Before a later invocation: obtain separate exact approval; review the live
maintenance-assignment binding and compile it with that approval; verify supported
tool adoption, a consistent backup, fresh canonical evidence, full local preimage
and exclusive-writer/executor/collision checks. Preserve the original workspace
and old-head archive. A receipt file has exactly `issue` (497), `record` (the full
accepted canonical object), and `receipts` (the three fixed references in source),
with a maximum UTF-8 encoded size of 65536 bytes. The helper compares pinned
bindings locally; it does not fetch or certify live GitHub state. Fresh remote
readback is the coordinator's separate prerequisite.

Only after those separate decisions, the supported CLI form is:

```text
python -B hub.py --db <existing-shared-database> mirror-accepted-497-recovery --session codex-local-coordination-recovery-20261008 --canonical-receipt <verified-private-receipt.json>
```

Read back the full row and actual-actor audit after a successful transaction,
compare every preserved field and recheck executor exclusivity before releasing
#497 source work. A failed gate leaves that work held. No arbitrary task, owner,
force, authorization, bypass or target option exists. This capability grants no
TDP, runtime, device, install, package, release or hardware authority.
