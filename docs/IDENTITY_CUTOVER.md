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

## Full installed identity migration

Current source writes the installed identities defined in
[the migration plan](IDENTITY_MIGRATION_PLAN.md): root control state under
`/var/lib/regear/control`, deploy authority under `/var/lib/regear/deploy`, user
state under `~/.local/share/regear`, and the Re-Gear Gamescope environment,
managed marker, inhibitor and diagnostic writer.

The former identifiers are accepted only by exact migration, rollback and
historical-artifact readers. They are not alternate live paths. The privileged
migration:

- refuses old-plus-new ambiguity, links, unsafe metadata and active lifecycle
  state;
- preserves recovery and completed-trial records byte-for-byte by moving whole
  directories on the same filesystem;
- journals each phase outside both names and holds lifecycle locks through
  validation, rename and fsync;
- moves the current directory back during rollback so newer recovery writes are
  never replaced by a stale snapshot;
- replaces helper, public key and sudo policy through one visible administrator
  bootstrap with signed snapshots, a resumable phase journal, exact backups and
  readback;
- treats the Gamescope file/environment cutover as prepared until a supervised
  idle-session restart proves the running process inherited the new environment.

The migration release retains exact former literals inside the dedicated
migration module and rollback readers. Removing those readers is a later cleanup
after installed acceptance and the rollback support window. Historical ZIPs,
reports, hashes, logs and dated evidence keep their original bytes indefinitely.

Fresh source and new packages do not create former paths, markers, browser keys,
helper names or journal messages. Normal deployment detects either a former
plugin root or former root-owned control state and refuses to start the new
runtime before migration. Former Decky directory-keyed settings, data and logs
are moved whole to neutral Re-Gear archive paths; current directories are never
merged with them.
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
