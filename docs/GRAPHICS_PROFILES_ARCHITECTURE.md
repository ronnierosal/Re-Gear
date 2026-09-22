# Automatic per-game graphics profiles — milestone 1 architecture

Status: initial implementation owner draft (Claude, cloud session). Scope is the
first adapter milestone only. Nothing here authorizes display, GPU, Gamescope,
TDP or controller mutation, and nothing here is wired into the Command Center.

## Problem

A player's preferred graphics settings for a game are not the same portable as
they are on a TV. Today they change them by hand, twice, every time they dock.
Re-Gear should carry a per-game graphics profile across a mode change.

A game's configuration file is the player's data. The only acceptable failure
mode is "Re-Gear changed nothing", never "Re-Gear left the file broken" and
never "the game will not start".

## Boundaries this milestone commits to

- **Managed keys only.** A profile names the exact keys it owns. Everything else
  in the file — unrelated settings, ordering, comments, unknown sections,
  trailing whitespace, line endings — survives a round trip byte-for-byte.
- **Unknown schema means Advisor.** If the file's format, or a key inside it, is
  not one this milestone understands, the outcome is advice to the player, not a
  write. There is no "best effort" write path.
- **Never while the game is running.** Application requires an explicit
  not-running observation supplied by the caller. Absence of evidence is not
  evidence of absence: an unknown run state refuses.
- **Never blocks a launch.** Every apply path returns an outcome value. The
  service raises nothing to its caller for a configuration failure; a failed
  apply leaves the last good bytes in place and reports `advisor` or `failed`.
- **No real game configuration is touched in this milestone.** Discovery is
  rooted at an explicitly supplied Steam root. There is no default of
  `~/.steam`; a path resolving outside the supplied root is refused.

## Components

| Layer | Module | Responsibility |
| --- | --- | --- |
| domain (pure) | `domain/graphics_profiles.py` | Profile, managed key, mode binding, support tier, and the pure planner that turns (document, profile) into a change plan |
| domain (pure) | `domain/graphics_config_format.py` | The one text-configuration adapter: parse/render a key–value document with full fidelity, plus the adapter registry |
| delivery (I/O) | `delivery/graphics_config_locator.py` | Steam library discovery, AppID → install dir, Proton prefix vs native configuration path |
| delivery (I/O) | `delivery/graphics_backup.py` | Bounded, pruned, restorable backups |
| delivery (I/O) | `delivery/graphics_config_store.py` | Atomic validated writes and verified read-back |
| delivery (I/O) | `delivery/graphics_profile_service.py` | The sequence: discover → read → validate → backup → apply → verify → restore |

### Why the format adapter is in `domain`

`docs/AGENTS.md` keeps `domain` free of filesystem, subprocess, network and OS
calls. Parsing and rendering text is none of those. Keeping the adapter pure is
what makes "unrelated settings are preserved" a property provable by a pure
round-trip test rather than by a filesystem test, so the adapter lives in
`domain` and every byte that reaches disk is produced by `delivery`.

### Why writes live in `delivery`

`scripts/check_architecture.py` forbids filesystem writers in
`backend/regear/adapters/`, with two narrowly reviewed device-writer exemptions.
Graphics-profile writes are ordinary state writes and belong in `delivery`,
alongside the existing atomic stores (`relaunch_intent_store`,
`auto_tdp_preferences`), and reuse their idiom: write a unique temporary file in
the target directory, `fsync` it, `os.replace` it into place, `fsync` the
directory.

## The apply sequence

```
discover  locate the configuration for AppID + mode           (read-only)
read      load bytes, refuse symlinks and oversized files     (read-only)
validate  parse with a registered adapter; unknown → advisor  (pure)
backup    bounded copy of the exact current bytes             (write, new file)
apply     render only managed-key changes, atomic replace     (write, replace)
verify    re-read, re-parse, assert managed keys are the
          requested values and the unmanaged remainder is
          unchanged; on mismatch, restore the backup          (read + rollback)
```

`restore` is independently callable and restores the exact backed-up bytes.
Byte-for-byte equality is the acceptance criterion for restore; the semantic
comparison exists only as evidence for documents whose renderer is known to
normalize, and this milestone's adapter never normalizes, so restore is
byte-exact.

## Backups

Bounded per (AppID, configuration identity): newest `MAX_BACKUPS` retained,
older pruned oldest-first. Each backup records the source path, the mode that
was about to be applied, a monotonic sequence and the SHA-256 of the bytes. The
digest is what makes "restored byte-for-byte" checkable after the fact rather
than assumed.

## Out of scope for this milestone

eGPU, Gamescope, controller, Auto TDP and Command Center code are untouched. No
UI, no RPC, no automatic triggering on a mode change, no second configuration
format, no registry-backed profile catalog, no live game detection — the run
state is an input, not something this code observes.

## Provenance

No third-party implementation code was read, copied or adapted. The Steam
on-disk layout used here (`steamapps/libraryfolders.vdf`,
`steamapps/appmanifest_<appid>.acf`, `steamapps/compatdata/<appid>/pfx`) is
publicly documented filesystem structure, not code. The atomic-write and
bounded-store idioms are taken from this repository's own existing modules.
