# Re-Gear directory cutover implementation

Repository scope: new Decky ZIPs have the single root `Re-Gear/`; new deployment
and support defaults use `/home/deck/homebrew/plugins/Re-Gear`. The manifest and
frontend already say Re-Gear. This is not an installed or hardware-tested result.
See [the migration plan](IDENTITY_MIGRATION_PLAN.md) for the decision and gates.

## Changed contracts

- `build_plugin.py`: archive root; public `Re-Gear-X.Y.Z.zip` naming is unchanged.
- `prepare_release_candidate.py`: new root only; rejects mixed-root archives.
- `stage_decky_update.py` and `ally_deploy_helper.py`: new root and matching
  private staging/signature protocol `Re-Gear-update-VERSION-REVISION.zip[.sig]`.
  The root-owned helper must be updated separately before using this protocol.
- `ally_deploy_helper.py` and `deploy_to_ally.ps1`: fixed new target and
  backup name; refuse any legacy root (including a dangling symlink) before local
  plugin changes. Neither automatically migrates the old tree. New plus legacy
  also refuses; an operator must establish authority, never choose by timestamp.
- `community_report.py` and `remote_capture_payload.py`: new installed-root
  defaults, with no silent legacy fallback. Community reporting retains its
  existing explicit-root option for reviewed historical/test diagnostics.
- `verify_validation_artifact.py`: read-only historical evidence verification
  accepts exactly one root, Re-Gear or HandheldDockMode, preserving old artifact
  checks. This does not make old artifacts deployable through the new tools.

The general native Decky installer is external software and is not modified by
this patch. Staging alone neither inspects nor migrates an installed plugin.
Do not use the native installer as a shortcut around supervised legacy cutover.

## Retained identifiers

Re-Gear is the current product and implementation identity. An old name survives
below only for a stated reason with removal criteria. "It would enlarge the
change" is not a reason; it is a schedule. Each group says what breaks and what
would have to be true to rename it.

### Addresses on devices we have already shipped to

These are not the product's name. They are the identity of something that exists
on a player's disk, and renaming them here does not rename it there — it orphans
it. Issue #167 is what that failure looks like. Each has an assertion and a
per-item reason in `tests/test_retained_legacy_identity.py`.

- `90-handheld-dock-mode.conf` — the managed Gamescope drop-in filename on every
  install. Renaming leaves the old file in place, unmanaged and still on `PATH`.
- `/var/lib/handheld-dock-mode` — root-owned control state and the deployment
  public key the signed installer verifies against.
- `HDM_STATE_ROOT` and `share/handheld-dock-mode` — rendered into the drop-in, so
  they are bytes on disk as well as names.
- `Handheld Dock Mode` as the sleep inhibitor `who` — what a live systemd lock
  reports and an operator matches against recorded evidence.
- `HandheldDockMode` as the installer's `LEGACY_NAME` — if it stops recognising
  the old tree it stops refusing, and both trees sit side by side.
- `hdm.hideAttachedEgpuSleepWarning` and its legacy partner — localStorage keys
  holding a player's own dismissal.
- `.hdm-deploy-backups`, existing config paths, recovery journals and the deploy
  verification key — existing rollback authority.

Removal criteria, all of them: a migration that recognises the old rendering,
repairs or moves it, and can roll back; regression coverage for an old install
and old data; and supervised validation on a supported profile. Until then, do
not clear or rename. Dated records and old ZIPs keep their original paths, names,
bytes and checksums regardless.

### Repository identities now changed

Current source uses `backend/regear/` and `regear` Python imports. Package contents,
entry points and installer/package checks move together; there is no second
`hdm` implementation package. Distribution metadata is `re-gear-steamos` and
the Python project console command is `regear-diagnose`. Decky still does not
install that command globally.

New support exports use `Re-Gear-support-<timestamp>.json`; support-version data
uses `regear`. The dormant submission adapter uses `X-Re-Gear-Content-SHA256`
and Re-Gear report IDs. These names do not imply a deployed submission service.
Old published archives and existing exported files retain their original bytes.

See [September 10 completion](REBRAND_COMPLETION_2026-09-10.md) for scope and
remaining device gates. The managed-drop-in migration primitive was already
present in released source, but the application preparation preflight rejected
its `managed_dropin_superseded` status. The companion application change addresses
that guarded path; issue #167 still requires supervised installed verification.

`HDM shutdown checkpoint: stage=` stays until both sides move together: it is
emitted to journald and parsed by a regex in
`scripts/capture_shutdown_evidence.py`, and renaming one side fails silently.

## Loader source evidence

Upstream Decky source at
[`1ea69d315a49376e32f1fba46ffa7d028eed8046`](https://github.com/SteamDeckHomebrew/decky-loader/tree/1ea69d315a49376e32f1fba46ffa7d028eed8046),
inspected 2026-09-08, extracts the ZIP under the plugin parent and discovers the
manifest name (`backend/decky_loader/browser.py`). Its plugin constructor joins
the discovered directory and creates `settings/<directory>`, `data/<directory>`
and `logs/<directory>` under its configured home (`plugin/plugin.py`). A hyphen
in the directory does not enter a Python module import in these paths.
This establishes source compatibility, not the installed loader version or
runtime proof. This repository does not currently consume Decky's per-plugin
settings/data environment paths; still inspect those locations before cutover.

## Controlled supervised test-install procedure

This procedure is a checklist for a separate device session, not an executable
migration script or authorization to act on hardware.

1. Identify the exact installed loader version, old plugin revision/hash, both
   possible plugin paths and their symlink status. Record whether neither, old
   only, new only, both or unknown is present. Both/unknown blocks deployment.
   Review pending recovery transactions and managed session wrappers: unresolved
   state or wrappers referring to the old plugin tree blocks the cutover until
   the hardware owner resolves them through the existing supervised mechanism.
2. Prepare a unique private backup outside the plugin discovery parent. Preserve
   the exact old tree with modes/ownership and a checksum manifest. Inventory
   relevant state under `/var/lib/handheld-dock-mode`, existing configuration,
   and Decky's directory-specific settings/data/logs. Record what exists and its
   ownership; do not indiscriminately copy or clear state. No new power or eGPU
   operation is part of validating a name change.
3. In the separately authorized session, stop/unload the old plugin through the
   verified loader lifecycle and verify it stopped. Move the exact verified old
   plugin tree out of discovery into the prepared unique backup. Keep the
   persistent state untouched. Do not create a symlink alias or leave two roots.
4. Install the exact verified new artifact through the reviewed deployment
   workflow. The helper protocol change requires reviewed helper deployment
   first; do not loosen its sudo/signature policy. Verify one new instance,
   revision, visible UI, read-only diagnostics, settings continuity, recovery
   state, and unload/reload behavior. Record the actual device evidence.
5. On failure, stop the new instance and verify it stopped. Preserve its tree and
   failure evidence outside discovery; restore the exact old tree and ownership
   from the verified backup. Restore only state changes established in the
   migration manifest, and only when reconciled against fresh recovery state.
   Never overwrite unknown runtime changes with a stale snapshot. Verify one old
   instance and read back its revision/state. If any step is uncertain, stop for
   supervised recovery; do not delete evidence or guess an authoritative copy.

A fresh installation needs the same unique-instance/readback checks. The normal
helper's mocked new-identity update rollback is separate from this manual legacy
rollback. Repository tests cannot certify the controlled device migration.
