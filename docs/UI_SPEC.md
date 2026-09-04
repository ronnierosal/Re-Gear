# Quick Access UI specification

This is the authoritative player-facing UI contract. eGPUBridge supplied useful
interaction evidence; agents implement this HDM specification rather than an
instruction to "make it look like eGPUBridge."

## Goals

- Controller-first, readable at Quick Access distance
- Status before controls
- Calm next action in player language
- Technical evidence available through progressive disclosure
- No control that implies authority the backend does not have
- Unknown and degraded state remain visible instead of being guessed away

## Primary hierarchy

The first view should answer, in order:

1. **Placement:** Portable, Boosted Handheld, Docked-iGPU, TV Docked, Unknown,
   or Degraded.
2. **Health:** Ready, Recovering, Degraded, or Attention Required.
3. **Game:** Running, Idle, or Unknown.
4. **Connection/readiness:** concise eGPU/display/link or journey status.
5. **Next action:** only when a currently approved flow can actually perform it.

Do not lead with PCI IDs, DRM connectors, Gamescope arguments, service names, or
transaction internals.

## Layout and interaction

- Use native Decky components and focus behavior.
- Keep the happy path compact; expose troubleshooting/detail behind one
  controller-focusable disclosure.
- Preserve focus when expanding or closing detail.
- Use one primary action per immediate task. Secondary inspection, acknowledge,
  or cancel actions remain visually subordinate.
- Destructive or disruptive actions require a backend-computed preview and the
  confirmation level defined by the owning safety contract.
- Do not add polling for visual convenience. UI cadence follows the bounded
  refresh policy and defers nonessential work during games.

## Status and error presentation

### Re-Gear compact visual implementation

Quick Access uses a single-column navy layout, cyan observed-mode cards, and an
amber primary TV action. The cards are read-only status, not mode selectors;
unknown, degraded, or loading evidence must not highlight a known placement.
Health and game status remain visible above the cards. No unsupported Boosted,
GPU tuning, or game-profile controls are offered.

The Dock / eGPU disclosure uses only the existing snapshot to show independent
active-display, render-GPU, and link observations. It starts no diagnostic RPCs.
Automatic TV docking uses Decky's native sliding `ToggleField`, retaining its
opt-in confirmation and unavailable/busy states. Native buttons retain their
existing action guards, acknowledgement flows, and focus behavior. Troubleshoot
remains the entry point for technical tools and secondary diagnostics.

This layout requires on-device controller, text-fit, and scrolling validation;
local component and contract tests are not evidence of hardware UX validation.

- Prefer `eGPU`, `handheld`, `internal display`, and `external display` in normal
  UI. Exact Ally/G1 names belong in supported-hardware or diagnostic context.
- State what HDM knows, what it cannot prove, and the safest next step.
- A failure shows the earliest useful stage and a stable categorical reason,
  never raw command output or private identity.
- Recovery state stays distinct from observed placement.
- Do not label a connector merely `connected` as active TV output.
- Never say `safe to unplug` for the current G1 profile; use the approved
  shutdown-before-disconnect guidance.

## Health and diagnostics

The first view shows one categorical health result and bounded blockers.
Troubleshooting may show:

- build/version label
- categorical hardware profile/capabilities
- stage timings
- recent bounded actions/failures
- current transaction/recovery state when connected to an authoritative source
- privacy-safe support preview/export controls

It must not render stable hardware IDs, connector names, paths, PIDs, command
lines, hostnames, addresses, account/game identifiers, or raw logs.

## eGPUBridge lessons retained

- One obvious primary display action
- Current status adjacent to the action
- Restore-internal recovery prominence
- Diagnostics separated from the happy path
- Controller-usable native Decky controls
- Visible error outcome rather than silent failure

## Intentional differences

- HDM separates placement, health, workflow, and evidence confidence.
- HDM does not expose eGPUBridge's broad tuning, TV/network control, launcher,
  driver, or live-removal surfaces.
- Actions use HDM's preview/approval/journal/revalidation contracts.
- Exact first-profile identity is a certification detail, not the product's
  general player vocabulary.

Established hierarchy, terminology, and authority should not be casually
redesigned. Material changes require review of this document, relevant frontend
tests, controller navigation, accessibility, and current backend capability.
