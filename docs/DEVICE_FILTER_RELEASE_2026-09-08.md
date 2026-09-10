# Device filter eGPU release — engineering record, September 8, 2026

This records how the eGPU device-filter release sequence was made to work on a
supervised configuration, what was measured, and what it does not establish.
It is an engineering evidence record. It is not a support claim, and it does
not change any deployment contract; see
[safety invariants](SAFETY_INVARIANTS.md) and
[deployment validation](DEPLOYMENT_VALIDATION.md).

It supersedes the resource-release conclusion in
[disconnect progress, 2026-09-06](DISCONNECT_PROGRESS_2026-09-06.md), which
recorded installed 0.3.54 and reported that resource release did not succeed.
That record stands as history; this one records the later result.

## Provenance of this record

This is written from the supervised session's own record of the run, not from a
captured evidence artifact. No redacted before/live/after capture for this run
exists in the repository, and this document does not stand in for one. Treat the
measurements below as the operator's recorded observations, and attach a capture
before this record is cited as validation evidence rather than as an engineering
account.

## Configuration and evidence tier

| Item | Value |
| --- | --- |
| Handheld and eGPU | ASUS ROG Ally X with GPD G1 |
| Release release | Re-Gear 0.3.58 |
| Arm sequence | **Hardware tested** from the installed plugin |
| Software removal and rescan | **Hardware tested**, driven from a source checkout rather than the installed plugin |
| Physical live unplug | **Not attempted, not supported** — see safety invariant 10 |

The distinction in that table matters. The arm sequence ran as installed
software. The removal that followed was executed on the same hardware, but
driven by hand from a source checkout, so it is evidence about the kernel and
the device, not about an installed feature. Nothing in either case is wired to
a player-facing control.

## What the arm sequence does

Operator tool, no UI, nothing automatic:

    sudo PYTHONPATH=backend python3 -m hdm.egpu_release --arm

1. Discover the exact character devices of both eGPU PCI functions.
2. Compose the device policy those functions require. A policy covering only
   the render path is refused: one retained audio handle keeps the device held.
3. Compile the policy to a cgroup device program — 312 bytes, 39 instructions
   for this device set.
4. Load it (`BPF_PROG_LOAD`) and attach it (`BPF_LINK_CREATE`) at the user
   manager cgroup.
5. Verify the loaded program is actually enforced on that cgroup before
   anything is disrupted, by querying the attached program ids.
6. Print the restart commands the approved plan calls for; the operator runs
   them while the filter is held.
7. Re-observe holders until none remain.

Recorded result: `clients_clear: every holder released`.

## Findings

These were not obvious in advance, and three of them are properties of the
session's systemd and cgroup topology rather than of this hardware pair.

### The attach point must be the user manager cgroup

Holders span four cgroups across `app.slice` and `session.slice`. The stack's
two leaf units can never reach `wireplumber` or `pipewire`, because those are
**siblings, not descendants**. A filter attached at a leaf unit gates only that
unit's own opens. `user@<uid>.service` is the lowest cgroup that is an ancestor
of every holder, so it is the only attach point that can gate all of them.

### Restarting the session target does not restart the audio stack

`wireplumber.service` is not a dependency of `gamescope-session.target`; only
the pipewire sockets are. Restarting the session target therefore leaves
WirePlumber running and still holding its descriptor. The audio units must be
restarted explicitly, which is why they appear in the restart plan rather than
being assumed to follow from the session restart.

### A cgroup filter gates `open()`, never an open descriptor

The filter decides whether a process may open a device node. It has no effect
on a descriptor that is already open. A process holding the eGPU when the
filter is attached keeps holding it. This is the whole reason the sequence
restarts units instead of only arming: arming prevents reacquisition, and the
restart is what causes release. Arming alone would report a filter in place
over an unchanged set of holders.

### Validation trap: never test the filter with `chmod`

Removing permissions from a device node is not a stand-in for the filter.
Permission denial fires a udev event that WirePlumber reacts to, so the system
responds to the test itself; BPF denial is silent to userspace. A `chmod` test
therefore reads as more optimistic than the real behaviour, and its result does
not transfer. Test the filter by attaching the filter.

## Software removal, from a source checkout

With holders clear, both PCI functions of the multi-function eGPU were
detached, audio function first:

- Each function detached in roughly two seconds.
- The kernel logged `amdgpu: finishing device` and `[drm] amdgpu: ttm finalized`.
- The session stayed active throughout.
- A bus rescan restored both functions in roughly three seconds, with their
  drivers rebound.

A plan covering only the GPU function is refused rather than executed partially:
a multi-function device left half-attached is not a smaller removal, it is an
incomplete one.

## What this does not establish

This is the part that should be read before any of the above is quoted.

- **It is not clearance to unplug anything.** Safety invariant 10 is unchanged:
  the tested configuration does not support physical live unplug. Restore
  internal operation and shut down before disconnecting. Holders released is
  not unplug clearance, and neither is software removal.
- **The clear verdict is not currently reliable enough to act on.** The holder
  scan silently skips holders in a `.scope`, processes whose descriptor or
  cgroup reads fail, and any unit not ending in `.service`; an empty result then
  reads as clear. Tracked in [#120](https://github.com/ronnierosal/Re-Gear/issues/120),
  which states directly that this result must not be consumed as a removal
  precondition.
- **The clear state does not persist.** The filter is detached as the sequence
  reports success, and the session reopens the device nodes immediately, so the
  proven state stops holding at about the moment it is reported. Tracked in
  [#123](https://github.com/ronnierosal/Re-Gear/issues/123).
- **The link is not durable recovery.** It is unpinned and disappears when the
  tool exits, which suits a supervised run and explicitly does not survive a
  crash. There is no ownership journal, so nothing records that a filter was
  ever in place. A production caller needs one.

  Updated 2026-09-09: the plugin path now has one.
  `hdm.domain.filter_ownership` plus `hdm.application.owned_filter` record a
  parent-scope claim before the attach and clear it only after a verified
  detach, and `build_live_disconnect_runtime` composes the filter behind it, so
  a crash in that window reconciles on the next attempt instead of vanishing.
  Two things that does **not** change. The link is still unpinned, so the filter
  itself still disappears with its owner: the journal makes that visible, it does
  not make the filter survive. And this is software verification only — unit
  tests over fixtures, no hardware run — so the arm-sequence evidence above is
  still the only hardware record, and the operator tool described here is
  deliberately unchanged.
- **Nothing here is a player feature.** No RPC and no UI is wired to it; the
  capability is operator CLI only.
- **The USB branch remains unresolved.** Uncorrectable ACS violations on the
  USB branch, from which `xhci` does not recover, are tracked separately in
  [#105](https://github.com/ronnierosal/Re-Gear/issues/105). The GPU branch was
  clean in this work.

## Reproducing

The arm sequence is reproducible from the installed plugin at 0.3.58 with the
command above. Software removal currently has no reviewed operator tool on the
installed build; one is proposed in
[PR #122](https://github.com/ronnierosal/Re-Gear/pull/122) and is unmerged at
the time of writing.

Hardware authority is separate from implementation authority. Permission to
implement any of this never implies permission to run it on a device; see
[agent coordination](AGENT_COORDINATION.md).
