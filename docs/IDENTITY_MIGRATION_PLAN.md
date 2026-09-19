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
| Sudo policy | `/etc/sudoers.d/regear-deploy-plugin` |
| Plugin rollback storage | `.regear-deploy-backups` |
| Browser preference prefix | `regear.` |
| Current journal marker | `Re-Gear shutdown checkpoint: stage=` |

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

The privileged migrator uses a root-owned phase journal outside both directory
names. Every phase records the original device/inode, owner, mode and content
manifest and is fsynced before the next mutation.

1. Create and verify a private evidence backup outside live roots.
2. Rename the complete control directory to `/var/lib/regear/control` on the same
   filesystem and fsync both parents.
3. Rename the complete user directory to `~/.local/share/regear` and fsync its
   parent.
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

## Privilege transition

The installed passwordless rule authorizes only the former helper and package
pattern, so it cannot replace itself. One visible, supervised administrator step
is unavoidable. `scripts/install_regear_identity_migrator.sh` is the narrow
bootstrap for that step. It must be reviewed and copied to the device before use;
Codex never requests or handles the device password. The completed bootstrap
installs only fixed Re-Gear paths and a fixed-argument sudo rule, validates it with
`visudo`, then removes former live authority only after readback succeeds.

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
environment, current inhibitor owner, current helper/sudo policy and absence of
former live paths. Exercise no eGPU or power transition for identity acceptance.
The existing hardware journeys retain their own validation gates.

Documentation impact: multiple
