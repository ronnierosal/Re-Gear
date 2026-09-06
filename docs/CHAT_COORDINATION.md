# Concurrent chat and agent coordination

This playbook prevents one workstream from overwriting another. It governs
repository changes, not hardware authority: Ally/G1 deployment and transitions
remain separately supervised.

## Roles and workspaces

- **Worker:** one bounded issue, one `codex/<workstream>` branch, and one
  dedicated Git worktree. It may modify only its declared files or module area.
- **Integrator:** the only role allowed to assemble worker commits. It works in
  a clean `codex/integration-<date-or-topic>` worktree created from
  `origin/main`.
- **Shared main checkout:** read-only for inspection. Do not implement there,
  resolve conflicts there, or begin a cherry-pick there.

## Worker handoff

Before handing work over, a worker must provide its branch, commit SHA, changed
paths, focused checks, and any unverified hardware claims. Commit only a small,
coherent, reviewed slice. Do not hand off a patch mixed with generated output,
unrelated formatting, or another worker's files.

## Integration sequence

1. Start a new integration worktree from the current `origin/main`.
2. Run `python scripts/check_integration_preflight.py` before every merge or
   cherry-pick.
3. Inspect the candidate commit's ancestry and changed paths. Do not integrate
   overlapping workstreams together unless their interaction has been reviewed.
4. Integrate one reviewed commit or tightly coupled series, resolve conflicts
   only in the integration worktree, then run the relevant checks.
5. Record the resulting commit, included worker SHAs, checks, and any remaining
   hardware gate in `docs/OPERATOR_HANDOFF.md` or the relevant issue/PR.

If the preflight fails, stop. Preserve the current state, identify the active
Git operation or changed paths, and create a fresh integration worktree instead
of repairing shared `main` in place.

## Rules that prevent overwritten work

- Never use `git reset --hard`, force-push, or history rewriting to make a merge
  easier.
- Never discard uncommitted files belonging to another chat. Preserve them in
  their worktree and ask the owner/integrator to classify them.
- Keep release artifacts immutable and uniquely versioned; a package from one
  workstream never replaces another candidate by filename alone.
- A passing worker test suite proves only that worker's commit. Re-run the
  relevant tests after integration.
