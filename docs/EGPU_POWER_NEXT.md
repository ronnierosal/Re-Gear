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
adds the request coordinator with backend-owned progress. Both descend from the preserved checkpoint.
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

## 0.3.111 trial protocol, prepared 2026-09-15 while the device was offline

The 0.3.109 Safe Disconnect stopped after the portable return with the eGPU
still bound to amdgpu and both inhibitors held, and the only record of where it
stopped -- `_whole_dock_trial_status`, served by
`get_egpu_disconnect_status("whole_dock_trial")` -- was never read. It lives in
the plugin process; installing anything restarts that process and discards it.
So the order below is not optional.

1. **Read first, install nothing.** From the dev machine:
   `ssh -N -L 19224:127.0.0.1:8080 -i ~/.ssh/hdm_ally_deploy_v2 deck@steamdeck.local`
   then `node scripts/probe_whole_dock_trial_status.mjs http://127.0.0.1:19224`.
   The probe is read-only by construction and a test pins that. Record
   `phase`, `release_stage`, `release.code`, `arm_stage`, `arm_code`, `busy`,
   the pending localStorage record, and `sleep_guard`. Port 19223 is another
   agent's CDP session; do not reuse it.
2. **Then install 0.3.111** (`out/Re-Gear-0.3.111.zip`, revision 880d941,
   sha256 4f90c8d4...2fffa). Not 0.3.110, which has the executor-start race.
   The restart releases both inhibitors and the first Command Center open
   retires the old-format pending record with the "could not confirm" notice.
3. **Safe Disconnect, captured.** Before the press: `systemd-inhibit --list`,
   `lspci | grep -i vga`, the newest `/home/deck/homebrew/logs/Re-Gear/*.log`
   tail. Press. After Gaming Mode returns, run the probe again before opening
   anything else, then open the Command Center and record what the control
   says. The disconnect has not succeeded on any build since 0.3.98; the one
   route-relevant backend change since is `peripherals.py` eaa7684, which makes
   a docked controller visible where 0.3.98's parser hid it. If the probe shows
   a refusal, `release.code` names it; if it shows `trial_running` with
   `in_flight` true, the worker is blocked and a kernel-side wait is the only
   place left.
4. **Disconnect and sleep, only if step 3 completed.** Same capture. The press
   should read readiness, refuse if `retained_inhibitor` is true, disconnect,
   and either finish the sleep in the same panel or -- if Gaming Mode restarts
   -- have the next panel claim `take_pending_sleep` and finish it. Record
   whether the handheld slept, whether it woke, and whether a closed game was
   reopened after the suspend call returned.

Nothing in this section is a hardware result. It is the plan for getting one.

## Safe Disconnect succeeded on 0.3.112, 2026-09-15 18:26 PDT (hardware result)

Installed 0.3.112 (c80ffff) at 18:26:16 with the eGPU docked and the TV
active (`mode=tv_docked game=idle`). The leftover `release_intent` claim from
the 0.3.109 attempt had already been archived automatically when the dock
came back after the reboot (`claim_stage` read `none` at 18:24). Safe
Disconnect pressed ~18:26:24. Read from the running plugin at 18:26:54 by
`scripts/probe_whole_dock_trial_status.mjs`, before the Command Center was
opened:

- `whole_dock_trial`: `dock_teardown.software_down`, `ok: true`,
  `software_down: true`, `phase: dock_teardown`, `release_stage: removed`,
  `release.code: live_disconnect.removed`, `display_release.released`,
  `released: true`, `display_released: true`, `filter_disarmed: true`,
  `in_flight: false`, request `2eb468cdc6d14feea35d61719d1b8df0`.
- `whole_dock_record.claim_stage: software_down`. Pending localStorage record:
  none. `lspci`: no `08:00.*` -- the Navi 33 and its audio function are off
  the bus.
- Journey: `completion.explicit_result_required` 18:26:24,
  `audio.restore_portable` 18:26:25, `completion.portable_held` 18:26:30,
  gamescope restarted 18:26:31, `connection.waiting_for_pci` 18:26:32,
  `completion.portable_released` 18:26:33, sleep guard
  `presence=absent active=False` 18:26:34. Press to removal about 10 s.
- One Handheld Dock Mode inhibitor still held afterwards: the trial's own
  lease, retained by design after a successful software removal.
  `get_sleep_readiness` reports `retained_inhibitor: true` and
  `sleep.available` (eGPU absent). Sleep is therefore blocked until that lease
  is released by a proper handoff or the plugin restarts; the
  "Disconnect and sleep" press refuses on this fact rather than suspending
  into it.

First recorded successful disconnect on any build since 0.3.98. The 0.3.109
failure of 2026-09-14 did not reproduce and its cause remains unknown; its
in-memory record was lost to the reboot. Software removal is not clearance to
unplug; the enclosure remains powered.

## Steam power surface, read-only probe on device 2026-09-15

Run by `scripts/probe_steam_power_surface.mjs` against the live Ally
(0.3.113 installed, SharedJSContext). Enumeration only: member names and
`typeof`, nothing invoked. This decides whether "safe disconnect first" can be
attached to Steam's own Sleep and Shutdown buttons.

**Sleep: a real lease exists, as the ADR describes.** The suspend store carries
`BlockSuspendAction:function` and `m_cSuspendBlockers:number` -- the counted
blocker Steam checks before preparing -- alongside `OnSuspendRequest`,
`RequestSleep`, `OnPrepareForSuspendProgress`, `OnSystemResumedFromSuspend`.
Interception is therefore possible and is already in place.

