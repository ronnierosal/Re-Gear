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

The Command Center uses a compact placement/display/game header and two-column
five-tile grid: FPS target, TDP limit, Auto TDP, Display target, Safe Disconnect.
Modules opens a labelled list of eGPU, Auto TDP and Controller destinations.
Exactly one destination is mounted; configuration does not trail the grid.
The two hardware status rows open read-only details. Troubleshoot is reachable
from Command Center and Modules and owns optional diagnostics.

TDP opens a compact picker using observed device limits. Auto TDP shows the
separate loop observation: Running, Stopping, Off or Unknown; it offers Stop
while running and Configure otherwise. Manual writer enablement is not loop
activity. Tiles and modules share one on-demand observation/request owner,
reject superseded responses and preserve Stop preemption. FPS limiting stays
unavailable without a provider; Auto TDP's target FPS is not a frame-rate cap.
Display uses the same guarded action in the picker and eGPU module.

Safe Disconnect retains the backend offer and confirmation. Software-removal
results never grant cable clearance: v1 unavailable status cannot prove bus
absence, and dock USB/Thunderbolt teardown remains unverified. Invariant 10 is
unchanged. No additional backend or hardware authority is implied by a tile.

Approved inline assets and stable tile positions preserve the design baseline.
Unavailable tiles remain focusable with explanations. Back restores the invoking
tile/row and delegates to Steam at the root; a fresh panel opening returns to
Command Center. [Validation](COMMAND_CENTER_VALIDATION.md) distinguishes browser
fixtures from pending native Decky/controller and transport verification.

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
  driver, or unguarded hardware-removal surfaces.
- Actions use HDM's preview/approval/journal/revalidation contracts.
- Exact first-profile identity is a certification detail, not the product's
  general player vocabulary.

Established hierarchy, terminology, and authority should not be casually
redesigned. Material changes require review of this document, relevant frontend
tests, controller navigation, accessibility, and current backend capability.
