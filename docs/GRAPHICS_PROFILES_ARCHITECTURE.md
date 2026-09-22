# Automatic per-game graphics profiles — milestone 1 architecture

Status: revision 2, after the primary review on PR #375. Canonical assignment
and acceptance criteria are issue #374. Scope is the first adapter milestone
only. Nothing here authorizes display, GPU, Gamescope, TDP or controller
mutation, and nothing here is wired into the Command Center. Source research
and its gaps are in [GRAPHICS PROFILES RESEARCH](GRAPHICS_PROFILES_RESEARCH.md).

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
- **Three support levels, and evidence decides.** 0 Unknown: the file's format,
  schema or version is not one an adapter was written against, so Re-Gear says
  nothing about its keys. 1 Advisor: the layout is recognised but some value is
  not writable, so the player is told what to change. 2 Managed: schema, version
  and every current value are recognised. Only Managed writes.
- **The player's edits win.** Every managed write records the digest of exactly
  the bytes it left behind. If the file no longer matches, someone else changed
  it, and their newer choice is kept — on apply and on restore alike. There is
  no silent rebaseline, and a file Re-Gear cannot prove it wrote is treated as
  the player's.
- **Restore means "my settings", not "the last profile".** The first capture for
  a target is a pinned baseline that pruning never evicts.
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
| domain (pure) | `domain/graphics_profiles.py` | Versioned profile, managed key, mode binding, support tier, and the pure planner |
| domain (pure) | `domain/graphics_config_format.py` | The one text-configuration adapter: parse/render a key–value document with full fidelity, plus the adapter registry |
| domain (pure) | `domain/graphics_schema.py` | Schema identity, version and current-value evidence; the structural signature recorded with each write |
| domain (pure) | `domain/graphics_game_adapter.py` | Semantic experience target → one game's own keys, from a declared table; and the resolver that turns an observed mode into a profile, or into nothing |
| delivery (I/O) | `delivery/graphics_config_locator.py` | Steam library discovery, AppID → install dir, Proton prefix vs native path, manifest contradiction and ambiguity |
| delivery (I/O) | `delivery/graphics_backup.py` | Bounded rotating backups plus a pinned, never-pruned baseline |
| delivery (I/O) | `delivery/graphics_management_state.py` | Durable provenance: the digest Re-Gear last wrote, the baseline, the schema and profile versions |
| delivery (I/O) | `delivery/graphics_config_store.py` | Atomic validated writes and verified read-back |
| delivery (I/O) | `delivery/graphics_profile_service.py` | The sequence, the conflict policy, Stop Managing, Restore My Settings and the launch boundary |

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
discover  locate the configuration for AppID + mode; refuse a
          contradictory or ambiguous manifest                 (read-only)
read      load bytes, refuse symlinks and oversized files     (read-only)
validate  parse, then assess schema id, version, required
          keys and CURRENT values; anything short → Unknown   (pure)
prove     compare the bytes against the digest Re-Gear last
          wrote; a mismatch is the player's edit → conflict   (read-only)
backup    bounded copy, pinning the first as the baseline     (write, new file)
apply     render only managed-key changes, atomic replace     (write, replace)
verify    re-read, re-parse, assert managed keys are the
          requested values and the unmanaged remainder is
          unchanged; on mismatch, restore the backup          (read + rollback)
record    persist the digest just written, with the schema
          and profile versions it was written under           (write, state)
```

A rollback is itself guarded: before writing a backup back, the service checks
that the bytes on disk are still the ones this attempt wrote. If something else
changed the file in between, a stale backup would destroy that change, so the
failure is reported without a rollback instead.

`restore` restores the pinned baseline by default and refuses when the file
holds edits Re-Gear did not make, unless the caller passes the explicit flag
that says the player chose to discard them. `stop_managing` ends Re-Gear's
authorship without touching the file and without discarding the baseline: opt
out and restore are separate acts, and neither is a blind overwrite.

## The launch boundary

`prepare_for_launch` is the caller-visible entry point and returns ALLOWED
always — for every apply outcome, every filesystem failure, and even an
unexpected exception from an injected collaborator. That contract is tested
through the entry point with real failures injected, not asserted from a
docstring. There is no production launch hook, no polling and no process
control in this milestone.

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

## Semantic profiles, and what is never invented

A profile is written in the vocabulary of `domain/mode_profiles.py` — an
experience target per placement — and a game adapter translates that into the
game's own keys using a table its author declared. Nothing derives, tunes or
measures a value. An adapter with no entry for a placement offers no profile
for it, which is exactly how Boosted Handheld behaves until somebody declares
one; the vocabulary existing is not permission to guess a setting, because a
guessed "optimal" value is a claim about hardware Re-Gear has not measured.

The resolver consumes a stable observed mode supplied by whoever already owns
mode observation. It reads no hardware, and an unrecognised placement selects
nothing at all.

## Out of scope for this milestone

eGPU, Gamescope, controller, Auto TDP and Command Center code are untouched. No
UI, no RPC, no automatic triggering on a mode change, no second configuration
format, no registry-backed profile catalog, no live game detection — the run
state is an input, not something this code observes. Steam Cloud ordering
remains an explicit unresolved production gate: filesystem atomicity cannot
prove cloud or game cooperation, and Valve's documentation was unreachable from
this session (see the research document).

## Provenance

No third-party implementation code was read, copied or adapted. The Steam
on-disk layout used here (`steamapps/libraryfolders.vdf`,
`steamapps/appmanifest_<appid>.acf`, `steamapps/compatdata/<appid>/pfx`) is
publicly documented filesystem structure, not code. The atomic-write and
bounded-store idioms are taken from this repository's own existing modules.
