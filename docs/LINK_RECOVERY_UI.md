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

## Backend guard

PR #301 at `0f1244c` lacked an atomic recovery guard. Its RPC assesses the
attempt latch, then awaits user resolution before calling `recover`; `recover`
sets the latch but does not reject an already reserved attempt. A local fake-port
reproduction synchronized two callers after assessment and recorded two
`restart_gamescope_session` commands, both reporting `link_recovery.trained`.
No hardware commands were executed by this reproduction.

The service now reserves one attempt atomically at the command boundary, before
any disturbance. Concurrent RPCs that already passed assessment cannot both run.
The in-flight guard remains held through observation and restoration, including
transport loss; a finally block releases it. The attachment latch still prevents
another attempt until transport loss is observed. Tests synchronize two actual
RPC callers after assessment and verify exactly one restart. Direct duplicate
calls and transport loss during execution also have regressions.

Ronnie explicitly authorized taking over PR #301 on 2026-09-11. Work continues in
`egpu-recovery-fix` on `codex/integration-egpu-recovery`, preserving Claude's
original checkout and history. The hub records the maintainer override.

## Display detection and positioning

Both recovery confirmation and attachment progress are centered on the viewport.
The attachment host changes position only; expanded content scrolls within the
body so it cannot paint over footer actions. Checks cover compact and expanded
states at both viewport sizes. Steam's native host remains a device validation.

Desktop mirroring is a saved presentation preference, not proof of present HDMI
readiness. `_g1_hdmi_ready` currently requires a verified G1 and exactly one
connected external connector with an EDID hash. A working picture with an
unready Re-Gear status could indicate a stricter-check false negative; this has
not been established by the captures. No display guard is bypassed here.
Existing readiness regressions cover a TV remaining off beyond the timeout and
becoming ready when it is later detected. This does not promise a picture on an
undetected or powered-off TV.

Recovery confirmation uses scoped viewport centering and stays in the main screen. Browser checks assert both center coordinates within one pixel at both sizes. Typecheck and build pass; frontend suite: 636 passed, 1 skipped, 0 failed. Native Steam host positioning remains a device check.

Combined validation: 2,972 backend tests passed (109 skipped); architecture and compileall passed. Frontend: 636 passed, 1 skipped; typecheck, bundle build and package checks passed. Source previews verify both popup centers, preserved compact dimensions, expanded body clipping/scroll and Hide behavior. No new installer was produced or installed; no additional hardware mutation was performed.


0.3.80 native validation: installed files matched fd77f20 and its ZIP. One explicitly user-authorized installed Decky execute_link_recovery(true, session_restart) request logged link_recovery.trained at 08:51:45.894 on 2026-09-11, followed by automatic TV transition at 08:51:48.836. The GPU arrived without Plasma/KWin; Ronnie confirmed TV picture, audio and controls. The reply closed during Steam restart and was not retried. Evidence snapshot SHA256 d88af5ea066b7d29d040ad5ec3a5c070fa0be231cc8843a2221542ba316fcf77 is retained locally. Native sidebar access was not established: Ronnie could not see the readiness card.

0.3.81 adds the same guarded action to the attachment popup footer, so recovery does not depend on finding the sidebar card. It preserves Hide/Details and centers both dialogs. No offer means no extra footer row; when offered, retry stays visible without scrolling. Simulated actual-component tests cover popup cancellation returning to progress and one confirmed dispatch. Native button navigation and centering remain the next supervised check.

