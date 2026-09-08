# Disconnect resource-release progress, September 8, 2026

This public summary records the current state of disconnect resource-release
work. It succeeds
[the September 6 summary](DISCONNECT_PROGRESS_2026-09-06.md), which recorded
installed 0.3.54 and remains accurate for that build. It does not replace
deployment contracts or establish support for other devices.

## What changed since September 6

The September 6 record concluded: visible return succeeded, resource release did
not. Resource release has since succeeded on a later build.

- Configuration: ASUS ROG Ally X with GPD G1; installed Re-Gear **0.3.58**.
- A cgroup device filter was compiled, loaded, attached at the user manager
  cgroup, and verified as enforced before anything was disrupted.
- With the filter held, the approved unit restarts were run, and every process
  holding the eGPU released it. Recorded result:
  `clients_clear: every holder released`.
- Separately, and driven from a source checkout rather than the installed
  plugin, both PCI functions were detached in about two seconds each with a
  clean kernel teardown, and a bus rescan restored both in about three seconds
  with drivers rebound.

Engineering detail, measurements, and the topology findings that made this work
are recorded in
[the device filter release record](DEVICE_FILTER_RELEASE_2026-09-08.md).

**Result:** resource release succeeded on the tested configuration. **No
physical-unplug clearance was granted, and none is implied.**

## What this does not mean

Under the current tested policy, fully shut down before disconnecting the eGPU.
Safety invariant 10 is unchanged: the tested Ally X and GPD G1 combination does
not support physical live unplug.

Three specific limits apply to the result above, and they are the reason it is
not yet a disconnect precondition:

- The holder scan can report clear while holders remain — it silently skips
  holders in a `.scope` and processes whose descriptor or cgroup reads fail
  ([#120](https://github.com/ronnierosal/Re-Gear/issues/120)). That issue states
  the result must not be consumed as a removal precondition.
- The filter detaches as success is reported, so the clear state does not
  persist long enough to act on
  ([#123](https://github.com/ronnierosal/Re-Gear/issues/123);
  [PR #124](https://github.com/ronnierosal/Re-Gear/pull/124) opens that window).
- No reviewed operator tool for software removal exists on the installed build
  ([PR #122](https://github.com/ronnierosal/Re-Gear/pull/122), unmerged).

None of this is wired to a player-facing control. The capability is operator
CLI only, and no automatic path uses it.

## Ownership

[Issue #52](https://github.com/ronnierosal/Re-Gear/issues/52) owns remaining
audio release and recovery.
[Issue #54](https://github.com/ronnierosal/Re-Gear/issues/54) owns supervised
software removal and eventual disconnect validation.
[Issue #90](https://github.com/ronnierosal/Re-Gear/issues/90) owns the sequencing
plan that separates software removal from physical unplug.
[Issue #105](https://github.com/ronnierosal/Re-Gear/issues/105) owns the
unresolved USB-branch ACS violations.

Follow the existing [deployment rules](DEPLOYMENT_VALIDATION.md),
[safety invariants](SAFETY_INVARIANTS.md), and
[reviewed diagnostics](DIAGNOSTICS.md).
