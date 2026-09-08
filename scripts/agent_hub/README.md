# Shared hub commands

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
route shared inboxes; registered sessions may claim available tasks directly.

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
