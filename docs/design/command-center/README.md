# Command Center visual review 01

Current mockup: [review 02 — quick-control tiles](REVISION_02.md), revised to
Ronnie's icon-grid direction. Review-01 decisions below are retained as history.

Status: **proposed; visual approval pending**. Prepared 2026-09-08 for
`qa-design-approval`, by Codex under Ronnie's instruction to proceed with mocks
and coordination. This is a design artifact, not production frontend work.

Open [the interactive review](review.html) in a browser. Use the review controls
outside the panel to change scenario, page, content width and panel height.
[Six-view comparison](captures/review-01.png) and
[all captures](captures/) preserve review 01. Values are illustrative fixtures.

The owning proposal is [COMMAND_CENTER_PLAN](../../COMMAND_CENTER_PLAN.md).
The current [UI_SPEC](../../UI_SPEC.md) remains authoritative until the
foundation task updates it after approval and navigation reconciliation.

## Design decisions for approval

1. Command Center replaces large mode cards with a compact placement/health row,
   one performance action, and eGPU/controller summary rows. Muted navy/graphite
   surfaces and cyan focus/accent retain the existing Re-Gear palette.
2. A labelled Modules button opens a vertical list. Each module row includes a
   reusable icon, label and summary. Unavailable modules stay inspectable.
3. Top-level performance means current Auto TDP state, target FPS and configured
   watts. It does not claim a refresh-rate setter, global frame limiter, measured
   watts or per-game profiles. Unsupported targets show Unavailable rather than
   sample values. One Stop action is available while running; configuration is
   reached through the module. No new quick-start default is invented.
4. eGPU keeps connection, display, render GPU and lifecycle separate. The docked
   fixture illustrates an already-permitted existing return action; no runtime
   permission is inferred by production code from the fixture's scenario name.
5. Attention appears above normal controls, with a direct Troubleshoot entry.
   Healthy states do not show warning banners. Unknown never highlights Portable.
6. Controller shows only built-in/external availability. Identity/Player 1/priority
   and automatic handoff are not represented as implemented features.

## Exact presentation handoff

| Element | Review 01 target | Native implementation mapping |
|---|---|---|
| Main content | 268, 310 and 320 CSS px tested; 16px panel inset | Measure actual QAM content; do not scale the whole interface with transforms |
| Page title | 20px, 600/700 weight, compact line height | Existing Decky heading styling adjusted within native constraints |
| Body / secondary | 14-15px / 12-13px; secondary text #b5c3d2 | Avoid shrinking long strings; wrap at word boundaries |
| Surfaces | #18212c panel; #111b25 inset; #344453 border | Reuse theme tokens; avoid bespoke gradients per module |
| Action / focus | #244655 primary action; #66d9f7 focus | Native DialogButton with visible native gamepad focus; CSS focus here is illustrative |
| Geometry | 8-10px radius, 12px section gap, 44px minimum button height | Use existing action-row/native field building blocks |
| Navigation | In-panel stack; Back restores invoking row and scroll | Shell owns destination/focus; avoid a full-screen route |
| Scrolling | Content scrolls; title and A/B legend stay visible | Native scroll container/focus-to-visible behavior; fixed legend is proposed chrome |
| Status | Small text plus color; no healthy giant badge | Existing health adapter; unknown and maturity remain separate |

The HTML uses browser buttons/selects as visual stand-ins. It does not import
Decky, call RPCs, poll state, access a device, or emulate Steam's focus router.
Its QAM header/footer are approximations. Native dropdown styling, exact viewport,
Back interception and focus highlighting must be verified in the foundation and
controller-validation tasks. A native limitation warrants a recorded deviation,
not silent visual redesign.

## State and interaction coverage

- Portable with Auto TDP active; TV Docked with external GPU; unknown/attention;
  stopping; unsupported TDP; long observed GPU model name.
- Command Center, Modules, eGPU, Auto TDP, Controller, Troubleshoot.
- Modules -> page -> Back, focus restoration, Escape, narrow/short scroll,
  and local simulated Start/Stop. All actions are fixture-only.
- Manual power, saved preferences, benchmark, shortcut and utility disclosures
  are structural placeholders for existing components. Their complete editors
  are not redesigned or approved by these placeholders. Implementation must
  preserve their current contracts and validate their final rendered content.
- Automatic TV docking remains an experimental opt-in. The fixture resets the
  checkbox and explains the confirmation boundary; it does not simulate approval.

## Verification

[verification.json](verification.json) records local Edge/Playwright checks:
72 layout cases, image loading, browser errors and meaningful navigation/state
checks. [verify.cjs](verify.cjs) regenerates screenshots and evidence. Requires
Node, Playwright and installed Edge; no package or production dependency changed.
Run `node docs/design/command-center/verify.cjs` with Playwright resolvable from
the environment. There are 22 individual captures plus the six-view comparison.

This proves the HTML fixture renders and responds locally. It does not prove
native Decky focus, gamepad behavior, installed capability, or hardware safety.
No shutdown, disconnect, power-limit write or controller mutation was performed.

## Approval record and remaining gates

- Revision: **review-01**, files and captures in this directory.
- Approver/date: **pending**. No visual sign-off inferred from “go ahead work on it.”
- Requested decision: approve the first-screen hierarchy, labelled Modules stack,
  density/palette and icon reuse, or identify changes against this revision.
- Separate owner decision: `qa-navigation-reconcile` awaits the existing #129
  owner's disposition. No code ownership transfer has been assumed.
- On approval, record the exact committed revision and any exclusions in this
  record and the hub; only then satisfy `qa-design-approval` dependencies.
- Substantial visual changes after approval require an explicit deviation record
  with reason, changed view and comparison; implementation agents do not replace
  approved assets or layout without recording the mismatch.

Documentation impact: none

Public documentation is unchanged. Later implementation/evidence tasks supply
the actual player-facing README/Wiki/Discussion handoff.
