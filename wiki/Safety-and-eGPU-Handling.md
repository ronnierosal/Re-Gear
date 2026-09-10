# Safety and eGPU handling

**Audience:** players and supervised hardware testers<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** safety policy is authoritative; individual mechanisms remain evidence-gated

Read the complete repository
[safety invariants](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SAFETY_INVARIANTS.md)
before any hardware-facing work.

## Follow the policy for your hardware

Disconnect requirements belong to the exact hardware profile. Re-Gear does not
currently establish physical live-removal support. It must never describe an
eGPU as safe to unplug merely because no software clients are visible. Under
the current shutdown-before-disconnect policy, return to or retain a known-good
state, shut the handheld down fully, and only then disconnect the eGPU.
Unknown hardware inherits no removal permission; see [Supported Hardware](Supported-Hardware).

## What Re-Gear will not bypass

- A running game is not migrated between GPUs.
- A Gamescope-restart transition is blocked when a game is running.
- Unknown game, GPU, profile, display, or transition state fails closed.
- An active display is proven from live state, not connector presence.
- Force-closing processes cannot target Gamescope, Steam, Decky, session
  managers, mounted storage users, or unknown/system processes.
- A hidden warning or preference never disables its underlying safety check.

## Connect, sleep, and disconnect

Hardware tests begin from a verified baseline and add one device or transition
at a time. Sleep protection is a separate capability from display switching or
disconnect readiness. If Re-Gear reports incomplete, stale, unavailable, or unknown
sleep evidence for the active profile, it keeps the operation blocked rather
than guessing.

No Wiki instruction grants mutation authority. Follow the current supervised
validation plan and active hardware driver's directions for a specific session.

An accepted shutdown request or loss of networking is not physical power-off. Keep the eGPU attached if the handheld has not fully powered down. A working Portable screen does not prove that every external GPU reference has been released.
