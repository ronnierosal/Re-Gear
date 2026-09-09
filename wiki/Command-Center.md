# Command Center

**Audience:** players and UI contributors<br>
**Reviewed:** 2026-09-09<br>
**Maturity:** implemented and staged; **not hardware tested**

The Command Center brings common controls and status into one controller-friendly
page. Modules hold deeper configuration. The repository
[UI contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/UI_SPEC.md)
owns implemented interaction rules. Implementation and staging do not establish
hardware readiness.

## How the interface is organized

- **Quick controls:** a two-column tile grid — FPS target, TDP limit, Auto TDP, display target — plus a fifth Safe Disconnect tile.
- **Status links:** eGPU and controller rows open read-only details. Opening status never requests a hardware change.
- **Modules:** a labelled list opens deeper eGPU, performance and controller pages.
- **Troubleshooting:** explanations and technical evidence stay available without filling the main page.

The grid keeps a fixed shape. A tile whose feature is unavailable is dimmed and
still selectable, showing why, rather than disappearing — a tile that vanishes
moves every tile after it under the player's thumb as a status arrives.

No tile invents a value. An unknown power limit reads *Unknown*, never `0 W`.
The FPS tile is a proposed capability with no provider on this device: it keeps
its position, says so, and shows no number. It is **not** Auto TDP's target FPS.

## What is implemented

| Area | State |
|---|---|
| Routing, module registry, Back contract, 2D grid traversal | implemented ([#153](https://github.com/ronnierosal/Re-Gear/pull/153)) |
| Shell wired into the panel; fresh entry opens Command Center | implemented ([#163](https://github.com/ronnierosal/Re-Gear/pull/163)) |
| Quick-tile grid | implemented ([#189](https://github.com/ronnierosal/Re-Gear/pull/189), [#203](https://github.com/ronnierosal/Re-Gear/pull/203)) |
| eGPU and Controller module pages, read-only | implemented ([#193](https://github.com/ronnierosal/Re-Gear/pull/193), [#191](https://github.com/ronnierosal/Re-Gear/pull/191)) |
| Safe Disconnect tile and post-disconnect result | implemented ([#198](https://github.com/ronnierosal/Re-Gear/pull/198), [#205](https://github.com/ronnierosal/Re-Gear/pull/205)) |
| Auto TDP module page | not built |
| Native controller and focus validation | **not performed** |

Design assets are approved and merged ([#144](https://github.com/ronnierosal/Re-Gear/pull/144)); the
manifest records that approval as delegated rather than a personal inspection of
each image.

## Safe Disconnect

Safe Disconnect detaches the eGPU **in software**. It is offered only when the
owning backend reports the action as attemptable; the panel never derives that
from topology, connection state, or the fact that two devices are online.

Before the action, a confirmation states that the Steam session will restart —
because that is what frees the device — and that the cable stays connected. If a
standing external display must be turned off, that is a **separate approval**,
because it is visible to whoever is watching the television.

After the disconnect and the session restart, the panel reports what the attempt
actually did and runs six checks before saying the eGPU can be disconnected:

1. the removal completed and released,
2. the device was not left half detached,
3. the PCI functions were removed and not restored again,
4. nothing still holds the device, with a process scan that actually finished,
5. Re-Gear's device filter is disarmed,
6. **the system itself reports that no eGPU is connected.**

The sixth is the decisive one. A success code says a command ran; *no eGPU is
connected* says the device is gone from the bus. If any check cannot be
evaluated it fails: absent evidence never counts as a pass on this screen.

This covers the **eGPU only**. Other devices behind the dock — USB controllers
and storage — are a separate path with a known `xhci` recovery failure
([#105](https://github.com/ronnierosal/Re-Gear/issues/105)) and are not checked.

### Evidence level

The removal sequence itself is **hardware tested**: both eGPU PCI functions were
detached with the handheld powered and the cable attached, then restored by
rescan with drivers rebound.

The **button** is not. The RPC path has not been exercised through Decky's
transport, and the clearance checks above are tested against fixtures rather
than against a live removal. Whether the status actually reports *no eGPU
connected* after a real removal is precisely what a hardware run must confirm.
Until then this is **implemented and staged**, not hardware tested.

Safety invariant 10 — which forbids unplugging while the device is bound —
and its scoping question in
[#147](https://github.com/ronnierosal/Re-Gear/issues/147) remain the owning
contracts. The Wiki does not decide them.

## Controller flow

The intended flow uses directional navigation, activation, Back, and focus
restoration. Back returns one level inside the panel and then hands the press to
Steam's own Quick Access Back, so a player is never trapped.

**Native Decky and controller testing has not been performed.** Keyboard
interaction with a prototype, and unit tests over a navigation model, are
different and weaker levels of evidence than a controller in a player's hands.

## Screenshots and validation

Real screenshots will be added here and to the README once the implemented
interface has been reviewed in Decky. Captures should identify the build and
view and avoid private game, account or diagnostic details. Design mockups
remain explicitly labelled concepts.

**Priority:** active usability work alongside eGPU reliability. Remaining gates
are native controller and focus validation, the Auto TDP module page, capability
lifting for the performance tiles, and a hardware run of the disconnect through
Decky's transport.
