# Sleep and shutdown lifecycle implementation

## Integration status — September 14, 2026

PR315 and PR316 are merged. They supply backend power handling and the request
coordinator; their former branch-only status below is historical. PR335, merged
as `a16ba34c336cfe5813f9dceb15d10f7df029f928`, additionally disables software
reconnect at the RPC boundary. These are source integrations, not installed
power-button, sleep/wake or charging qualification. Older installed packages
do not inherit the new gate.

The UI primary separately owns combined button mounting, original-intent routing
and reconnect removal. PR329's 0.3.107 artifact and the separate PR333/334 power
stack must not be described as one installed journey. Use the
[lifecycle acceptance matrix](wiki/technical/egpu-lifecycle.md) and preserve the
[0.3.98 baseline](EGPU_0398_CHECKPOINT.md). No new hardware trial is established
by this documentation reconciliation.

## 2026-09-14 inhibitor findings and lifecycle acceptance matrix

PR315 (power backend) and PR316 (coordinator) are now merged in source at
9421c6f; the historical implementation/installation notes below predate those
merges. Source merge is not an installed sleep/wake result. PR333 is the separate
button consumer, PR334 the read-only context producer, and PR329 the UI candidate.

### The two recorded Linux inhibitors

The 0.3.98 capture at 2026-09-13 04:05:45 UTC recorded PIDs 37189 and 12372,
both named **Handheld Dock Mode**, `what=sleep`, `mode=block`. Both use the
reason “The attached eGPU is known to wake this handheld immediately from sleep.”
The code has two owners: `Plugin._sleep_guard` is the background controller;
`Plugin._whole_dock_trial_lease` is the retained disconnect-transaction lease.
The identical labels alone cannot assign each historical PID to its owner;
live PID/parent ancestry is still required for that exact mapping.

Both are releasable process-held leases, not permanent kernel/firmware blocks.
The merged handoff releases the actual owned lease(s), pauses background
reacquisition, submits one sleep request, and restores protection after the
observed result or failure. A failed release remains a real block; software
support is not proof that both installed processes release cleanly. When there
is no retained transaction lease, ordinary keep-connected sleep only releases
the background lease. Do not invent a second lease for that case.

Steam's `BlockSuspendAction` is an additional frontend blocker, distinct from
these two Linux processes. The old interception warns; it does not retain an
OS request that automatically resumes when an inhibitor disappears. The intended
prompt can hold **application intent** pending the user's choice, then release
owned blockers and submit one selected request. It must not queue a suspend
first and assume cancellation or inhibitor release controls it afterward.
`OnSuspendRequest` is Sleep-only, not a Sleep/Shutdown action enum.

Report these findings before building the prompt. Offer **Sleep connected** only
when the installed handoff can release its actual blockers; if it cannot, do not
promise that choice. Disconnect-then-sleep also needs a working release of the
retained transaction lease, so it is not an automatic workaround for an
unreleasable lease. No forced suspend or process killing is part of validation.

### Expected results and evidence

Charging continuity is an acceptance requirement, not an incidental side effect.
Disconnect releases data/GPU resources; it must not intentionally disable dock
power delivery while the cable remains attached.

| Journey | Required result | Evidence / remaining check |
| --- | --- | --- |
| Safe disconnect, cable attached | Handheld usable; eGPU data path down; dock still supplies charging power | Golden 0.3.98 software-down/handheld result; user reports retained charging. |
| Safe disconnect, then sleep, cable attached | Sleep/wake on handheld; charging retained; no software reauthorization | User reports desired charging retention; monitored 0.3.98 sleep was blocked. Controlled sleep/wake and power evidence remain pending. |
| Safe disconnect, then shutdown, cable attached | Clean shutdown; dock charging retained | User-confirmed clean manual shutdown and continued charging; preserve this valid observation. |
| Sleep connected, then wake | Existing eGPU/TV/audio/controls usable; record recovery-attempt count before/during/after wake | Not yet captured in the requested controlled journey. “Works after recovery” and “works without recovery” are separate outcomes. |
| Physical unplug/replug after safe disconnect | Existing automatic-TV behavior preserved | Golden 0.3.98 physical cycle; no software reconnect substitute. |

