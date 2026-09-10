# Re-Gear installed identity cutover

Status: repository cutover implemented in a **separate task, worktree and PR**
on 2026-09-08. See [implementation inventory and procedure](IDENTITY_CUTOVER.md).
No installed system was changed. Hardware migration and rollback validation
remain separate supervised steps.

## Decision and scope

Use **`Re-Gear`** as the target installed Decky directory and archive root,
consistent with the pinned upstream loader source inspected in the
implementation inventory; the installed loader still needs supervised checks. The visible manifest/UI label is already Re-Gear. This is a
clean identity cutover, not an ongoing dual-name compatibility layer.

Ronnie reports legacy installs are limited to his own recent test device(s).
There is no known community legacy-install cohort to support. GitHub has public
v0.3.57/v0.3.58 development-candidate releases, so retain those immutable artifacts
and document the cutover clearly; their existence alone is not evidence of other
users or a reason to build indefinite migration compatibility. Decky Store/channel
registration is separate from GitHub publication and has not been established.

The controlled test-install upgrade/rollback is necessary even without a store
listing. A new directory must not leave two active plugins, duplicate observers
or power writers, or lose safety/recovery state.

## Contract inventory for implementation

Confirm this search inventory against the implementation base; it is not an
instruction to replace every matching string.

| Contract | Starting points | Required decision/check |
|---|---|---|
| Manifest, visible identity, loader lifecycle | `plugin.json`, `src/branding.ts`, `main.py`, `tests/test_decky_contract.py` | Prove loader discovery and unique runtime identity; distinguish visible label from folder |
| Package layout and candidate metadata | `scripts/build_plugin.py`, `scripts/prepare_release_candidate.py`, `scripts/verify_validation_artifact.py` | New root, manifests/checksums and consistent validation; reject mixed roots |
| Native Decky staging and deployment | `scripts/stage_decky_update.py`, `scripts/deploy_to_ally.ps1`, `scripts/ally_deploy_helper.py`, `scripts/install_ally_deploy_helper.sh` | Exact target, legacy detection and safe stopped-plugin sequence; no second live instance |
| Read-only capture and support | `scripts/remote_capture_payload.py`, `scripts/community_report.py` | Correct new root; explicit legacy-test diagnosis where needed; no ambiguous first-match fallback |
| Recovery/state ownership | `backend/hdm/delivery/runtime_state.py`, `gamescope_integration.py`, `main.py` | Inventory actual settings/journals/helpers/managed-file ownership before changing paths |
| Distribution and import identifiers | `package.json`, `pyproject.toml`, Python `hdm`, helper names and stored keys | Change only contracts required for the installed-identity cutover; explicitly list retained compatibility identifiers and reasons |
| Tests and CI | Decky/package, artifact, release-candidate, staging, deployment, support/capture and runtime-state tests; `.github/workflows/ci.yml` | Assertions cover new identity, no mixed package, clean install, controlled upgrade and rollback |
| Documentation and old artifacts | BRANDING, RELEASE_PIPELINE, deployment/support instructions and dated records | Update current procedures after implementation; keep historical paths, ZIP bytes, hashes and evidence intact |

## Clean-cutover behavior

1. Inventory the target installation without changing it. Classify new only,
   legacy only, neither, both, and ambiguous/corrupt state. Both identities present
   must stop normal upgrade handling; never guess which is authoritative.
2. New packages install only the new root. Do not ship two roots, a silent alias,
   or a long-lived dual-writer compatibility mode.
3. Handle Ronnie's legacy test install through a narrowly documented, explicitly
   supervised transition. Record exact source/artifact/current identity and any
   recovery state before the loader stops the old instance.
4. Preserve settings and safety journals using a reviewed schema/ownership
   decision. No blanket state-directory copy or clearing a pending transaction.
   Unknown or unfinished recovery state blocks cutover until safely resolved.
5. Verify old instance stopped and new instance uniquely loaded before success.
   Any failed verification uses the prepared rollback; no simultaneous instances.

## Backup and rollback for the test device

Before a separately authorized device step, preserve a checksum-verified old
plugin package or bounded copy, the exact relevant settings/journals with modes
and ownership, and a manifest of what the migration may change. Keep backups
private and outside both plugin discovery directories; never overwrite them.

Rollback stops the new instance through the native lifecycle, restores the exact
old package/state and ownership from the manifest, then verifies one old instance
and expected state. Do not reverse unknown runtime writes by guessing, discard
recovery evidence, delete unrelated files or rewrite old releases. If restoration
cannot be verified, stop and report the precise state for supervised recovery.

## Verification and acceptance

Repository acceptance requires targeted migration/package/deploy/support tests
plus the full relevant backend/frontend/build/package matrix and final-head CI.
Test neither/legacy/new/both roots; malformed or mixed ZIP roots; partial staging,
interruption and retry; stale/missing backup; conflicting state; and rollback.
Verify old published artifacts remain byte-identical and no broad legacy-string
replacement changed historical evidence or unrelated Python/state contracts.

Hardware acceptance is separate and must use an exact build and supervised
baseline under DEPLOYMENT_VALIDATION. Prove a fresh new-identity installation,
then one controlled legacy-test upgrade and rollback: unique loader lifecycle,
settings continuity, recovery-state correctness, build readback, diagnostics,
controller-visible UI and clean unload/restart. Exercise no eGPU transition or
power-control action merely to validate naming. Installation is not authorized
by successful repository tests.

The focused implementation PR must list changed and retained identities,
backup/rollback instructions, tests, exact source revision, and unperformed
hardware checks. Reconcile current documentation as that PR lands. Store/channel
publication, release artifacts and physical migration keep their separate gates.
