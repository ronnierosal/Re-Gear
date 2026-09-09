# Full Re-Gear identity transition

Status: requested by Ronnie on 2026-09-09; implementation and device acceptance
remain open. This extends the earlier directory-only cutover. It does not claim
that existing HDM runtime contracts have already changed.

Ronnie confirmed there is no external deployment cohort and requested a one-time
backup and restore during the rename. Do not build indefinite dual-name support.
An absent preference is normal and must not be replaced with an enabled default.

## Verified baseline

- Ally readback: `Re-Gear/build_info.json` reports 0.3.69 at
  `aab13c3834e7ac1e286619495bf9e67eb56e9ee5`.
- A second root-owned `HandheldDockMode/` directory still contains a valid
  manifest named Re-Gear and build 0.3.58 at
  `9301c8c79dd33f96fa9f19d542df36c2b1e907b8`. Loaded instances are unverified.
- Deleted 11 superseded Re-Gear ZIP copies from the two approved staging
  locations after installed-build readback. Retained only
  `/home/deck/Re-Gear-0.3.69.zip`, SHA256
  `e3f0f0ceefa05e01304636e05bd348b8a9e2e2ca01a58a93d125667e6821628f`.
  Local rollback artifacts and unrelated eGPUBridge ZIP were preserved.
- Current passwordless deploy rule still allows the legacy HDM-update protocol.
  It cannot perform a general stopped-plugin identity migration. Do not widen
  the sudo rule or use another privileged command as a workaround.

## Target contracts

| Surface | Target |
| --- | --- |
| Product, manifest, archive and installed directory | Re-Gear (already implemented) |
| npm/Python distribution | re-gear-steamos |
| Python import package | regear |
| User diagnostic command | regear-diagnose |
| Current helper and service names | regear prefix |
| Durable state/config roots | re-gear, through an explicit migration |
| Settings and managed-file ownership | versioned conversion with continuity checks |
| Historical releases, hashes and evidence | retain original identity verbatim |

These target identifiers are the implementation proposal for the user's full
transition request. Existing runtime contracts remain authoritative until each
replacement is implemented, tested and installed together.

## Ordered implementation and acceptance

1. Establish a single installed plugin. Capture the loader's actual discovery
   and loaded-instance state and inventory relevant settings/recovery metadata.
   Follow IDENTITY_CUTOVER.md: native unload, verified backup outside discovery,
   move the exact legacy root, reload one Re-Gear instance and read back version.
   Do not delete the old root while its lifecycle is unknown. Administrator
   execution is required; never request a password in chat.
2. Resolve the existing managed Gamescope path migration in PR216 with its
   owner and the overlapping security-user-writes task. Test recognised old
   renderings, refusal of edited files, retry and rollback before device use.
3. Change distribution/import/CLI contracts in one tested source migration.
   Inventory all imports, entry points, package scripts and CI. Any temporary
   old CLI alias is only an upgrade bridge with explicit removal acceptance.
4. Coordinate installer/security owners before changing helpers, service units,
   signed-update protocol, public-key location or sudo policy. One reviewed
   installation transaction must update all consumers consistently; no broader
   permissions and no simultaneous old/new service writers.
5. Implement state conversion with a schema/versioned manifest: verify owner,
   modes and exact recognised source; reject ambiguous old-plus-new state;
   preserve pending recovery transactions; write atomically; support interrupted
   retry and rollback without overwriting newer runtime state. Inventory settings,
   diagnostics identifiers and managed markers individually rather than applying
   a repository-wide string replacement.
6. Update current docs, support commands and package assertions. Keep historical
   logs, release bytes, validation evidence and quoted identifiers unchanged.
7. Run the complete backend/frontend/build/package gates and final-head CI.
   Separately validate clean install, upgrade, interrupted migration, rollback,
   unique loaded instance, settings continuity and controller navigation on the
   Ally. Naming acceptance exercises no eGPU or power transition.

## Coordination and remaining gates

Owner: `codex-01a087c9-c282-7d81-aff1-0f6274ac8936`, hub task
`regear-full-identity-transition`. Runtime scope must be split or transferred
before edits overlapping security-installer-pr, security-user-writes-pr,
controller-shortcut-bindings or PR216. The existing native menu acceptance stays
open: installed 0.3.69 is verified, successful controller routing is not.

Documentation impact: Wiki

## Offline backup and restore tool

`scripts/regear_settings_backup.py` provides explicit `backup`, `verify`, and
`restore` operations. Stop the plugin before either copying or restoring state.
Use trusted, private directories: this is an operator tool, not a privileged
service accepting untrusted backup uploads. Checksums establish integrity,
not authenticity. Windows uses the parent directory ACL; POSIX backups use 0700
directories and 0600 files. Restore preserves recorded POSIX modes and ownership.

Example command shape (paths are operator-selected, not an installation script):

```text
python3 scripts/regear_settings_backup.py backup SOURCE NEW_PRIVATE_BACKUP
python3 scripts/regear_settings_backup.py verify NEW_PRIVATE_BACKUP
python3 scripts/regear_settings_backup.py restore NEW_PRIVATE_BACKUP ABSENT_DESTINATION
```

The tool refuses existing restore destinations, links, special files, unsafe
paths, corrupt/incomplete manifests and oversized snapshots. Restore validates
all contents before writing, then stages content privately. Final publication
is exclusive but not crash-atomic: leave the plugin stopped through verification.
An interrupted publication requires inspection of the partial target; it is not
silently overwritten on retry. The source and backup remain unchanged.

Inventory each actual directory separately; record absent directories rather
than creating invented settings. Observed/in-scope locations are:

| Location | Treatment |
| --- | --- |
| `/var/lib/handheld-dock-mode` | Root-only state: inventory and back up privately; migration must distinguish preferences, recovery records, keys and live authorizations |
| `/home/deck/.local/share/handheld-dock-mode` | Saved presentation and trial state observed; old trial authorization is not a setting to reactivate |
| Decky `settings/HandheldDockMode` and `settings/Re-Gear` | Both directories exist; reconcile explicitly, never merge by modification time |
| Decky `data/HandheldDockMode` and `data/Re-Gear` | Both directories exist; same conflict rule |
| Frontend local storage | Menu shortcut already uses `regear.menu-shortcut.v1`; separately migrate the two legacy sleep-warning keys |

Preference code supports `automatic-dock.json`, `auto-tdp.json`,
`auto-tdp-preferences.json` and `game-close-preferences.json`. File existence in
the protected directory has not been established. SSH cannot read it without
administrator execution; no actual complete device backup is claimed yet.

The source migration must not restore stale approval tokens, filter handles or
process leases as active authority. Recovery journals remain available for
reconciliation. No general-purpose restore is automatically invoked on startup.
