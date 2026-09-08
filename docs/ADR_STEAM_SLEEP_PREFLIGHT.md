# ADR: Steam sleep preflight

## Status

Implemented with deterministic tests. The non-sleep lifecycle proof and the
supervised enforcement/display-safety portion passed on the certified Ally
X/SteamOS build on 2026-08-31. Toast and synchronous-modal warning iterations
failed the acknowledgement UX criterion. A delayed, non-popout modal build is
installed, but its supervised visible-warning proof remains pending; this ADR
does not authorize an unsupervised sleep attempt.

## Problem

The backend login1 inhibitor prevents full system suspend while the G1 is
attached, but Steam begins its player-facing sleep sequence before login1 makes
that decision. The live Steam **Power → Sleep** test left Gamescope presentation
black even though the kernel never suspended. A graceful Steam reboot restored
the internal display.

The root inhibitor remains required for non-Steam and privileged request paths,
but it cannot by itself provide a safe Steam user experience.

## Inspected Steam path

On the validated Steam build, the power-menu item calls the shared
`SuspendResumeStore.RequestSleep()` method. The resulting notification reaches
`OnSuspendRequest()`, whose first action is to return when the store has one or
more suspend blockers. Only after that check does Steam call
`SteamClient.User.PrepareForSystemSuspend()` and eventually
`SteamClient.System.SuspendPC()`.

The same store exposes `BlockSuspendAction()`. It increments Steam's native
suspend-blocker count and returns a callback that releases exactly that lease.
This check occurs early enough to avoid the preparation sequence implicated in
the black-screen failure.

Webpack module IDs and minified export names observed during inspection are
ephemeral evidence and must never be stored in implementation.

## Decision

Add a frontend-owned Steam preflight lease alongside the backend-owned login1
lease.

1. Resolve one Steam suspend store by capabilities, using Decky's
   `findModuleExport()`:
   - `BlockSuspendAction` is a function
   - `OnSuspendRequest` is a function
   - `RequestSleep` is a function
2. Resolve and acquire the native blocker synchronously during plugin startup,
   before the first asynchronous backend snapshot.
3. Retain the blocker while the snapshot is loading, stale, unavailable,
   unknown, or reports that the G1 sleep guard is required.
4. Release it only after a fresh snapshot verifies that the G1 is absent and
   the backend sleep guard is not required.
5. Reacquire it idempotently if later polling becomes unknown or observes the
   G1 again.
6. Install a reversible `beforePatch()` on the store instance's
   `OnSuspendRequest`. When Re-Gear holds its blocker, the patch displays a
   game-aware Decky warning and then lets the original method return through
   Steam's blocker check. It never calls a sleep API.
7. On plugin dismount, unpatch once and invoke only Re-Gear's returned blocker
   release callback. Other applications' blocker count is never reset.

The native Steam blocker is the preflight enforcement point. The patch exists
only to explain the refused action. Re-Gear must not patch power-menu DOM nodes,
hard-code webpack identifiers, replace `SuspendPC()`, or depend on connector,
DRM-card, or PCI enumeration order.

## User experience

Quick Access reports two independent protection layers:

- **System inhibitor:** active/inactive from schema 3
- **Steam preflight:** active/unavailable from the frontend lifecycle

When a blocked request occurs:

- G1 attached with no game client: explain that Sleep is unavailable until the
  G1 is safely absent.
- A game owns the G1: use a critical warning that the game and eGPU are active.
- Snapshot or game state unknown: use the stronger fail-closed warning.

Steam closes its transient Power menu after dispatching the suspend request.
Re-Gear therefore schedules the acknowledgement modal after that menu closes and
uses Decky's non-popout modal host with its default visible-SP window resolver.
The plugin runs in an invisible SharedJSContext, so that context's global
`window` must never be supplied as the modal parent. Rendering the modal
synchronously from the pre-request hook is not accepted because Steam may
discard it with the Power menu.

If the deferred modal host rejects the render, Re-Gear emits one critical
attempted-action toast as a presentation-only fallback. A toast failure is
contained and never reaches the Steam hook; neither fallback can release the
native blocker or invoke a sleep API. The modal remains the preferred path
because it requires acknowledgement.

**Never show this explanation again** may continue to hide the passive panel
explanation. It does not hide feedback for an attempted blocked action, disable
either lease, or change safety state.

If the Steam store cannot be resolved, Quick Access reports **Steam preflight
unavailable** as critical and must not claim complete sleep protection. The
login1 inhibitor remains active, but supervised sleep testing is forbidden on
that Steam build.

## Implementation shape

Keep Steam internals behind a small injected adapter and put lifecycle decisions
in a testable coordinator:

```text
SteamSuspendStore adapter
        | acquire/release + attempt callback
        v
SleepPreflightCoordinator <--- latest typed snapshot
        |
        +--- native blocker lease
        +--- Decky warning callback
        +--- frontend status row
```

The coordinator owns at most one release callback and one patch handle. Calling
start, reconcile, or stop repeatedly is a no-op after the desired state is
already reached.

## Verification gates

Before deployment, dependency-free frontend tests or an equivalent deterministic
harness must prove:

- startup acquires exactly one blocker before snapshot resolution
- required, loading, stale, error, and unknown states retain the blocker
- verified G1 absence releases only Re-Gear's blocker
- later G1 presence or unknown state reacquires exactly once
- blocked attempts show standard, game, and unknown-state warnings correctly
- modal-host failure emits one critical fallback toast without changing either
  sleep lease or invoking a sleep API
- warning suppression cannot affect enforcement or attempted-action feedback
- resolver failure reports unavailable and never claims full protection
- dismount unpatches and releases exactly once
- a fake Steam store never reaches its prepare-for-suspend call while blocked
- unrelated pre-existing Steam blockers are preserved

Then run the normal architecture, unit, compile, typecheck, build, and package
checks.

Hardware validation has two phases:

1. **Non-sleep lifecycle proof:** with the G1 attached, show that plugin load adds
   exactly one native Steam blocker, refresh does not duplicate it, and plugin
   unload removes only that blocker. Do not invoke Sleep.
2. **Supervised request proof:** only after phase 1 passes, select Steam Sleep
   once while monitoring boot ID equality, continuous uptime, login1 state,
   Gamescope, live display, and both leases. The warning must appear and the
   visible display must remain usable. Physical-button testing remains blocked
   until this proof passes.

## Rollback

Plugin dismount releases the frontend lease and patch. Reinstalling the previous
package restores the prior frontend while the backend login1 holder follows its
existing crash-safe lifecycle. If the UI becomes unusable, use the already
validated graceful Steam reboot; do not disconnect the G1 or hard-power the
device as the first recovery action.