Three members the adapter does not name, recorded because they bear on whether
the single patch point is sufficient: `OnRequestSuspend:function` (distinct from
`OnSuspendRequest`), `InitiateSleep:function`, and Steam's own confirm-sleep
modal state (`SetShowConfirmSleepModal`, `ShowConfirmSleepModal`,
`m_bShowConfirmSleepModal`, `BShowSuspendResumeDialogs`). Whether any of these
is an alternate entry that reaches a suspend without passing the blocker check
is NOT established by an enumeration; it needs the function bodies read, and
until then no claim either way belongs in the UI.

**Shutdown: no equivalent lease found.** `SteamClient.System` exposes
`ShutdownPC`, `RestartPC`, `SuspendPC`, `RebootToAlternateSystemPartition` --
methods that cause power actions, not hooks that hold one. The shutdown-shaped
members found are observers:

- `AddShutdownCallback:function` with `m_rgShutdownCallbacks:object`
- `OnShutdownStart`, `OnShutdownDone`, `OnShutdownState`, `OnShutdownFailed`,
  `GetShutdownState`, `ClearShutdownFailure`, `m_shutdownState`

`BlockServerShutdown_Bool:number` and `DeviceCanPowerOff_Bool:number` are
numbers, not callables -- the shape of settings keys, not a live blocker.

Nothing here has the shape of `BlockSuspendAction`: acquire, increment a count
Steam consults before proceeding, return a release. `OnShutdownStart` fires
when a shutdown has begun, which is after the point where a disconnect would
have to run. So on this Steam build, "disconnect first, then shut down" cannot
be attached to the system shutdown button without racing a power-off, and must
not be attempted on the strength of a callback name. Whether
`AddShutdownCallback` can veto or defer is unknown for the same reason as
above; that is the only remaining question worth a follow-up probe.

## Why the portable return kept refusing, 2026-09-15 (root cause)

Two Disconnect + Sleep presses on 0.3.113 and 0.3.115 both refused with
`dock_teardown.portable_return_unverified` -- on screen, "The return to the
handheld screen could not be verified". 0.3.114 added the blocker code to the
payload, and the second press named it: `portable_return {kind: blocked, code:
observation.stale}`.

`TransitionOrchestrator` plans against one observation and re-observes before
acting; if the snapshot's content-hash generation moved in between it refuses
as `observation.stale` (transition_orchestrator.py:148). On a dock that has
just attached that hash moves constantly -- link recovery, audio preflight,
attach readiness and the TV transition each change it -- so a press issued
while the dock is still settling can lose the race between `preview()` and
`execute()`. Both failing presses were within ~10 s of `attach.ready_idle`;
the successful 0.3.112 Safe Disconnect was issued onto an already-settled
dock after a plugin restart.

This is not a refusal of the action: it says the world moved while we were
deciding. `_return_portable_before_disconnect` now re-plans up to
`PORTABLE_RETURN_ATTEMPTS` (3) times, waiting
`PORTABLE_RETURN_SETTLE_SECONDS` (1 s) between attempts, and only for
`blocked/observation.stale`. Every other blocked or failed outcome still stops
on the first answer. Each attempt calls `preview()` again rather than reusing
an approval token, so each is independently gated and a readiness that
genuinely went away refuses at the preview. The recorded outcome carries
`attempts`.

This affects every route through the portable return, not just sleep: Safe
Disconnect and Disconnect + Shutdown could lose the same race.

## First complete disconnect on the sleep route, 2026-09-15 21:11 PDT

0.3.116 installed 21:11:34; Disconnect + Sleep pressed ~10 s later, while the
dock was still settling -- the case that refused twice before. The portable
return PASSED this time (`portable_return {}`, no stale blocker recorded), and
the teardown completed: `release_stage removed`, `live_disconnect.removed`,
`display_release.released`, `filter_disarmed`, `software_down true`, eGPU off
the PCI bus, claim `software_down`. The re-plan fix did its job.

The sleep itself did not happen. The trial ended at `phase power_verification`
with `dock_power.request_unverified`, `power_requested false`, and the system
journal records no suspend attempt whatsoever.

Ruled out by reading the device: the plugin runs as uid 0, so
`dock_power.root_required` is not it; and the only non-`delay` inhibitor
present afterwards is our own retained trial lease, restored by the handoff
after the refusal. The handoff verifies every lease reports `active() is False`
immediately before submitting, so both were down at submit time.

What the cause is remains unknown, because `_run_sleep_request` submitted via
`lambda r: SystemSuspendCommandRunner().request_suspend().requested is True`,
which collapsed a four-way result into a boolean. A refused submission, a
timeout, an unavailable command and a privilege failure all arrived as the same
`request_unverified`.

That is now fixed rather than guessed at. `Plugin._submit_suspend` records
`suspend {requested, code}` on the terminal payload, and the control appends
the reason to the refusal. `SystemSuspendCommandRunner` additionally
distinguishes the one refusal with an actionable cause -- a block inhibitor
still registered with logind when the request was made -- as
`dock_power.suspend_inhibited`, classified from the command's stderr without
any of that output crossing the boundary.

Leading hypothesis, not established: logind may not have dropped our inhibitor
registration by the time `systemctl --check-inhibitors=yes suspend` ran. The
lease's own process had exited and `active()` reported false, but the D-Bus
side of that release is not necessarily synchronous with process exit. If the
next press reports `suspend_inhibited`, that is the answer and the fix is to
wait for logind to agree before submitting, not to drop `--check-inhibitors`.
