# Current evidence and development state

This page summarizes what has changed in Re-Gear and how strongly each change is
proven. It was last reviewed against merged source `5ed1e3d` on September 24,
2026.

## For players — no technical background needed

Re-Gear is still in development and has no supported public release. The
[eGPU guide](../player/egpu.md) explains what that means in practice.

Since mid-September, on the maintainer's single recorded test setup, the
ordinary journey — return to the handheld, **Safe Disconnect**, unplug, plug back
in, TV picture returns — has worked on three test builds. The disconnect-and-sleep
journey has not yet worked on an installed build and is being fixed. The Command
Center now uses its approved artwork and live eGPU controls, and Quick Access can
be customized. Automatic per-game graphics settings are being built but do nothing
yet.

A new build number is not the same as a tested build. Newer test builds can have
different controls, and a built package is not automatically installed or
supported.

## Technical details — for advanced users and contributors

Three evidence levels are kept separate below: **merged source** (code and tests
on `main`), **installed** (a specific build read back on the test handheld), and
**supervised hardware result** (an observed outcome on that one configuration).
None of these extends to other handhelds, docks, graphics cards or builds.

### Installed and supervised hardware results

The [v0.3.98 checkpoint](egpu-lifecycle.md) remains the documented lifecycle
reference in the acceptance matrix. The later trials below come from the
project's task records. The dated authority record,
[CURRENT_STATE](../../CURRENT_STATE.md), has not yet been updated for them, so
treat this table as a summary pending that update, not as the authority.

| Date | Build | Result | Limit |
|---|---|---|---|
| 2026-09-13 | 0.3.98 (`f6059fa`) | One supervised disconnect, physical unplug and replug cycle succeeded | Repeatability, other hardware and sleep not established |
| 2026-09-21 | 0.3.127 | Maintainer-reported manual journey succeeded: TV to handheld, Safe Disconnect, physical unplug, reconnect, return to TV | Single report on one configuration |
| 2026-09-22 | 0.3.129 (`e8ad848`) | Supervised: automatic TV, both display switches, Safe Disconnect through software-down, physical unplug/reconnect and automatic TV all passed | Same configuration only |
| 2026-09-22 | 0.3.129 (`e8ad848`) | **Disconnect + Sleep failed.** It returned to the handheld but never reached software-down, the unplug prompt or sleep; the pending record then blocked TV and its status vanished after a UI remount | Fixed in merged source ([PR #383](https://github.com/ronnierosal/Re-Gear/pull/383)); not yet re-proven on hardware |
| 2026-09-23 to 24 | Later test candidates | Supervised trials are active and have surfaced further defects: automatic TV blocked after reconnect by a leftover disconnect claim, and a leftover sleep blocker after a successful unplug prompt. Fixes are in review, not merged | In progress; no new passing result recorded |

Software reconnect stays excluded after the 0.3.92 incident. Details of the
retained code and its gating are in
[the lifecycle guide](egpu-lifecycle.md#software-reconnect-decision-and-retained-machinery).
Read-only readiness probes do not execute a disconnect or validate a button path.

### Merged source since September 14

These are source integrations with passing CI. None is a hardware result by itself.

**eGPU lifecycle**

- Software reconnect refused at the backend RPC boundary
  ([PR #335](https://github.com/ronnierosal/Re-Gear/pull/335)); no reconnect
  control remains in the production interface.
- Disconnect-before-sleep withdrawn from the UI and refused at the RPC
  ([PR #344](https://github.com/ronnierosal/Re-Gear/pull/344),
  [PR #345](https://github.com/ronnierosal/Re-Gear/pull/345)), then replaced by
  sleep gated on verified physical absence
  ([PR #367](https://github.com/ronnierosal/Re-Gear/pull/367)).
- A **Disconnect + Sleep** failure before software-down retires only its own
  unsubmitted intent; status is restored after a Gamescope remount
  ([PR #383](https://github.com/ronnierosal/Re-Gear/pull/383)).
- **Switch to TV** offered again after a verified successful handheld return
  ([PR #366](https://github.com/ronnierosal/Re-Gear/pull/366)).
- Stale software-down status normalized after a verified physical reconnect
  ([PR #361](https://github.com/ronnierosal/Re-Gear/pull/361)); failed connected
  sleep kept separate from Safe Disconnect status
  ([PR #363](https://github.com/ronnierosal/Re-Gear/pull/363)).
- Read-only eGPU cooling evidence in disconnect status
  ([PR #350](https://github.com/ronnierosal/Re-Gear/pull/350)) and the fan-safe
  preparation contract ([PR #343](https://github.com/ronnierosal/Re-Gear/pull/343)).

**Command Center**

- Production eGPU actions wired ([PR #353](https://github.com/ronnierosal/Re-Gear/pull/353),
  corrected in [PR #371](https://github.com/ronnierosal/Re-Gear/pull/371)) and
  in-game focused overlay routing ([PR #354](https://github.com/ronnierosal/Re-Gear/pull/354)).
- Approved V3 artwork locked and wired across registry controls
  ([PR #365](https://github.com/ronnierosal/Re-Gear/pull/365) to
  [PR #378](https://github.com/ronnierosal/Re-Gear/pull/378)); card copy and the
  first-connection popup polished ([PR #384](https://github.com/ronnierosal/Re-Gear/pull/384)).
- Quick Access customization — tap **Y** to change a button, hold **Y** to move
  cards, **Reset Layout** in Settings — plus **Tutorials** and **About**. See
  [Customize Re-Gear](../player/customize.md). The earlier combined test build
  PR329 was closed without merging; these reached `main` separately.

**Performance**

- Diagnostics report the power range a provider can actually express
  ([PR #277](https://github.com/ronnierosal/Re-Gear/pull/277)). Diagnostic only:
  runtime admission against that range is separate, unfinished work.

**Automatic per-game graphics profiles (inert)**

[PR #398](https://github.com/ronnierosal/Re-Gear/pull/398) integrated the
graphics-profile foundation, a semantic profile engine, performance-plan and
target-resolver models and a frame-generation provider model. Nothing in the
plugin entry points calls this code, no real game is supported, and nothing
changes a game's settings. See the
[architecture](../../GRAPHICS_PROFILES_ARCHITECTURE.md),
[engine](../../GAME_PROFILE_ENGINE.md) and
[staged plan](../../AUTOMATIC_GAME_OPTIMIZATION.md).

### Related records

[Power implementation](../../EGPU_POWER_NEXT.md) separates merged backend and
coordinator code from mounted integration and hardware acceptance.
[Golden preservation](../../GOLDEN_BEHAVIORS.md) defines the regression gate.
Follow the owning PRs and exact revisions rather than inferring capability from
version ordering. Historical point-in-time records are in the
[archive](../../archive/README.md).
