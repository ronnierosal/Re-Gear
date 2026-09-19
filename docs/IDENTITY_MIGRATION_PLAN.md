# Re-Gear full installed identity migration

Status: implementation in progress. The current plugin, archive, npm package and
Python namespace already use Re-Gear. This migration finishes the installed
runtime identity without discarding recovery authority left by older builds.
Repository tests do not establish that the device migration has run.

## Target identity

| Surface | Current target |
| --- | --- |
| Root-owned control state | `/var/lib/regear/control` |
| Privileged deploy authority | `/var/lib/regear/deploy` |
| Per-user state | `~/.local/share/regear` |
| Gamescope drop-in | `90-regear.conf` |
| Gamescope environment | `REGEAR_STATE_ROOT` |
| Managed-file and inhibitor owner | `Re-Gear` |
| Privileged deploy helper | `/var/lib/regear/deploy/regear-deploy-plugin` |
| Deploy public key | `/var/lib/regear/deploy/deploy-public-key.pem` |
| Sudo policy | Canonical `/etc/sudoers.d/regear-deploy-plugin` plus an identical lexically-final SteamOS precedence copy |
| Plugin rollback storage | `.regear-deploy-backups` |
| Former deploy backups/staging | Whole-directory root archive under `/var/lib/regear/deploy` |
| Browser preference prefix | `regear.` |
| Current journal marker | `Re-Gear shutdown checkpoint: stage=` |
| Former Decky settings/data/log directories | Whole-directory archives under `~/.local/share/regear-decky-*-archive` |

`/var/lib/regear/control` is deliberately below the existing Re-Gear authority
root. Other current components already use `/var/lib/regear`; moving the former
control directory directly onto that nonempty directory would merge unrelated
authority. Deploy credentials are separated into `/var/lib/regear/deploy`.
The control migration renames the whole directory as one filesystem object and
never copies or rewrites individual safety records.

The migration release has bounded readers for exact former identifiers. Those
readers are migration input, not active installed identity. They remain only
through rollback and device acceptance. A successful installed cutover has no
former live path, drop-in, helper, environment entry, inhibitor owner, or writer.
Historical releases, hashes, evidence and quoted logs retain their original bytes.

## Safety boundary

The cutover is an offline naming operation. It performs no display, eGPU, sleep,
shutdown, power, authorization, or recovery action. Before changing files it must:

1. stop the Decky plugin loader and prove the Re-Gear backend is absent;
2. prove Gamescope's game state is idle and known before the separately supervised
   session restart needed to replace its inherited environment;
3. acquire the runtime admission, claim, transition and TDP locks without waiting;
4. reject links, special files, unsafe owners or modes, cross-filesystem moves,
   edited managed files, and old-plus-new ambiguity;
5. reject any unfinished operation, including an active transition, whole-dock
   claim, reset marker, unconsumed dock-power intent, active portable Vulkan trial,
   or non-idle TDP session.

Completed audit and recovery history moves byte-for-byte with the directory. The
migrator never deletes a claim to make preflight pass. An unfinished operation is
reconciled by its owning runtime path before another migration attempt.

## Transaction and rollback

The privileged migrator uses root-owned phase journals outside every directory
being moved. The journal records fixed planned paths and completed phases and is
fsynced before the next mutation. Before each whole-directory rename, the
migrator revalidates type, ownership, mode, bounded contents, quiescent lifecycle
state and the same-filesystem destination. It does not claim to create a separate
content backup of the control state.

1. Rename the complete control directory to `/var/lib/regear/control` on the same
   filesystem and fsync both parents.
2. Rename the complete user directory to `~/.local/share/regear` and fsync its
   parent.
3. Move former Decky directory-keyed settings, data and logs whole into neutral
   Re-Gear archive paths. Existing current Decky directories are never merged.
4. Replace the exact recognized Gamescope drop-in, deploy helper, public key and
   sudo policy as one reviewed installation transaction.
5. Publish the matching Re-Gear plugin, reload the user unit configuration, and
   restart Gamescope only through the existing idle-game supervised path.
