# Confirmed eGPU detection retry

The eGPU readiness card offers **Retry eGPU detection** after two minutes only
when current evidence shows a connected transport, a missing GPU, and no game
running. Confirmation requests the existing `session_restart` backend strategy.
Opening the card, polling, cancelling, and closing the dialog issue no recovery.
The confirmation rechecks backend eligibility; stale evidence prevents execution.
An interrupted RPC reply is inconclusive and never triggers an automatic retry.

This implements the player action against PR #301's schema-version-1 RPCs.
An older backend leaves the action hidden. It does not implement automatic
session restarts, a Desktop round trip, or permission to disconnect the cable.

## Evidence and limits

The controlled experiment is recorded in branch
`codex/desktop-attach-experiment`, commit `b9c9880`,
`docs/DESKTOP_ATTACH_EXPERIMENT.md`. A supervised plain Gaming session restart
preceded G1 PCI arrival without Plasma running. This supports an explicit
recovery option; it does not establish the underlying kernel cause or repeated
reliability. The existing 0.3.79 installer and experiment captures are preserved.

Model tests cover strict schema handling and honest result messages.
`scripts/link_recovery_preview.mjs` exercises the actual component against mocked
Decky APIs at 828x466 and 1280x720: no command on mount/cancel/Escape, fresh denial,
expired evidence, duplicate confirmation, and lost reply. It compares existing
card geometry against baseline `0ef9325`. Outputs are in
`out/link-recovery-preview/`. These are simulated host checks, not native
controller or installed-device validation.

## Backend prerequisite

PR #301 at `0f1244c` still needs an atomic recovery guard. Its RPC assesses the
attempt latch, then awaits user resolution before calling `recover`; `recover`
sets the latch but does not reject an already reserved attempt. A local fake-port
reproduction synchronized two callers after assessment and recorded two
`restart_gamescope_session` commands, both reporting `link_recovery.trained`.
No hardware commands were executed by this reproduction.

The UI prevents duplicate clicks in one mounted component, but backend protection
must cover multiple callers. Reserve one attempt atomically before the first
await leading to execution, release in-flight state reliably on all exits, and
keep the attachment attempt latch consumed after a disturbance. Add concurrent
RPC regression coverage and verify interaction with existing transition guards.
Backend ownership remains with the PR #301 owner; this UI branch does not change
those files. Do not install the combined candidate before this prerequisite and
integration checks pass.

Recovery confirmation uses scoped viewport centering and stays in the main screen. Browser checks assert both center coordinates within one pixel at both sizes. Typecheck and build pass; frontend suite: 636 passed, 1 skipped, 0 failed. Native Steam host positioning remains a device check.

