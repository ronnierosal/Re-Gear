# Focused release batch - 2026-09-06

Release integration owner: UI Redesign. Hardware owner: Ally eGPU - v2.
User is away; no installation, service restart, or device transition is allowed.
G1 was last confirmed attached and powered. No hardware certification is implied.

## Exact baseline

Candidate branch `codex/release-batch-2026-09-06` starts at installed-source
`e765fad4b9283964f43fbcc4185fb6b332cd7333` (0.3.54), explicitly confirmed by
the hardware owner as the preservation baseline. This is not trial approval.
Do not merge later `codex/disconnect-mapping-candidate` work through `a749341`.
Keep the existing dormant trial gates, approvals, recovery and shutdown policy.

Baseline local checks: 1067 backend tests (nine skips), 181 frontend tests,
architecture, compilation, typecheck, build and package checks pass. Rebuilding
produced no committed dist changes. These are local checks, not device tests.

## Existing PR disposition

- PR #1: 16/17 patches already represented; remaining PNG is unused. Current
  assets match installed source. Seven SVG merge conflicts; do not regress them.
- PR #2: adapted into live UI by `cf6e12b` via merged PR #5. Current assets and
  presentation modules match installed source. Old view-model lacks later stale
  evidence handling. Seven SVG and four component conflicts. No missing feature.
- PR #3: broad historical draft, 207 changed files, tip `cc1bab4` predates0.3.54.
  Main reconciliation has eight add/add conflicts. Hold for historical review;
  focused tests do not authorize the whole historical range.
- PR #4: expanded draft at `212bd438`, ten files. 29 targeted fixtures passed.
  Hold for scope reconciliation and issue #24 (default raw diagnostic UUID).
  Its own USB PM document excludes release integration. Do not activate helpers.

Reviews are recorded on the respective GitHub PRs. Nothing was closed as
superseded, merged wholesale, or removed from another checkout.

## Contributions and candidate gate

Offline Play - v1 and Bug Fixing are preparing focused PRs against this exact
baseline. Only this integration owner reserves a version and packages the batch.
Before packaging: review each final diff, require green checks, verify all shared
ready refs and installed ancestry, then rerun the full matrix. Existing ZIPs and
version reservations are immutable. Record exact included commits and ZIP hash.

## Prepared candidate

Focused Offline issues #21/#22 were independently implemented as `fd9e30b`,
reviewed, and merged via PR #25 (`ebde3d0`). No old uncommitted patch was used.
The candidate version commit is `870157dda43d500241703fb5bfcea3f21c5f170d`.
Artifact: `out/Re-Gear-0.3.55.zip`, 449188 bytes, SHA-256:
`992bc2442ab4f0a2679547952d870f0b7f51782e18bb41e6adcec49eb5ab0d0e`.
ZIP CRC and embedded revision/version verified. The shared version was reserved
once; no existing archive was overwritten.

Final local matrix: 196 frontend tests, 1067 backend tests (nine skipped),
typecheck, architecture, compileall, build and package validation pass. The 22
focused Offline tests include eight regressions that fail against the old source.
Backend, main.py, bin and packaging implementation have zero diff from exact
installed e765fad. Only Offline frontend, tests/generated output, docs and version
metadata are included after that baseline. Existing dormant experiments remain
unchanged; this is not approval to use them.

Read-only installed metadata still reports e765fad/0.3.54. Candidate is local
only: no upload, old remote archive deletion, installation, service restart,
device transition, or trial activation. Home/Library same-tile recovery, return
from gameplay, and retry/expiry behavior require supervised device validation.
Issues #21/#22 remain open. Bug Fixing has supplied no ready contribution at
this cutoff; those fixes and issue #24 are not included.
