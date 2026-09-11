# Re-Gear shared UI design system

The [approved Command Center composition](design/command-center-approved.md) and
[preservation contract](UI_DESIGN_CONTRACT.md) own the visual language. This guide
defines the user-requested popup family, not a separate redesign. It is a target
contract; migration and native evidence must be reported per surface. A merged
guide alone does not establish that every popup complies.

## Shared visual tokens

Use existing Re-Gear palette and repository icons through shared components.
Prefer a small shared modal, status row/icon, progress and warning implementation
over duplicated per-dialog styling; retain Decky's focus and confirmation APIs.

| Role | Treatment |
| --- | --- |
| Surface | Dark navy, restrained translucent fill, subtle border and modest radius; no full-popup neon outline. |
| Primary text | Existing off-white; clear title and short current state. |
| Secondary text | Muted blue-gray for explanation and diagnostics; smaller elapsed metadata. |
| Active/progress/focus | Cyan. Obvious dark-surface focus border without white fill or layout shift. |
| Success | Green only for a verified result supplied by the application. |
| Warning | Amber for attention or delay; delay alone is not failure. |
| Error | Red for an actual reported failure. Missing observations are muted Unknown, not invented failure. |
| Cards | Existing padding/radius/border rhythm; no separate oversized alert design. |

Use the existing font family. As a starting scale, modal title 18–22px,
section/primary copy 14–16px, secondary 13–14px, metadata 11–12px; verify at
actual handheld CSS scale rather than shrinking all content to fit. These sizes
are implementation guidance within the approved hierarchy, not new branding.

## Status icons

`src/quick-access/command-center-icons.tsx` already provides these assets:

| State | Existing asset and behavior |
| --- | --- |
| Success | `status-ok`, green |
| Warning/blocked | `status-warning`, amber |
| Error | `status-error`, red |
| Unknown/unavailable | `status-unknown`, muted |
| Checking/waiting/switching | Reuse a suitable existing activity asset with restrained animation; inventory assets first. Shared component must centralize its choice. |

No Unicode checks, emoji, CSS-drawn success circles or substitute icon families
when repository assets exist. Labels accompany icons; color is not the only
signal. Keep icon sizing consistent with labels and separate status from focus.

## Viewport and structure

Every modal has a bounded shell, persistent header, internally scrollable body,
and persistent footer/actions. Use flex layout with `min-height: 0` on shrinking
body ancestors and `overflow-y: auto` on the body, not the entire dialog.
Measure/allow for the usable viewport and Steam chrome; `100vh` alone does not
prove fit inside the host. Keep comfortable top/bottom and side margins.

Use viewport-relative max height and width with a sensible dialog-width cap.
Do not globally override Steam dialog classes; styles must be scoped to Re-Gear.
Long details, translated labels and errors must not grow the shell beyond bounds.
Never hide bottom actions, shrink the whole popup, clip necessary information or
reduce text until it fits. The header/footer must remain visible while details
scroll. At small sizes, reduce spacing modestly before reducing text.

## Connection presentation

Header: Re-Gear asset, concise application-backed state, small `m:ss elapsed`.
Primary state: Connecting, Waiting, Ready, Action required or Failed as supported
by actual observations. Distinguish physical attachment from docking completion.
Show the active step with a small animated indicator, not a fabricated percentage
or an unconditional multi-stage promise.

Use short readable status rows for GPU, link, display, audio, switching and game
state only when their meaning matches the supplied checks. Preserve the original
evidence behind **View details**. Do not rename a readiness prerequisite as an
executed action. Technical checks and full reason text belong in the expandable
scrolling details, not repeated high-priority warning blocks.

One compact delayed notice is enough: “Taking longer than expected” plus the
current unconfirmed step and necessary keep-connected guidance. Full diagnostics
remain accessible. Do not infer failure from elapsed time or promise a three-minute
deadline. Connection, display activation and physical unplug clearance are separate.

## Motion and lifecycle

- Checking/waiting: small continuous activity animation, including genuine waiting
  for confirmation. Pending/unknown checks do not masquerade as completed steps.
- Status change: subtle color/opacity transition, no aggressive flashing.
- Entrance/exit: short fade with modest movement if appropriate, approximately
  120–180ms. Keep lifecycle callbacks and focus restoration intact.
- Honor `prefers-reduced-motion`: remove motion while retaining clear static
  progress text; reduced motion is not a failed animation test.
- Verified completion: briefly show success before closing (existing 3.5-second
  dwell is a usable baseline). Pause/suppress automatic close while the user is
  interacting or inspecting details; recheck current completion/freshness before
  dismissal. A stale result must not cause success dismissal.
- Hide dismisses presentation only. Cancel/confirm retain each flow's existing
  semantics. Do not auto-confirm or auto-dismiss safety confirmations.

## Controller and touch

A activates the focused action. B backs out of details or hides/cancels according
to the existing flow. D-pad navigation must expose scrolling diagnostics and all
footer actions, with no focus jump after a status refresh. Retain safe initial
focus, focus containment and opener restoration. Refreshes must not steal focus
from an input or collapse details. Touch remains usable; never require a mouse.

## Migration inventory and evidence

