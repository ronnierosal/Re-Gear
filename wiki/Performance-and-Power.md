# Performance and power

**Audience:** players and performance contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** implemented in development source; not installed or hardware validated by this review

Manual TDP and optional Auto TDP aim to make handheld power control understandable.
The [TDP contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/TDP_CONTROL.md)
owns provider requirements, behavior, and validation. This is guarded power-limit
control, not a promise of higher FPS, longer battery life, or universal support.

## Manual and automatic control

**Manual TDP** requests a supported handheld power limit. The requested value,
read-back configured limit, and measured power consumption are different facts.
Re-Gear must verify the configured result and handle partial failure or ownership
changes through its recovery policy.

**Auto TDP** adjusts within a player-selected range toward a frame-rate target.
It depends on fresh game-bound telemetry and a supported provider. It must pause
or stop issuing adjustments when the game, measurements, controller ownership,
or readback becomes uncertain. It cannot guarantee a frame rate.

Saving per-mode preferences does not enable control. Manual and automatic
requests share the power-control service; opening or closing a page must not
silently start or stop the backend session. Unsupported modes remain unavailable.

## Current implementation and next gates

The manual controls, Auto TDP session, preference editor, and guarded provider
path are present on main following [PR #49](https://github.com/ronnierosal/Re-Gear/pull/49).
[PR #132](https://github.com/ronnierosal/Re-Gear/pull/132) contains additional
provider-range and session guards and remains separate review work at this checkpoint.

**Priority:** ongoing performance work; reliability gates precede availability
claims. Actual provider limits, competing controllers, benchmark cost, thermal
configuration, restoration, and native UI behavior still require validation on
the exact device/build. Do not copy wattage ranges from another handheld or run
competing power writers as a workaround. The future [Command Center](Command-Center)
will expose only controls supported by the current capability evidence.