For charging checks record external supply `online`, battery capacity/status and
charge/current trend when available, plus the user's charging indication.
“Not charging” at a full battery alone is not loss of power delivery. Absence of
post-shutdown telemetry is not proof of failure; use the device indicator/user
observation and label the evidence source.

### Pending connected sleep/wake capture

Before sleep record installed version/revision, boot identity, game/display/GPU
state, inhibitor owners, and automatic-link-recovery state/attempt count. Keep
a timestamped local journey capture across SSH loss, then record suspend/resume
events, GPU/TV/audio/controls, and recovery transitions/count after wake. The
existing recovery policy is bounded at two attempts with a ten-second interval;
do not reset counters to make the trial pass. Report whether any attempt was
consumed, not just eventual success. Do not run software reconnect.

On 2026-09-14 the attempted read-only preflight could not resolve steamdeck.local;
the last known address 192.168.1.198 also timed out. No sleep/wake operation or
current inhibitor observation was performed. Await the current reachable device
and a user who can wake it and confirm picture/audio/controls.

### Software reconnect is disabled at the RPC boundary

The 0.3.92 reauthorization timeout with unusual dock heat had no thermal telemetry.
`execute_egpu_disconnect(trial_action="whole_dock_reconnect")` now returns
`dock_reconnect.disabled` before a worker or hardware action can start, including
from `dock_teardown.software_down`. The action is absent from the backend allowlist
and no generic trial fallthrough dispatches it. Frontend removal remains with
the UI primary. Physical reattachment and ordinary auto-connect are unchanged.

## Accepted behavior

Preserve the [0.3.98 golden cycle](EGPU_0398_CHECKPOINT.md). Shutdown with an
active eGPU returns to handheld and runs the same resource/GPU/USB4 disconnect
before continuing the original shutdown once. A verified already-disconnected
dock does not repeat removal. Verified absent USB4 transport uses ordinary power
without requiring an idle game or a supported eGPU profile.

Sleep offers two explicit choices:
- Disconnect eGPU and sleep: use the same teardown, then continue Sleep.
- Keep eGPU connected and sleep: leave the existing connection untouched.

After the disconnect choice, the cable may remain attached for charging, but
software reauthorization/rescan/reconnect remains excluded. Physical unplug/replug
is the intended return path for that intentionally disconnected attachment.
Keeping an existing authorized connection through sleep is a separate choice.
Charging and healthy wake behavior remain hardware observations, not code claims.

## Current backend implementation

The implementation from `egpu-power-0398` is now merged through PR315; PR316
adds the backend-owned request coordinator. Both descend from the preserved checkpoint.
`Plugin._run_dock_power_request` routes ordinary, already-down, and active-dock
power. Already-down continuation currently requires the retained runtime in the
same backend process and fresh verification of its software-down claim/topology.
Runtime reconstruction after plugin restart is not implemented by this slice.
Ordinary absence uses the existing complete USB4-host reader; do not generalize
it to platforms without that evidence or to every non-GPU Thunderbolt dock.

`whole_dock_shutdown`, `whole_dock_sleep`, and `whole_dock_sleep_connected` use the
existing confirmed `execute_egpu_disconnect` RPC. Original intent is generated
before the background worker can restart the Gaming session. Teardown-bound
intent is durably consumed before power. Ordinary/already-down power consumes
its process-local request once and never restores it across backend restart.
A supplied correlation ID is action-bound and cached for that backend lifetime;
frontend restart must read status, not replay the power request.

Sleep now uses `run_observed_sleep`, the existing power coordinator and
`SleepLeaseHandoff`. It pauses the actual background guard and, after disconnect,
the retained transaction lease. The two are released only for the original
request. A local handoff phase separates lease protection from held mutation
admission after verified teardown; ordinary teardown still requires its lease.
The keep-connected/no-dock route uses only the background guard.

`SuspendObserver` establishes same-boot kernel success/failure counters before
submission. No counter evidence means no Sleep teardown. After a single ordinary
systemctl suspend request, the worker observes completion/failure and restores
its leases. Timeout/unreadable evidence remains unresolved even after restoration;
it is not cancellation of a queued job. Failed restoration is reported separately.
No resume path authorizes or reconnects hardware.

