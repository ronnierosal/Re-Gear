# Supervised Ally session preparation — 2026-09-01

> Historical record: HDM was Re-Gear's former name; original wording is retained.

## Artifact readiness

This is local package evidence only. It does not prove installation, player
presence, G1 state, UI behavior, or any hardware capability.

| Role | Commit | Version | SHA-256 | Isolated validation directory |
| --- | --- | --- | --- | --- |
| Installed prior candidate | `cb1696c1b622db045223c9c3846127b1fdb72bb7` | `0.2.0` | `fbf7da6fccbbed8e908a09664298f849364f9fa0380e043a953a49daba71c818` | native install remotely observed; graceful retirement failed |
| Current held-local candidate | `49c826c5e7d896287abefdbb2a657ae1b2da516f` | `0.2.0` | `029ca3f2b5887ae0199845b8f21e0c8f5a35f408aa0627e7602bbfad1cea39a1` | `out/release-candidate.json` (manifest verified; one watched D2 lifecycle observation required) |
| Rollback baseline | `e73d249db5687f564043fe4b6f9f2fa04c2042ec` | `0.2.0` | `f9faae446cd8e61616bc0f3b3afa21961fb1b9f3fe4e87b858e1d8a9935ec519` | `out/validation-rollback-e73d249` |

The candidate was built from clean current main and its release-candidate
manifest verified its version, embedded revision, ZIP structure, and hash. The
rollback was rebuilt in a detached exact-revision worktree, not substituted from
the unrelated preserved `25802649` archive; its embedded revision and artifact
verifier passed locally with the observed baseline label `e73d249db568`.
The current candidate supersedes the installed `cb1696c` and the failed
executor-only `fd2d38f` follow-up. Before D2, create the paired candidate
record from this exact archive and re-verify both artifacts.

## Session scope and stop conditions

The player must be present with a known recovery path. Stop and preserve
evidence for display/input/SSH/network loss, unexpected Steam/Decky/Gamescope
restart, or provenance mismatch. Do not suspend, reboot, unplug the G1, restart
Gamescope, or change display/GPU/audio/controller state.

## Ordered hands-on stages

1. **D2 baseline/install — G1 physically disconnected.** Confirm handheld
   display, controls, network, Steam, Decky, and SSH. Capture redacted before
   state. Install only the candidate through Decky's native lifecycle; verify
   the QAM build label, one plugin instance, hashes/RPC schema, sleep lease, and
   unload/reload return to baseline. Capture redacted after state.
2. **D2a read-only gameplay observation — G1 still disconnected.** With the
   player watching, open HDM during one ordinary internal-screen game; verify
   controller usability and deferred Troubleshooting behavior. Observe at least
   fifteen seconds without claiming performance certification.
3. **D3 named G1-attach observation — separately scheduled.** The player
   naturally attaches the G1 and retains visible control. Capture before/live
   redacted snapshots; inspect exact identity, TV/EDID, Gamescope/render state,
   game state, blockers, and sleep layers. Keep the G1 attached.

No D4 warning/support acceptance, D5 process/presentation operation, D6 sleep,
unplug, controller/audio, or display transition is in this session.

## D2 result — native install observation

**Status: Remotely Observed; D2 lifecycle acceptance incomplete.** With the G1
absent and the game Idle, the player used Decky's native installer to install
the candidate above. The immediate bounded read-only capture reported
`0.2.0` / public revision `cb1696c1b622`, exactly matching the candidate,
with no collector errors, one active internal display, and one Steam,
Gamescope, and plugin-loader process. Decky remained active with zero service
restarts, logged its frontend import event, and HDM subsequently reported
Portable/Idle/certified with no blockers.

The native install did expose a stop condition for later lifecycle acceptance:
Decky waited five seconds for the prior HDM process to unload, then sent
SIGKILL before loading the candidate. This establishes neither graceful
unload/reload return-to-baseline nor controller/input/RPC health. Do not begin
D2a or attach the G1 from this result. Preserve the logs and diagnose the
shutdown timeout in a separately approved local change before advancing.

## Follow-up result and current candidate — graceful retirement

**Status: Remotely Observed failure for `fd2d38f`; current correction
Implemented locally; Hardware Validation Required.** Local commit
`fd2d38f2fa0434f70c20a4759a1a9b606861f8f0` shuts down HDM's event-loop default
executor only after its owned lifecycle tasks are cancelled and its sleep guard
is closed. This releases idle workers created by HDM's `asyncio.to_thread`
calls before `_unload` returns. A deterministic regression test confirms that
the executor is shut down during unload. A watched native install of that exact
package still required Decky's five-second SIGKILL, so the executor-only theory
is insufficient.

The current local-only package is `49c826c5e7d896287abefdbb2a657ae1b2da516f`,
version `0.2.0`, SHA-256
`029ca3f2b5887ae0199845b8f21e0c8f5a35f408aa0627e7602bbfad1cea39a1`.
It starts the Docked-iGPU watcher only for the exact Running Docked-iGPU
placement, instead of starting it in the portable/Idle D2 baseline. The latter
unnecessary task is strongly implicated by the absence of the later
sleep-guard-release log and by local cancellation isolation, but the remote
process had no definitive thread dump.

Before D2a, the player must install this exact current package through Decky's
native lifecycle with the G1 disconnected, observe one unload/reload, and stop
if Decky again needs SIGKILL or any display/input/session issue appears. No G1
attachment, sleep, display, GPU, audio, controller, USB4, or process action is
authorized by this local correction.
