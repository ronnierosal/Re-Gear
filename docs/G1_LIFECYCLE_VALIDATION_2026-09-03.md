# Ally X / GPD G1 lifecycle checkpoint — 2026-09-03

## ACTIVE MISSION

Repeatable idle Portable -> G1/TV -> Portable, including audio. Preserve the
shutdown-before-physical-disconnect rule. No live-removal or game-migration claim.

## Hardware observations

Installed base: `0.2.0`, revision `3a5d1620ddf8`; SteamOS `3.8.16
(20260716.1)`, kernel `6.16.12-valve24.5-1-neptune-616-gb2f7cfe85e45`.
Redacted captures are local under `out/remote-captures/`.

- 23:35 UTC: idle Portable, G1 absent.
- 23:38–23:39: candidate transport present, incomplete graphics/DRM identity.
  A transient inactive-sleep-protection toast appeared. Later photographs showed
  G1/TV ready and the system inhibitor Active. The standalone capture cannot
  observe the Decky-owned inhibitor. Do not infer persistent failure from it.
- Automatic docking was initially disabled; the maintainer enabled it.
- 23:42: both screens black, SSH reachable, Steam/Gamescope absent. Session
  service exit 126; journal: HDM launcher `/usr/bin/python3^M: bad interpreter`.
  CRLF in extensionless `bin/gamescope` prevented execution. This confirms a
  package defect, not a kernel fault. An accompanying
  `audio.external_sink_ambiguous` event does not explain the executable failure.
- Maintainer approved launcher repair and one session restart. Their interactive
  sudo command retained a backup and converted CRLF to LF. Verification confirmed
  only line endings changed, a valid shebang, and executable permissions. Manual
  service start was refused by the unit; its owning `gamescope-session.target`
  started successfully. Steam returned to the Ally. The installed build label
  remains the base revision but the launcher no longer matches the original ZIP.
- After acknowledgement of the failed transition, automatic docking retried.
  At 23:48 Gamescope was running; the maintainer confirmed TV picture/menu audio.
- At 23:50 **Prepare G1 disconnect** returned Steam to the Ally. Capture confirmed
  internal active, external connected but inactive, Steam/Gamescope running.
  Maintainer confirmed usable controls. Audio remained on TV despite
  `transition.succeeded`; PipeWire reported HDMI as configured/effective default.
  Protected Steam/PipeWire/WirePlumber clients remained; none were terminated.
- Maintainer manually selected Ryzen HD Audio Controller in Steam and confirmed
  sound on the Ally. No physical disconnect occurred.

## KNOWN GOOD PATH — DO NOT REGRESS

Preserve profile-bound Gamescope selection (`--prefer-vk-device 1002:7480`,
`MESA_VK_DEVICE_SELECT=1002:7480`) and the shared guarded transition engine.
The launcher must be executable and LF-only. A connected connector is not active
TV proof; human picture/audio and control confirmation remain required.

## Local corrections

The launcher lacked an explicit LF Git attribute; Windows checkout produced CRLF
and packaging copied raw bytes. Pin `bin/**` to LF, normalize launcher archive
bytes without rewriting source, and verify raw shebang/line endings and mode.
Regression tests exercise Windows/Unix inputs and deterministic ZIP provenance.

The automatic loop recorded Portable audio whenever display/render placement was
Portable, including G1-attached HDMI output. This can overwrite the saved Ally
sink before restoration and produce false `audio.already_selected`. This is a
reproduced code mechanism consistent with the live symptom; private saved state
was not read, so the exact live write remains unproven.

Baseline recording now requires a verified idle Portable session with no external
GPU/transport requirement and complete absent-client evidence. Fresh exact G1
identity rejects remembering/restoring its audio sink as Portable. Docking
preserves an existing valid baseline. Separate categorical audio-result events
report target and success without exposing sink names or device identifiers.
Tests cover three simulated cycles, poisoned baseline, partial attachment,
unknown/running games, and a different current non-G1 default.

## CURRENT FAILURES / OPEN QUESTIONS

- These fixes need a new packaged-build hardware test; do not reuse the old ZIP.
  Install detached after full shutdown, boot Portable, and select the desired
  Ally output before attaching so the baseline is refreshed.
- Legacy saved sink names lack provenance. If exact G1 identity is unavailable,
  a historically poisoned external name cannot be distinguished from a valid
  saved output. Removed-G1 recovery deliberately does not require G1 identity.
  The new attached-identity guard does not solve that legacy case.
- Default-sink verification cannot prove all existing streams moved or prevent
  later session routing changes. Verify audible menu sound after both switches.
- The UI could not hook read-only `OnSuspendRequest`; the system inhibitor later
  showed Active, but attempted-sleep warning delivery was degraded. No sleep test.
- Successful transitions still require acknowledgement before another action.
  Do not remove retry/journal safety gates without separate validation.
- Full poweroff, with human-observed fan/LEDs off, remains required before unplug.

## BACKLOG — OTHER AGENTS

Coordinate sleep-hook compatibility and transient-warning wording with UI/sleep
owners. Shortcut polish and successful-journal retirement are separate work.

## Next supervised test

Local verification: 819 backend tests passed with five platform skips; 66
frontend tests passed. Architecture, compileall, typecheck, Rollup, source package
contract, and whitespace checks passed. These are local gates, not hardware proof.

One action at a time: detached Portable audio baseline; automatic attach; TV
picture/audio; acknowledge; prepare disconnect; Ally picture/control/audio.
Inspect logs at each step. Repeat attached display/audio switching only when
current guards permit. Physical reconnect uses shutdown-before-disconnect.