The implementation owner must audit all `showModal`/`ConfirmModal`/`ModalRoot`
call sites and indirect wrappers in the final source. Record each surface as
migrated, already compliant, or not migrated with exact reason and owner:

- eGPU connection/docking progress and readiness checks;
- safe disconnect progress, ready, blocked and game-running warnings;
- shutdown-before-disconnect and sleep blocking;
- controller/display switching;
- generic errors, confirmations and long-running operation dialogs.

Do not claim an absent popup exists or that importing a shared component migrates
every call site. Preserve confirmation/cancellation callbacks, required messages
and action guards. Changes to detection, policy, DRM/PCI/USB4, Gamescope, process
killing or shutdown behavior are outside this UI task. Record runtime findings
separately; tiny UI-facing fixes need explicit scope and tests.

## Before-merge checklist

- [ ] Approved palette, repository status assets, no Unicode/emoji substitutes.
- [ ] Header/footer inside usable bounds; only body scrolls with long content.
- [ ] Source-rendered cases at 828x466, 1280x720, 1280x800 and 1920x1080.
- [ ] Connecting, long-delay, success, disconnect-ready, disconnect-blocked,
      generic warning and confirmation captured; fixture evidence labeled.
- [ ] Text wrapping, icons, visible focus, footer and expanded details inspected.
- [ ] Progress animation checked over time; reduced-motion counterpart checked.
- [ ] Completion dwell, interaction hold and stale-result behavior tested.
- [ ] D-pad/A/B, touch, details scrolling and opener restoration tested or native
      gaps explicitly recorded. Browser keyboard tests are not Decky proof.
- [ ] No duplicated warnings, fake progress, hidden required evidence or changed
      runtime safety behavior.
- [ ] Relevant regression tests, typecheck/build and final combined checks pass.
- [ ] Migration inventory, exact revision, screenshot paths and deviations reported.

Native acceptance requires an actual Ally capture/readback of the new build.
Until available, say “source preview passed; native validation pending.” Do not
reuse the user's before photo as evidence that the revised popup fits.

## Implementation checkpoint: shared-popup-system

This checkpoint is a partial implementation, not all-popup acceptance. Baseline
`2946d66`, with the documentation contract cherry-picked as `e4b9b7a`.

`StatusIcon` in `src/readiness-row.tsx` now delegates to the existing
`CommandCenterIcon` status assets. Waiting uses the existing unknown icon with
cyan pulse only in the primary status; diagnostic rows stay static. Entry and
color transitions honor reduced motion. Exit animation is not implemented:
`showModal.Close()` immediately unmounts and does not invoke close callbacks;
no replacement lifecycle is introduced just to animate closing.

| Surface in this baseline | Migration state and next owner action |
| --- | --- |
| Connection live panel | Shared PopupFrame, bounded header/footer, scrolling details, elapsed time, current check, compact delay and persistent cable guidance implemented. Source preview passed; native navigation pending. |
| EgpuConfirmModal wrapper | Shared brand/palette and bounded body implemented; retains native ConfirmModal and forwards callbacks, disabled/destructive/alert/middle props. Native chrome geometry and focus remain unverified. |
| showSafeDisconnectConfirmation (shutdown/return), showDisconnectConfirmation, showGameCloseDialog, showBlockedAttempt | Baseline still native ConfirmModal. Claude's separate PR276 a5963e9 adopts wrapper at these four sites; not integrated in this checkpoint. |
| showSupportBundlePreview, showPresentationPreparationConfirmation, showAutomaticDockConfirmation, showControllerDisplayConfirmation, showProcessReleaseConfirmation (force/nonforce), showDiagnosticLoggingConfirmation | Unmigrated; src/index.tsx owner Claude must agree and implement call-site adoption while preserving each action and consent. |
| showPresentationPreparationBlocked | Existing toast, not a modal; unchanged. Do not claim modal migration. |
| Sleep warning | Existing inline/toast visibility flow and game-close guard; no independent sleep modal is fabricated. Runtime integration remains with Claude. |

Tests execute the real LivePanel effect with a deterministic clock: success dwell,
expiry and phase changes, expanded details, pointer/keyboard/focus/native handler
interaction, and unmount. These establish handler behavior, not physical gamepad
routing. Focusable's supported onGamepadFocus/onGamepadDirection/onButtonDown
signals renew the dwell without intercepting events. Controller propagation,
D-pad/A/B, details scrolling and opener restoration still need native validation.

`scripts/popup_system_preview.mjs` captures seven cases at four viewports, each
with default, expanded and scrolled variants under `out/popup-preview/`.
ConfirmModal chrome is explicitly a fixture because Decky discovers its actual
implementation at runtime. Browser bounds on that fixture are not native bounds
proof. Connection captures use the actual PopupFrame. Motion and reduced-motion,
footer focus, expanded-details persistence and one-minute copy are asserted.

The additive optional `displayPending` contract was agreed with the connection
status owner: true only for fresh ready_display_pending; suppress delay warnings
for settled eGPU/TV-off waits. Freshness still overrides presentation and this
flag never means completed display activation. Model tests cover this half;
the source owner's separate commit must be combined before claiming end-to-end.

Remaining acceptance: combined call-site migration and per-operation status
contract; actual native chrome/controller validation; exit animation decision;
reciprocal review, integration preflight and final-head CI. No installation or
hardware action was performed.
