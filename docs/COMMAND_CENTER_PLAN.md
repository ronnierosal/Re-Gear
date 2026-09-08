# Command Center implementation plan

Date: 2026-09-08. Inspected source: `5591a7a72897fd581021b94c3884b1b063324b06`.
Status: approved product direction, proposed detailed interaction/architecture;
not implemented, installed, or visually approved. The shared root agent hub is
the live task/ownership record; this document owns the proposed design, not task status.

**Quick Access is for actions now. Module pages are for configuration and personalization.**

## Evidence and existing work

- [UI_SPEC](UI_SPEC.md) remains the current UI contract. Its safety, independent
  observations, disclosure and refresh rules carry forward. The new first-screen
  hierarchy below replaces its large placement-card presentation only after
  design approval and the foundation task updates that contract.
- `src/index.tsx` owns snapshot refresh, action routing, confirmations, focus,
  diagnostics and a long panel render. It renders `TdpControls` directly and
  does not import the section chooser at this baseline.
- `quick-access-sections.ts`, `quick-access-nav.ts`, `quick-access-nav-row.tsx`
  already provide a pure five-section taxonomy and native DialogButton/Focusable
  icon row: eGPU, Controller, Auto TDP, Display & Audio, System.
- [Issue 125](https://github.com/ronnierosal/Re-Gear/issues/125) owns the section
  migration; [PR 129](https://github.com/ronnierosal/Re-Gear/pull/129), inspected at
  `6accbc5`, wires System to existing `showDiagnostics`. Other sections are not
  migrated there; TDP availability cannot yet reach its parent. Do not recreate
  that PR, overwrite its owner, or silently drop its refresh/state semantics.
- Existing `quick-access-overview.tsx`, `regear-theme.ts`, `SectionFocus`,
  `health-ui.ts`, `connection-quick-status.tsx` and existing guarded action rows
  should be reused. Large two-mode cards spend scarce first-screen space and
  do not scale to performance/controller summaries.
- Inspected `output/pr2-quick-access.png`: historical 320px-wide navy/cyan
  Portable/TV mock surface, not a current installed screenshot or approved new
  Command Center. Existing SVG branding/mode assets and `docs/images/` are
  reusable candidates. No approved new Command Center mockup was found.
- [Navigation evidence](UI_SECTION_NAVIGATION_CANDIDATE.md) records a 268px
  information column and native focus defects. Roughly 310px is a design width,
  not a universal viewport measurement. Local DOM tests cannot prove Steam focus.

## Screen and navigation decision

Use a native in-panel navigation stack: Command Center -> Modules -> module.
One visible, labelled Modules DialogButton opens a single-column list of native
rows with icon, title, one-line summary and chevron. Initial rows: eGPU, Auto TDP,
Controller. Keep Troubleshoot as a separate utility destination; future modules
append registry entries without growing a horizontal strip. No desktop side rail,
horizontal scrolling, or extra full-screen route is needed.

This is a proposed evolution of #125's chooser, not a second navigation project.
The foundation task reconciles it with #129's owner and integrates/reuses the
existing pure model and focus primitives. A labelled vertical list is preferred
because the current five 44px icon targets do not scale indefinitely at 268px.
Tabs/rail squeeze labels or content; an unbounded icon row loses discoverability.
The list costs one extra navigation step for configuration, consistent with the
product rule. Common actions remain on the first screen.

Fresh plugin entry opens Command Center. B returns one internal level and then
delegates to native QAM Back. Closing a modal returns to its initiating control;
returning from a module restores the selected module row and scroll position.
Reopening QAM starts at Command Center; do not persist a hidden diagnostics page
as the new default. Confirm exact QAM lifecycle behavior during native validation.
Keep module order stable through refresh. Unavailable modules stay reachable with
a concise reason; availability must disable mutations, not remove recovery or Stop.
Unknown selections fall back to Command Center. The existing resolver currently
falls back from unavailable selections despite comments promising reachability;
cover that mismatch when adapting the model.

## Command Center hierarchy

Single column, no settings wall. Reading/focus order:

1. Re-Gear / Command Center heading and Modules button.
2. Compact placement and categorical health; one actionable attention message
   when necessary. Healthy state is quiet. Preserve game-state visibility where
   it explains availability. Unknown is explicit, never Portable by fallback.
3. Performance: Auto TDP state, target FPS and configured power limit when known.
   One context-sensitive immediate action: Stop when active; Start only with an
   already valid, explicitly configured range and existing `can_start` permission;
   otherwise Open Auto TDP. Avoid a toggle implying power-writer enablement and
   loop start are the same operation. Never start from guessed defaults.
4. eGPU/dock: observed model when unambiguous, connection, independent display
   target and placement. One existing guarded next action if permitted; recovery
   takes precedence. Connection does not imply rendering, active TV or removable.
5. Controller: observed built-in/external availability, or Status unavailable.
   No invented device name or Player 1 assignment. Open Controller for detail.
6. Troubleshoot utility entry, with urgent recovery reachable even on stale data.

Resolution and frame/refresh controls remain design slots, omitted in the first
implementation unless an existing verified capability contract is identified.
Do not render fake 1080p/60Hz selectors. Auto TDP target FPS is not a display
refresh rate or global FPS limiter. Prefer no empty tiles to planned controls.

## Capability and module content

| Area | Implemented source surface | Proposed presentation / limits |
|---|---|---|
| eGPU | Snapshot inference, connection readiness, optional GPU model name, health, guarded display/restore flows in index | Mode and connection first, independent render/display observations second, lifecycle/progress when active. Preserve Docked-iGPU and Unknown as well as Portable/Boosted/TV. No brand-specific architecture. |
| Dock preferences | Existing automatic docking status/set RPC and opt-in confirmation | Move existing experimental auto-docking preference into eGPU; keep its warning, busy and unavailable gates. Future per-mode/notification policies are planned, not switches. |
| Disconnect | Existing guarded UI and ongoing removal hardening | Do not market Safe Disconnect or Shutdown for Disconnect as solved. No new live-unplug action. The reported attached-G1 shutdown hang and next-boot controller loss remain unresolved in this plan. Existing experimental tools remain behind their safety boundary; no UI task investigates or relaxes it. |
| Display | Existing display/audio observations and transition routes | Show supported observations only. No resolution/refresh/HDR/VRR writer or authoritative value was found in the inspected frontend RPC contract. Missing values are unavailable, not inferred from connector presence. |
| Auto TDP | `TdpControls`, `AutoTdpControls`, `backend.ts`: enabled/can_enable/ready/current_watts; can_start/enabled/running/stopping/target_fps/min/max | Dedicated page: status, existing writer enablement, target/range, Start/Stop, manual Apply/Restore under disclosure, saved per-mode preferences, advanced collection benchmark. Configured watts are not measured consumption. Stop keeps limit; Restore restores saved settings. Closing page does not stop session. |
| Auto personalization | Existing preferences editor and benchmark; active session guard PR 132 | Preserve save-without-activation behavior. Per-game profiles are planned, not equated with existing per-mode preferences. Surface opaque activity codes through player wording; don't change backend guards. |
| Controller | `PeripheralStatusPayload.controller`: complete/exact/builtin_available/external_connected/code; existing shortcut controls | Dedicated page: honest observed availability and existing shortcut settings. No Player 1/name/priority/handoff contract is established by these booleans. Such personalization stays planned; shortcut availability is not evidence of controller assignment. Issue 23 remains independent. |
| Utilities | Existing System/Troubleshoot, support export, journey, sleep, offline readiness | Preserve all existing reachable utilities, privacy filtering and bounded optional collection. Display & Audio moves into eGPU; global support/offline tools remain utility content. Do not lose features during the taxonomy migration. |

Ready, Recovering, Degraded, Attention Required remain health vocabulary.
Transitioning is workflow, Connected is topology, Experimental is feature maturity:
none can overwrite the others. Details disclose the earliest useful reason without
raw IDs, paths or logs. Color always has a text/icon equivalent.

## Frontend boundaries

Proposed files under `src/quick-access/`: `module-registry.tsx`, `shell.tsx`,
`command-center.tsx`, `modules/egpu.tsx`, `modules/auto-tdp.tsx`,
`modules/controller.tsx`, `status.tsx`, `performance-state.tsx`.
These are ownership boundaries, not a mandatory pseudo-API.

- Registry descriptors carry stable ID, label, icon, summary renderer, page
  renderer and capability presentation. A compile-time typed registry is enough;
  do not introduce dynamic plugin loading or a new backend module system.
- Shell owns destination/focus/scroll only. Pure adapters derive presentation
  from authoritative payloads. Module pages receive existing guarded callbacks;
  none calculate a new safety permission from topology or optimistic state.
- Keep snapshot/action coordinator and backend-wide subscriptions in their
  existing lifetime initially. Extract presentation in small patches. Lift TDP
  state/request gates into one shared frontend owner before showing it twice.
  Summary and page share the same status and busy state; no duplicate loops,
  subscriptions, or extra diagnostic polling. Retain late-result invalidation.
- Registry integration belongs to one foundation owner. Module workers deliver
  isolated renderers against that interface; sequence shared wiring/build output
  explicitly. Do not give every worker ownership of `index.tsx` or `dist/`.
- Preserve diagnostics open-edge refresh and closure behavior from #129. Route
  state and diagnostics collection must not diverge. Test stale status, pending
  requests, page changes, Stop accessibility, errors and recovery reachability.

## Visual approval and asset brief

ChatGPT supplies approved mocks and a revisioned spec before visual implementation.
Required views: healthy Portable, connected/TV, unknown/attention, Modules list,
and each module; include unavailable, pending action, long labels and focused
control variants. Show 268px and 310px content widths within actual QAM chrome,
including short-height scrolling. Label mockups as proposed, never screenshots.

Reuse `regear-header-logo.svg`, `regear-icon.svg`, `mode-handheld.svg`, `mode-tv.svg`
subject to visual review. Use native/library vectors for module eGPU, gauge/Auto
TDP, controller, modules/menu, Back, chevron, information, warning, recovery and
power. Existing connection/controller/gauge vectors are candidates; do not create
replacement artwork just to fill slots. A Boosted Handheld symbol and unified
module icon family need ChatGPT direction only if existing vectors are inadequate.
Safe Disconnect/Restore Portable icons are conditional on approved visible actions,
never symbols claiming removal safety. No custom raster status indicators needed.

Asset handoff must record file names, license/provenance, dimensions/viewBox,
dark-background/focus variants, intended placement, accessible text treatment,
approved revision and approver. Keep approved outputs under a dedicated design
folder; implementation tasks link that revision. Record technical deviations with
before/after evidence and return material changes for visual approval rather than
silently redesigning. No ASUS artwork, branding or literal layout reproduction.

## Validation and release boundary

- Fixture rendering at 268px, 310px and 320px content widths, short/tall QAM
  heights measured on target. No horizontal overflow, clipped controls or
  mid-word wrapping. Prefer 44px action targets; prototype readable 14-16px body
  and 18-20px headings, subject to approved mocks and native constraints.
- Controller A activates once; D-pad order follows reading order; B unwinds one
  level; native focus is visible and distinct from selection. Focused items scroll
  into view. Stable selection survives refresh and capability loss. Informational
  focus stops do not mutate. No focus trap, focus loss on unmount or mouse need.
- Targeted frontend behavior tests, `pnpm typecheck`, `pnpm test:frontend`,
  `pnpm build`; generated bundle from the combined final source at integration,
  never arbitrary selection of another branch's dist. Full gates per DEVELOPMENT
  at integration; hardware-affecting flows retain separate supervised approval.
- Capture native SteamOS controller evidence only with the hardware owner at a
  safe time. Fixture evidence is not native validation. Do not test shutdown,
  disconnect, TDP writes or controller mutation to validate layout.
- Final evidence records source/build, fixture vs native, dimensions, input
  sequence, results and remaining limitations. README/Wiki/Discussion review is
  a later documentation-owner handoff; no public redesign in this planning task.

## Ordered inbox map

All implementation items are unclaimed; suggested roles are advisory. Each hub
note contains scope, acceptance, validation, exclusions and documentation impact.

| Task ID | Boundary | Depends on | Suggested fit |
|---|---|---|---|
| qa-design-approval | ChatGPT mockups/assets and exact interaction approval | qa-command-center-plan | ChatGPT |
| qa-navigation-reconcile | Refine existing #125/#129 ownership and migration disposition | qa-command-center-plan | Existing Claude UI owner / Codex coordination |
| qa-module-foundation | Registry, native stack, contract and utility migration foundation | qa-design-approval, qa-navigation-reconcile | Claude |
| qa-health-presentation | Shared quiet health/attention presentation | qa-module-foundation | Codex |
| qa-performance-state | Shared TDP frontend status/action ownership | qa-module-foundation | Claude |
| qa-command-center | Compact first-screen summaries and existing immediate actions | qa-health-presentation, qa-performance-state | Claude or Codex |
| qa-egpu-page | eGPU configuration/detail presentation | qa-health-presentation | Claude |
| qa-auto-tdp-page | Existing TDP tuning/preferences module | qa-performance-state | Claude |
| qa-controller-page | Observed controller status and existing shortcuts | qa-health-presentation | Codex or Claude |
| qa-controller-validation | Native focus/scroll/accessibility acceptance | four page tasks | Codex verifier with hardware owner |
| qa-visual-polish | Approved spacing, typography, icon treatment | qa-controller-validation | Codex |
| qa-ui-evidence | Screenshot evidence and technical/public-doc handoff | qa-visual-polish | Codex / ChatGPT |

The reconciliation task is coordination only: #125/#129 remains the existing
implementation record. Its acceptance requires an explicit recorded disposition
from its owner (reuse, land first, or accepted supersession), refreshed collision
checks for #50/#62/#82 and index/dist, and source availability for this plan before
dependent work starts. It does not independently implement or merge #129.
No global eGPU dependency blocks pure UI preparation. Any specific runtime action
without approved capability evidence stays absent/guarded; backend owners keep
their priority and checkout. Recheck current claims before every implementation.
