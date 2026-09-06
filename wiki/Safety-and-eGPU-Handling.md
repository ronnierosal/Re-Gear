# Safety and eGPU handling

**Audience:** players and supervised hardware testers<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** safety policy is authoritative; individual mechanisms remain evidence-gated

Read the complete repository
[safety invariants](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SAFETY_INVARIANTS.md)
before any hardware-facing work.

## Current GPD G1 rule

Physical live removal is unsupported. Re-Gear must never describe the G1 as safe to
unplug merely because no software clients are visible. Return to or retain a
known-good Portable state, shut the handheld down, and only then disconnect the
G1.

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
sleep evidence for the first profile, it keeps the operation blocked rather
than guessing.

No Wiki instruction grants mutation authority. Follow the current supervised
validation plan and active hardware driver's directions for a specific session.

An accepted shutdown request or loss of networking is not physical power-off. Keep the G1 attached if the handheld has not fully powered down. A working Portable screen does not prove that every external GPU reference has been released.
