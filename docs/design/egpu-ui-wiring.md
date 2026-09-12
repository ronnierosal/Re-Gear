# Re-Gear eGPU UI wiring contract

This document is the handoff from the design-owned Command Center workstream to runtime/wiring owners.

## Goal

The eGPU UI is now ready to accept live state and verified actions without changing layout or safety semantics.

Use `src/quick-access/expanded-command-center/egpu-ui.tsx` for the detailed eGPU module and lifecycle/progress presentation.

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

## Runtime action slots

`EgpuControlDetail` exposes stable presentation slots for:

- `dockMode`
- `displayOutput`
- `safeDisconnect`
- `details`

Runtime owners may place verified controls into these slots. The component itself must remain presentation-only.

Do not add hardware or RPC calls to the eGPU UI component.

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

Recommended step vocabulary can map to the actual runtime state machine, for example:

- Detect GPU
- Establish link
- Detect display
- Switch display
- Finalize

These labels are examples only. Runtime state remains the source of truth.

## Safe Disconnect

Safe Disconnect remains a separate safety surface.

The UI must preserve the distinction between:

- readiness to begin
- software removal / return-to-handheld completion
- physical unplug clearance

A successful command, a working handheld display, or a removed device does not by itself authorize physical unplug unless the runtime explicitly exposes verified clearance.

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
- safety policy
- persistence

If wiring requires a visual change, report the constraint back to the UI workstream instead of changing the design independently.

## Integration requirement

Before merging eGPU wiring, validate the combined tree against the Command Center UI regression suite, especially:

- approved eGPU field order
- stable Safe Disconnect presentation
- no global header repurposing
- no removed rows because a provider is missing
- no duplicate polling introduced by the visual layer
- no hard-coded synthetic success values

Native Ally visual validation is still required after combined integration.
