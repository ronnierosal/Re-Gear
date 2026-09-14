# Re-Gear eGPU UI wiring contract

This document is the handoff from the design-owned Command Center workstream to runtime/wiring owners.

## Goal

The eGPU UI is ready to accept live state and verified actions without changing layout or safety semantics.

Primary presentation files:

- `src/quick-access/expanded-command-center/egpu-ui.tsx`
- `src/quick-access/expanded-command-center/egpu-actions-ui.tsx`
- `src/quick-access/expanded-command-center/popup-ui.tsx`

## Approved primary eGPU fields

Keep these concepts separate and visible, even when a provider is unavailable:

1. External GPU
2. Dock mode
3. Display output
4. Render GPU
5. Connection link
6. Safe Disconnect readiness

Do not collapse connection, rendering, display, or unplug readiness into a single `Connected` state.

Unknown or unavailable providers should render explicit `Unknown` / `Unavailable` values instead of deleting cards or rows.

## Fast Auto TV popup

Normal Auto TV switching is expected to complete quickly, around the 7–10 second class when runtime is healthy.

Use `EgpuConnectionPopup` for this path.

The normal popup should remain compact and centered, with no more than four visible lifecycle rows. Runtime supplies real state; UI does not fabricate percent complete.

Recommended compact phases may map to real runtime states such as:

- Detect eGPU
- Establish connection
- Switch display
- Finalize

Completed states use success icons. The active step uses the animated active treatment. A short success confirmation may be shown before host dismissal.

`Retry` is never inferred from elapsed time. It may appear only when runtime explicitly reports a failed state that is safe to retry. A merely delayed operation should offer details / keep-waiting behavior instead.

## USB authorization popup

Use `UsbAuthorizationPopup` when a device requires explicit USB authorization before the eGPU workflow can continue.

Required runtime inputs:

- truthful device label/identity available to the user
- exact authorization action
- optional details surface
- cancel / not-now action

The UI does not invent permanent trust, `Always allow`, or policy persistence. If persistent authorization becomes supported later, it requires an explicit runtime and UX contract.

## Sleep while eGPU is attached

Sleeping with the eGPU physically connected is a supported user choice when runtime permits it.

Use `EgpuSleepChoicePopup` when sleep is requested while an eGPU is attached. The popup exposes two distinct paths:

1. **Sleep** — keep the eGPU connected and let the device resume with the same physical connection still attached.
2. **Safe Disconnect + Sleep** — run the verified Safe Disconnect path first, then request sleep only when runtime permits it.

The UI must not imply that Safe Disconnect is required merely to sleep while attached.

## Approved eGPU action set

The eGPU module and Quick Access may both expose the same action vocabulary:

1. `switch-handheld` — switch from TV to handheld
2. `safe-disconnect` — open/run the verified Safe Disconnect flow
3. `resolution` — open verified resolution/display-target controls
4. `disconnect-sleep` — Safe Disconnect, then sleep
5. `disconnect-shutdown` — Safe Disconnect, then shutdown
6. `status` — open eGPU status/detail surface

Use `EgpuQuickActions` as the presentation surface. It uses the same four-column Command Center grid language. Unsupported actions remain visible but unavailable rather than disappearing.

Do not change the meaning of these actions between the eGPU tab and Quick Access.

## Runtime action slots

`EgpuControlDetail` exposes stable presentation slots for:

- `dockMode`
- `displayOutput`
- `safeDisconnect`
- `details`

Runtime owners may place verified controls into these slots. The component itself must remain presentation-only.

Do not add hardware or RPC calls to the eGPU UI components.

## Lifecycle/progress UI

Use `EgpuLifecycleDetail` for connect, dock, return-to-handheld, and other eGPU lifecycle progress surfaces.

Runtime supplies:

- exact operation title
- elapsed time, if measured
- current summary
- ordered state-machine steps
- active step index
- optional delayed-state warning
- optional expandable/details content
- action controls

The UI must not infer progress or manufacture percentages.

## Safe Disconnect and power requests

Safe Disconnect remains a separate safety surface.

The UI must preserve the distinction between:

- readiness to begin
- software removal / return-to-handheld completion
- sleep request acceptance
- shutdown request acceptance
- physical unplug clearance

A successful command, a working handheld display, sleep, resume, or shutdown request does not by itself authorize physical unplug unless runtime explicitly exposes verified clearance.

Use `EgpuPowerActions` for the optional Safe Disconnect + Sleep and Safe Disconnect + Shutdown presentation.

## Presentation ownership

ChatGPT UI workstream owns:

- composition
- hierarchy
- sizing
- colors
- typography
- icon treatment
- responsive behavior
- popup/modal presentation

Codex / Claude Code own:

- state producers
- observation confidence/freshness
- action dispatch
- hardware/runtime behavior
- USB authorization semantics
- sleep/resume semantics
- safety policy
- persistence

If wiring requires a visual change, report the constraint back to the UI workstream instead of changing the design independently.

## Integration requirement

Before merging eGPU wiring, validate the combined tree against the Command Center UI regression suite, especially:

- approved eGPU field order
- stable six-action vocabulary
- four-column action grid on supported widths
- Safe Disconnect presentation
- sleep-attached vs disconnect-first choices remain separate
- USB authorization is explicit and device-scoped
- no global header repurposing
- no removed rows because a provider is missing
- no duplicate polling introduced by the visual layer
- no hard-coded synthetic success values

Native Ally visual validation is still required after combined integration.
