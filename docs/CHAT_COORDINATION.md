# Multiple chat integration and release rules

Each chat owns an isolated worktree and branch. Never edit another chat's dirty
files or resolve its in-progress merge. Inspect worktree status before edits.

## Shared ready ledger

Git refs under refs/regear/ are shared by all worktrees in this repository.
They are local coordination records, not automatically shared with other clones.
Run `python scripts/release_coordination.py status` before starting and before
packaging. After tests and a clean commit, register completed work using
`python scripts/release_coordination.py ready <workstream>`.
Never register unfinished experiments. Existing ready entries may only advance
to descendants. Preserve earlier completed changes when resolving conflicts.

The release driver integrates every registered ready commit using normal Git
merges, reviews conflicts, and runs the full release matrix. Do not blindly
merge every historical worktree. Ask an active owner to finish overlapping work;
never absorb their uncommitted changes. Hardware work retains its separate
supervised safety gates. Inspect the installed revision before staging and
ensure it is an ancestor of the candidate, or explicitly resolve differences.

## One version and immutable ZIP

Use plain versions, for example Re-Gear-0.3.39.zip. No offline.1 or popup.1
suffixes. Update package.json and pyproject.toml together. Before choosing a
version inspect the shared ledger, all current candidate records and Ally files.
The packaging script checks ready ancestry and atomically reserves the version
in shared Git refs. A second worktree cannot reserve it. Existing local ZIPs
are never overwritten. A failed build burns its reservation: choose a new
version rather than deleting the record. Do not rename old ZIPs: embedded version
and filename must match. Preserve old artifacts as historical evidence.

Stage to a unique temporary path on the Ally, verify SHA-256, then create the
final /home/deck/Re-Gear-X.Y.Z.zip with an atomic no-clobber operation (for example
hard-link the verified temporary file to the final filename; failure means stop).
Verify the final hash, then remove only the exact temporary file. Do not use
scp directly on an existing destination. Record version, revision, integrated
workstreams, tests and hash in CURRENT_STATE.md. Staging does not authorize install.

## Adoption and limits

Older chat checkouts do not automatically gain this script or AGENTS changes.
They must merge the coordination commit before producing another release.
This guard prevents accidental omission of registered work; review and tests
are still required because ancestry alone cannot prove conflict resolution
preserved behavior. Unregistered work must be discovered through owner handoffs.
The conflicted main checkout must be resolved by its owner, not used as a build base.