`power_requested` means submission only. Sleep `ok`/`sleep_cycle_observed` becomes
true only for an observed successful kernel cycle, not proof of a healthy TV,
audio, controls, charge rate, or duration asleep. The read-only `power_status`
request exposes pending/final sleep status. No UI-supplied capability booleans can
replace the request, observer or ownership checks. Historical static capability
restrictions are optional narrowing checks, not invented hardware certifications.

## Integration and validation remaining

Backend source has independent review and focused tests, including actual guard
objects across consumption, release, submission and restoration, both Sleep
choices, no-dock Shutdown, already-down Shutdown and correlation replay rejection.
The 49-test golden gate passes. The full Windows offline suite ran 3,523 tests successfully with 299 platform
skips. Independent core review ran 64 focused tests; final status review ran 27.
Linux-only checks and actual device behavior remain separate gates. The final
status defaults were additionally covered by focused tests after the full run.

The UI primary owns separate Steam Sleep and Shutdown interceptors and the sleep
choice. `OnSuspendRequest` is not a Sleep/Shutdown enum; its argument can suppress
actual suspend. A read-only loaded-source probe is available at UI commit633d7ec.
The Ally was unreachable for source readback during this implementation. Production
UI interception/mounts are not yet integrated, no new ZIP is installed, and native
blanket interception is not removed before the replacement path exists.

Run a focused supervised sleep/wake trial when the combined candidate is ready.
Preserve the successful manual shutdown evidence below; do not repeat it without
a changed path or a concrete gap. No software reconnect trial is part of this work.

## Manual sleep trial after live disconnect, 2026-09-13 04:05 UTC

Installed build remains 0.3.98. User authorized a live software disconnect,
manual sleep with cable attached, then wake/readback; no software reconnect.
Fresh preflight showed idle, TV active and no retained dock claim. The first
script did not dispatch because it required a preview token unavailable after a
completed trial. The second used the existing backend current-attachment path;
its response channel closed during session restart, so it was not retried.
Fresh capture verified dock_teardown.software_down, busy=false, ok=true,
live_disconnect.removed, display_release.released and durable software_down
claim. User then attempted manual sleep and reported it was blocked.

Read-only systemd-inhibit at 04:05:45 UTC showed TWO Handheld Dock Mode sleep
block inhibitors (PIDs 37189 and 12372). Other listed inhibitors were ordinary
delay inhibitors. GPU remained absent and the software_down claim remained.
This establishes the installed build still blocks sleep after successful dock
removal; it does not establish a wake or firmware problem. No sleep/wake occurred,
no inhibitor was killed, and no force-suspend or software reconnect was attempted.
Battery status reported Not charging; that alone does not establish power loss
or failure of charging retention (capacity/external-power evidence was not read).
Capture: whole-dock-disconnect/out/0398-disconnect-1789272173165.jsonl.

Next: finish the two-lease production handoff already under implementation, then
run a focused sleep/wake trial. Do not rerun disconnect merely to reconfirm this
same blocker. The automatic-TV and physical reconnect golden evidence stands.

## User-reported shutdown and startup outcome, 2026-09-13

Following the verified live disconnect and blocked manual sleep attempt, Ronnie
reports that manual shutdown was clean and the G1 continued charging the Ally.
He also reports normal startup with the G1 disconnected, and a separate described
safe-disconnect/shutdown/power-on sequence automatically returning to the TV.
Exact cable changes between those startup observations were not captured; do not
infer a software reconnect or attribute the outcome to uninstalled power code.
These are successful user-observed manual workflow results on the last verified
installed 0.3.98 baseline, not an automated shutdown continuation test. Preserve
this evidence rather than repeating the same shutdown sequence without a change.

Ronnie then requested the two-choice Sleep flow recorded above. Keeping an
already-connected dock through sleep is distinct from software reauthorization
after intentional disconnect. The latter remains excluded. Successful connected
sleep/wake is the user's expectation, not yet a recorded hardware result.
