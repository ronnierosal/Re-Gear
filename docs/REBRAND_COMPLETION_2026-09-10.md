# Re-Gear repository identity completion — September 10, 2026

This records the namespace change being prepared from `7d9756a`. It is a source
inventory, not evidence of a new release, installation, Wiki publication or
hardware validation. Final checks and integration revisions belong in the owning
task and PR. See [cutover procedure](IDENTITY_CUTOVER.md) before device work.

## Current source identity

- Product, Decky manifest and new archive/install root: `Re-Gear`.
- npm and Python distribution metadata: `re-gear-steamos`.
- Python implementation: `backend/regear`, imported as `regear`; source CLI:
  `PYTHONPATH=backend python -m regear.cli`. Installing the Python project creates
  `regear-diagnose`; installing a Decky ZIP does not create a global command.
- New support export prefix: `Re-Gear-support-`; support-version key: `regear`.
  The dormant submission protocol uses Re-Gear header/report names. No endpoint
  or support upload is activated by renaming these contracts.
- The read-only community-report helper also recognizes the `hdm` namespace in
  previously published installations. It refuses an ambiguous mixed namespace;
  new archives contain only `regear`.

The package move must include imports, launcher code, package validation,
installer checks, tests and current documentation. Historical evidence and
revision-pinned source links continue to identify the original `hdm` paths.
Zero old-name matches is not the acceptance criterion.

## Retained compatibility identities

| Identity | Why it remains | Requirement before changing it |
| --- | --- | --- |
| `HandheldDockMode` legacy plugin root recognition | Detects an old installation and prevents two active trees | Controlled upgrade/rollback and unique loader-instance proof |
| `90-handheld-dock-mode.conf` and its managed marker | Identifies an existing Gamescope drop-in; changing only the name strands active configuration | Recognize exact old bytes, guarded migration, rollback and installed verification |
| `HDM_STATE_ROOT`, `share/handheld-dock-mode`, `/var/lib/handheld-dock-mode` | Existing user/root state, recovery journals and deployment-key locations | Preserve ownership and pending recovery authority throughout migration |
| `.hdm-deploy-backups` and existing helper/config names | Existing rollback and signed-deployment authority | Manifest-backed migration and verified restoration of old data |
| `hdm.hideAttachedEgpuSleepWarning` and legacy preference keys | Preserve the player's stored choice | Read-old/write-new migration with preference regression coverage |
| `Handheld Dock Mode` inhibitor identity and `HDM shutdown checkpoint: stage=` | Correlate live systemd/journal evidence with existing consumers | Move producer and readers together, retaining interpretation of old evidence |
| Old ZIPs, exported reports, dated notes and pinned source URLs | Immutable provenance and historical evidence | Preserve; a namespace change does not rewrite past artifacts |
| `hdm_support_bundle` manifest kind, legacy `hdm` version input and `HDM-` report IDs | Interpret already exported reports and legacy responses | Version the report schema and keep old reports readable before removing compatibility |
| Legacy names in tests and archived HTML previews | Exercise old-install compatibility or preserve historical fixtures | Update only when the fixture's contract changes; these are not current product labels |

The full per-item contract remains in [identity cutover](IDENTITY_CUTOVER.md).
Retaining these bytes does not retain the former product identity or a parallel
Python implementation.

## Managed Gamescope migration and device acceptance

PR #216 added recognition and migration of an exact prior managed drop-in, and
that code is contained in `v0.3.73`. The application preparation service still
rejected its `managed_dropin_superseded` status before approval could be issued.
The companion application fix in this change addresses that gate with migration
and rollback checks; it does not authorize automatic startup repair or establish
that an installed device was repaired.

Rollback restores the exact prior managed bytes after an in-process failure and
refuses a concurrently edited file. The existing remove/publish sequence is not
crash-atomic; a process or power failure between those operations remains outside
that recovery guarantee.

Keep #167 open for supervised installed migration acceptance. Verify one plugin
instance, correct effective drop-in, settings/recovery continuity, package identity
and rollback using the [deployment gates](DEPLOYMENT_VALIDATION.md). Physical
unplug, display switching and power-control certification are separate claims.

The predecessor backup utility at `5c21fbc` is preserved as a separate deferred
tool. It is not integrated or designated as the migration procedure by this
namespace change. Preserve its work and existing backup artifacts.

Documentation impact: multiple.