6. Start the plugin loader and verify one Re-Gear instance, exact revision, new
   runtime paths, state continuity, deploy signature verification, and the live
   Gamescope process environment.

Before the new runtime starts, rollback reverses exact renames and managed-file
changes. After it starts, rollback first stops it and moves the *current* new
directories back; it never restores a stale snapshot over newer recovery writes.
Unknown phase, inode drift, unexpected content or rollback divergence stops with
the journal and all evidence intact for operator review.

If a native Decky install starts the current runtime before this migration, it
can create a second `/var/lib/regear/control`. The migrator still rejects that
ambiguity by default. Its explicit `reconcile-runtime` recovery is admitted only
while the loader and Gamescope are offline, when the former tree is quiescent
and the current tree contains exactly two empty lock files plus a byte-identical
`portable-audio.json`. It journals a same-filesystem whole-tree rename to
`/var/lib/regear/pre-migration-control-v1`, fsyncs the parent, and retains that
tree as evidence. It never merges or deletes either authority.

Rollback has one fixed dependency order. While the current deploy authority is
still installed, run `/var/lib/regear/deploy/regear-migrate-identity rollback`
and verify that the combined, directory and Gamescope drop-in journals are
`rolled_back`, the current drop-in is absent, and `/var/lib/regear/control` is
absent. Only then run the administrator bootstrap with `rollback` to restore the
former helper, key, sudo rule and archived private deployment directories. The
bootstrap refuses the reverse order because removing the current migrator first
would strand the only reviewed rollback path for control and Gamescope state.

## Privilege transition

The installed passwordless rule authorizes only the former helper and package
pattern, so it cannot replace itself. One visible, supervised administrator step
is unavoidable. `scripts/install_regear_identity_migrator.sh` is the narrow
bootstrap for that step. It must be reviewed and copied to the device before use;
Codex never requests or handles the device password. The completed bootstrap
snapshots signed helper and migrator inputs into root-only storage, verifies both
with the already trusted deploy public key, and uses a fsynced phase marker so an
interrupted install or rollback can resume. It installs only fixed Re-Gear paths
and fixed-argument sudo rules, validates them with `visudo`, then removes former
live authority only after direct and Deck-user readback succeeds.

When the private key matching the former trusted public key is irrecoverably
lost, `install-rotated <new-public-key-sha256>` is the separately approved
credential-recovery mode. It snapshots the former authority first, pins the
operator-supplied fingerprint, verifies the helper and migrator against the
copied new key, records the immutable trust mode in the root-only transaction,
and then follows the same publication, readback, retirement and rollback path.
The new private key remains off-device and outside the repository. Ordinary
`install` keeps the former-key trust chain unchanged.

SteamOS also supplies a later general password-required rule. The bootstrap
therefore publishes the same fixed-command policy at the canonical path and at
`/etc/sudoers.d/zzzzzzzz-regear-deploy-plugin`, which sorts after the platform
rule. Both copies must match the root-only snapshot, pass `visudo`, and are
verified and removed together during rollback; the later copy grants no
additional command surface.

The Gamescope phase remains prepared until a separately supervised restart proves
the running process inherited `REGEAR_STATE_ROOT`. Removing a file is not proof
that the old environment left the running process.

## Verification

Repository acceptance covers old-only, new-only, neither and both-root fixtures;
links and ownership failures; every active-operation blocker; byte and metadata
continuity; interrupted phases; idempotent current state; rollback before and
after new-runtime writes; managed drop-in exact matching; helper argument limits;
browser and journal compatibility readers; and post-commit absence of former live
identifiers. Run architecture, golden behavior, complete backend/frontend,
typecheck, compile, build and package checks on the combined head.

Installed acceptance is supervised and separate. Capture preflight, migration
journal, exact installed build, unique process/readback, current Gamescope
environment, current inhibitor owner, current helper/sudo policy, archived former
Decky directories and absence of former live paths. The migrator's `status`
output must report the restarted Gamescope environment as `current`; file-level
readiness alone is insufficient. Exercise no eGPU or power transition for
identity acceptance.
The existing hardware journeys retain their own validation gates.

Documentation impact: multiple
