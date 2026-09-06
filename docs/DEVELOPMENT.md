# Development workflow

HDM favors small, reversible progress with validation proportional to blast
radius. Safety is strict around hardware mutation; ordinary repository work
should not accumulate ceremony.

## Start every workstream

```text
git status --short --branch
git rev-parse HEAD
git log -1 --oneline --decorate
```

Read `AGENTS.md`, [Current state](CURRENT_STATE.md), and the authoritative docs
for the affected area. Check for active work in shared files before editing.

## Iteration and verification

Use the smallest check that can falsify the current change:

- documentation: local links, `git diff --check`, and affected contract review
- pure domain change: focused unit tests plus architecture check
- adapter/delivery change: focused adapter tests, compilation, and relevant
  package or frontend check
- frontend change: focused frontend test, typecheck, then build when integration
  is meaningful
- packaging/version change: package contract, archive build, provenance verifier
- hardware-affecting change: all applicable local gates before a separately
  approved supervised session

At integration, deployment, or release gates run:

```text
python scripts/check_architecture.py
python -m unittest discover -s tests -v
python -m compileall -q backend tests scripts
pnpm typecheck
pnpm test:frontend
pnpm build
python scripts/check_plugin_package.py .
git diff --check
```

Do not repeatedly run the full matrix after tiny documentation edits. Do not
skip the full matrix when producing or deploying an artifact.

## Automatic failure diagnosis

A failure starts diagnosis:

1. Capture the exact command, failure, timestamp, and relevant revision.
2. Inspect bounded HDM logs, current transaction/action history, and applicable
   system state.
3. Correlate timestamps and identify the earliest divergence.
4. Form one concrete hypothesis.
5. Apply the smallest justified fix.
6. Re-run the failing check, then the relevant regression gate.

When authorized and useful, a worker may use the documented read-only SSH
capture instead of waiting for another prompt. Remote mutation still obeys
[Deployment validation](DEPLOYMENT_VALIDATION.md) and the current hardware
driver's ownership.

## Git rules

- Keep commits small, focused, and descriptive.
- Do not mix unrelated cleanup with a fix.
- Inspect staged paths and diff before committing.
- Generated `dist/index.js` and its source map belong in Git only as the
  intentional Decky package outputs; `out/` artifacts do not.
- A worker may create a local commit for a coherent verified slice when its
  driver owns the worktree or has coordinated the shared paths.
- Create a branch when isolation is useful or explicitly requested; report its
  starting point.
- Merge only after ancestry, conflicts, diff scope, and relevant checks are
  known. Prefer fast-forward integration for bounded worker branches.
- Never push, tag, publish, create a release, force-push, rewrite published
  history, or delete remote refs without explicit maintainer authorization.

## Concurrent chats and agents

Follow [Chat coordination](CHAT_COORDINATION.md) whenever more than one chat or
agent may modify the repository. Active implementation never happens in the
shared `main` checkout. Before an integration, run:

```text
python scripts/check_integration_preflight.py
```

The check rejects a dirty workspace, unresolved conflicts, an in-progress Git
operation, a detached checkout, a non-integration branch, or an integration
branch that no longer contains the current `origin/main`.

Before any authorized push report branch, HEAD, ahead/behind state, dirty/clean
state, tests performed, and generated artifacts included. A GitHub CI result
validates only its exact workflow commit.

## Version and artifact discipline

`package.json` is the semantic-version source. The Python project version,
archive filename, embedded build metadata, candidate record, checksum, installed
metadata, and runtime label must agree. Follow [Release pipeline](RELEASE_PIPELINE.md)
and [Deployment validation](DEPLOYMENT_VALIDATION.md); never test a ZIP selected
only by filename or modification time.
