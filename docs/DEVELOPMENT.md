# Development workflow

Re-Gear favors small, reversible progress with validation proportional to blast
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
pnpm build
python scripts/check_architecture.py
python -m unittest discover -s tests -v
python -m compileall -q backend tests scripts
pnpm typecheck
pnpm test:frontend
python scripts/check_plugin_package.py .
git diff --check
```

`pnpm build` runs first, not last. `dist/` is generated rather than committed,
and three later gates read it from the checkout: `tests/test_capture_provenance.py`
hashes `dist/index.js` as one of the critical files, and the branding and
bundle-clearance frontend tests audit the shipped bundle rather than the
sources. A fresh clone has nothing for them to read until the build has run.
`scripts/check_plugin_package.py` and `scripts/build_plugin.py` read the same
built bundle and say so if it is absent.

A Python-only checkout with no Node toolchain can still run the Python suite:
the provenance tests skip rather than fail when the bundle is missing. CI always
builds first, so they are always exercised there.

Do not repeatedly run the full matrix after tiny documentation edits. Do not
skip the full matrix when producing or deploying an artifact.

## Automatic failure diagnosis

A failure starts diagnosis:

1. Capture the exact command, failure, timestamp, and relevant revision.
2. Inspect bounded Re-Gear logs, current transaction/action history, and applicable
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
- Generated `dist/index.js` and its source map are not in Git, and neither are
  `out/` artifacts. `pnpm build` produces the bundle; packaging consumes what
  that build left on disk. Committing it made a generated file the most
  contended path in the repository, conflicting in pull requests whose source
  merged cleanly, so CI now rebuilds it and refuses to let it be tracked again.
- A worker may create a local commit for a coherent verified slice when its
  driver owns the worktree or has coordinated the shared paths.
- Create a branch when isolation is useful or explicitly requested; report its
  starting point.
- Merge only after ancestry, conflicts, diff scope, and relevant checks are
  known. Prefer fast-forward integration for bounded worker branches.
- Scoped commits, branch pushes, PRs, and validated routine merges have standing
  authorization under `AGENTS.md`. Its narrow high-risk boundaries govern release,
  publication, history rewriting, credentials, and hardware actions.

## Concurrent chats and agents

Follow [Agent coordination](AGENT_COORDINATION.md) and
[release coordination](CHAT_COORDINATION.md) whenever more than one chat or
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
