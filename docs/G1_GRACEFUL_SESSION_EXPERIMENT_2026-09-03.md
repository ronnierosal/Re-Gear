# Supervised graceful session stop — 2026-09-03

## Scope and installed build

The maintainer explicitly approved one graceful session-stop experiment and
temporary reversible systemd overrides after preflight exposed force escalation.
Installed Re-Gear 0.3.0 reports revision `9571a5ca3e5b`; fixed-file provenance
matched earlier in the session. G1 remained attached, game state was Idle,
internal display active and the connected external display inactive.

## Mechanism

Twelve active services belonging to the graphical session received exact temporary
`/run/user/<uid>/systemd/user/<unit>.d/zzzz-regear-graceful-experiment.conf`
drop-ins: `SendSIGKILL=no`, `TimeoutStopSec=20s`, and
`TimeoutStopFailureMode=terminate`. Effective values and normal TERM/CONT signals
were checked before one `systemctl --user --no-block stop gamescope-session.target`.
Existing native ExecStop and ExecStopPost behavior was retained, including Steam's
TERM handler and Gamescope's drm_janitor. PipeWire and WirePlumber were not stopped.
No driver unbind/reset, physical removal, shutdown, or force-kill was requested.

## Observed result

- Steam Launcher: stopping to stopped in 2.965 seconds.
- Gamescope Session: stopping to stopped in 2.120 seconds.
- SteamOS automatically started Gamescope approximately 0.200 seconds after its
  stop completed, then started Steam. The agent issued no recovery-start command.
- The bounded journal query returned no matching timeout, SIGKILL, blocked-task,
  drmModeAtomicCommit, amdgpu or pciehp symptom rows. This is bounded unprivileged
  log evidence, not proof that every kernel event was visible.
- Post-capture: Steam and Gamescope present, game Idle, internal display active,
  external display connected/inactive. Steam DRM and WirePlumber audio clients
  remained observed; client scan and protected render-selector evidence remain
  incomplete at this privilege level. No quiescent-GPU or removal-safety claim.
- All 12 temporary override files and the experiment manifest were removed.
  Native Gamescope 10-second / Steam 60-second timeouts and SendSIGKILL=yes were
  re-observed, with both services active and no pending jobs.
- The maintainer confirmed restored Ally picture, audio, and built-in controls.

## Interpretation and next step

One orderly userspace session stop succeeded with the G1 attached. This does not
reproduce complete machine shutdown or isolate the prior shutdown hang. Native
session re-entry prevented a sustained stopped-session observation; force-killing
these services is not supported by this result. Keep shutdown-before-removal.
Visible usability is confirmed. Next, design bounded capture of the actual
shutdown phase before another separately supervised poweroff. Do not disable native
session re-entry, stop audio, or widen teardown authority from this result.

## Local evidence

Ignored operator artifacts under `out/`: `graceful-session-before.json`,
`graceful-session-stop.json`, `graceful-session-after-stop.json`,
`graceful-session-lifecycle.json`, `graceful-session-cleanup.json`, and redacted
`remote-captures/capture-20260904T044253Z.json`. The fixed streamed experiment
script is retained locally as `graceful_session_experiment.py`; it is not a
product feature or a reusable authorization to stop sessions.

## Follow-up capture limitation

A read-only coverage check found 18 previous-boot records whose JSON MESSAGE was
an array, and no invalid JSON rows in that 2,000-row tail. The current classifier
labels non-string MESSAGE fields malformed; its earlier malformed_journal status
therefore does not establish corrupt journaling. The current-boot tail likewise
contains array-valued messages. Both bounded tails contain only sparse kernel
evidence. Review array-message handling and targeted shutdown coverage before
relying on the collector to diagnose another poweroff. No journal configuration
was changed.
