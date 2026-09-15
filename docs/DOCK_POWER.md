# Disconnect before sleep or shutdown

Status: backend shutdown composition implemented; UI wiring and hardware
validation are pending. Sleep is explicitly refused before any teardown until
its capability, inhibitor handoff, and thermal validation gates are satisfied.
No new native power-button interception is installed.

## Backend workflow

The existing `execute_egpu_disconnect` backend entry accepts two additional
confirmed trial actions: `whole_dock_shutdown` and `whole_dock_sleep`. The caller
must provide the existing explicit display-release and trial confirmations.
The sleep action currently returns `dock_power.sleep_unverified` without changing
hardware. This backend route is specifically for an attached eGPU; no-eGPU
normal power routing remains the later UI/native-integration responsibility.

For shutdown, the backend creates an immutable original request with an opaque
operation ID, boot/process session, and deadline of at most five minutes. It then:

1. Acquires the existing dock mutation admission and sleep inhibitor.
2. Returns to verified idle Portable operation using the existing transition.
3. Claims the exact dock and durably binds the original shutdown choice before
   resource release. A failed bind retains the claim and stops before release.
4. Runs the existing GPU/audio release, USB branch removal, and USB4 tunnel
   deauthorization, including independent completion verification.
5. Rechecks matching software-down ownership, complete topology/storage,
   downstream function absence, deauthorization, idle game state, and Portable
   placement. Unload, changed evidence, or timeout refuses continuation.
6. Atomically consumes the original power intent, rechecks, and invokes the
   existing fixed ordinary system-poweroff adapter once while admission is held.

A successful command response reports `power_requested`, not completed shutdown
or physical unplug clearance. The initiating frontend may disappear during the
session transition; the backend owns continuation. A duplicate RPC cannot start
another teardown while the durable dock claim remains. A backend restart never
reconstructs or resumes the original power command.

The standalone `DockPowerCoordinator` supplies once-only/expiry guards.
`DockPowerIntentStore` uses bounded strict records, the existing claim lock,
secure descriptor-relative access, and flushed consumption records. Failed or
ambiguous submission never causes an automatic retry or software reconnect.

## Preserving automatic connection after reboot

The shutdown transaction rechecks its live sleep inhibitor before returning to
Portable, after that transition, and before resource release and dock teardown.
The same live check participates in runtime mutation admission and both power
continuation preflights. A lost or unreadable inhibitor stops further work;
successful initial acquisition alone is insufficient. This does not eliminate
the need for platform validation of inhibitor lifetime during a real shutdown.

The response preserves verified `software_down` separately from
`power_requested`. A failed or uncertain power submission can therefore report
software removal without reporting successful shutdown or physical unplug
clearance. Removal is an observation from this transaction, not proof that the
enclosure is powered off.

The dock claim lives in persistent storage, so command acceptance does not clear
it. A canceled shutdown in the same boot remains inhibited. On a later automatic
connection attempt, the backend can archive an exact software-down claim only
when a matching consumed shutdown intent proves a different boot and fresh
observations establish the matching authorized dock/transport, idle supported
host/session, settled helper work, and no inner recovery or transition journal.
The current attachment generation must be stable; it need not equal the old
boot's generation. Ordinary mutation admission is retried after archival.

If a validated prior-boot shutdown claim is otherwise eligible but the read-only
session-helper audit explicitly reports unsettled work, the automatic TV path
can use its existing single pre-plan retry. Fresh identity, display, consent and
idle evidence must still match. This shares the existing retry budget; it does
not reset it. Unknown audit failures, changed claims and a transition that has
already started never qualify. The launcher preserves only the audit command's
exact known unsettled response on exit 1; failed mutation commands remain failed.

This path performs no device writes, does not reset recovery budgets, and cannot
retire ordinary disconnects, sleep intents, same-boot shutdowns, unconsumed or
missing intents, or failed reconnect records. Those continue to require their
own evidence-backed recovery. Consumed power records remain as audit evidence.

## Sleep and UI work remaining

The read-only `dock_power_capabilities()` delivery contract describes this
build's implementation status. It performs no discovery or hardware action and
does not approve a request. Its versioned, JSON-compatible payload always sets
`authorizes_action: false` and each action's `actionable: false`. Shutdown is
`implemented` with live readiness `not_assessed`; it reports
`dock_power.shutdown_hardware_unverified` and
`dock_power.live_preflight_required`. Existing execution guards remain mandatory.

Sleep is `unavailable`, with stable reason categories:

- `dock_power.sleep_profile_unverified`: no verified cable-connected sleep profile.
- `dock_power.sleep_inhibitor_handoff_unverified`: no coordinated original-request
  handoff covering the background guard and retained transaction lease.
- `dock_power.sleep_wake_thermal_unverified`: wake behavior and powered-enclosure
  thermal safety remain unverified.

The existing `DISCONNECT_BEFORE_SLEEP_VERIFIED` hardware-profile value describes
the canonical physical-removal workflow. It does not satisfy cable-connected
sleep requirements. This status contract cannot enable sleep, release an
inhibitor, or authorize software reconnect; exposing it through the backend/UI
is a separate integration step.

The focused 0.3.94 candidate mounts the existing guarded dock control with
`disconnect_only` intent. It retains fresh attachment/idle checks and confirmation,
but exposes neither software reconnect nor shutdown or sleep through that control.
The wider lifecycle branch retains the separately tested shutdown intent for
later integration. Normal Steam Sleep/Shutdown and the physical button do not
invoke the new shutdown flow. Software-disconnect completion is not physical
unplug clearance; the enclosure remains powered.

On 2026-09-14 the maintainer decided to offer the shutdown intent through that
same control. The native adapter now mounts a two-option selector -- disconnect
only (the default, and the route the 0.3.98 golden cycle ran) or disconnect and
shut down -- feeding one `WholeDockControl`, one pending record and one poll.
Reconnect and every sleep route stay off the selector. Selection is
presentation only: `dockIntentControl` and every backend guard still decide
whether the chosen route is offered, and the capability contract still
authorizes nothing. `dock_power.live_preflight_required` was removed from that
contract because it named a gate that was never implemented. Hardware
completion of an automated shutdown continuation remains unverified: D5.2
recorded fan and LEDs staying on until a manual power-button hold, and the
later clean shutdown is a user-reported manual result, not an automated
continuation test.

On 2026-09-14 the maintainer also asked for the disconnect-then-sleep press.
It is mounted on the Quick Access surface as "Disconnect and sleep", on the
existing game-close route (`runSleepWithGameClose`), not on the dock control's
selector, which still offers no sleep route. The press reads sleep readiness
first and refuses without touching the eGPU when readiness is unknown, when
sleeping does not need a disconnect, or when a retained disconnect-transaction
sleep lease is still held. That last fact is `retained_inhibitor`, now reported
by `get_sleep_readiness` in every branch: the snapshot's `sleep_guard` describes
the background controller only, and the 2026-09-13 capture recorded both
inhibitors still up after a successful software removal. After the software
disconnect the press does not suspend on the disconnect result. It re-reads the
snapshot a bounded number of times until the background guard is neither
required nor active, hands that same observation to the Steam-side preflight so
its blocker drops on evidence, and only then asks Steam to suspend; if the guard
is still up when the budget ends it says so and leaves the handheld awake.
Freeing the eGPU restarts the Steam session whenever a session-reached unit
held it, which destroys that panel before its sleep step runs, so the sleep is
also written down with the disconnect (`take_pending_sleep`: one record,
consumed on claim, same boot only, five awake minutes, refused if the machine
has slept since) and the panel that comes up after the restart claims it,
waits for the same guard evidence, and asks Steam to sleep. A game closed for
the sleep is reopened only after the suspend call returns -- after waking
when the machine did sleep, a moment later when Steam declined -- and a guard
refusal reopens it at once. The readiness retained-lease fact and this
continuation are both new on 2026-09-14 and neither has run on the device.
Separately, a sleep handoff whose restore fails no longer silences the
background guard for the process lifetime: `resume_protection` returns the
controller to its ordinary presence policy for every lease the handoff owned
-- acquire while the eGPU is present, release once it is gone -- while the
handoff keeps its claim so a second one cannot start on top of it. The
transaction controller is built per request and reconciled by nothing, so a
transaction lease that fails to reacquire stays down exactly as before; that
gap is recorded here, not closed.
None of this is hardware-validated. No sleep/wake cycle has been run through
the press, invariant 10 still disclaims sleep validation, and the enclosure
remains powered.

An unwired `SleepLeaseHandoff` module now implements the proposed two-lease
handoff contract with independent restoration readbacks and one-shot submission.
No production adapter supplies the required pause, crash-continuity, supported
profile, wake and thermal evidence. The current sleep refusal remains active.

Sleep needs supported-profile validation, coordinated inhibitor release and
reacquisition on failure, and an approved continuation of its exact original
request. The current trial retains its sleep lease after software removal;
never bypass inhibitors to make the command appear to work. Software removal
does not power off the enclosure. Powered software-reconnect trials remain
paused following the reported heat incident; see
[the incident and isolation requirements](WHOLE_DOCK_DISCONNECT_MECHANISM.md).
This implementation provides no resume reauthorization or PCI rescan.

## Verification and delivery

### Automatic connection must coexist with retained disconnect state

The golden manifest now includes the real automatic recovery scheduling,
admission and service caller chain with fake OS boundaries, alongside the
existing automatic-TV loop tests. The fixtures cover a clean idle attach,
retained ordinary disconnect intent across runtime recreation, consumed
shutdown from an earlier boot, settled/unsettled early release, unavailable or
busy admission, running/unknown games and persisted preferences. Recreating a
runtime models the reload/update boundary; it does not execute a package
installer or certify migration on the device. A separate required Linux-root
CI step joins the real automatic recovery caller chain to the unmodified gate
factory, fixed-path root validation, persisted preferences, journal and claim
readers, and filesystem locks. Each case enters a private child chroot before
creating these dependencies; device observations and commands remain simulated.
The chroot isolates paths for trusted tests and is not a root security sandbox.
The CI step refuses absent privilege, empty coverage, skips and expected failures.
It supplements the existing privileged record/writer tests and the portable
43-test golden gate. Neither layer proves physical TV handoff or qualification.

`get_automatic_dock_status().recovery.decision_code` reports the **last observed
automatic recovery decision**, not a new preflight or permission to act. The
existing `enabled` and `code` preference fields remain separate. Until an
observation is available, the decision is `automatic_recovery.not_observed`.
Waiting states distinguish absent/unresolved transport, startup without a
verified detach, settling, game/session/identity uncertainty, and exhausted
attempts. Admission refusals expose only fixed categories: `admission_inhibited`,
`admission_unavailable_or_busy`, or `admission_refused`, each prefixed with
`automatic_recovery.`. Repeated unchanged decisions produce one journey event;
a changed decision is recorded again. Exception details and attachment
identifiers are not exposed. These fields do not clear claims, restart the
session, extend the attempt budget or grant unplug clearance.

Before promoting a candidate, retain a record of its exact source, ZIP hash,
installed readback, OS/kernel, both automatic-docking and recovery preferences,
managed session readiness, and categorical initial claim/journal state. Keep
these settings as test evidence; do not silently enable recovery during an
update. Preserve the previous artifact and separately verify restored settings
when rolling back.

| Scenario | Required result/evidence |
| --- | --- |
| Detached clean boot, idle attach, TV on | Bounded automatic recovery if needed, automatic TV handoff, and user confirmation of picture, audio and controls. |
| Same sequence with the checkpoint TV in standby | Repeat the checkpoint case; record actual connector/EDID evidence rather than assuming genuinely missing HDMI. |
| Runtime reload/update with saved opt-in or opt-out | Preferences preserved, no recovery replay merely because the dock was already attached. Verify the actual installer separately. |
| Ordinary disconnect or incomplete release record retained | Automatic recovery remains blocked with its reason; no silent record deletion or attempt-budget reset. |
| Verified consumed shutdown record on a later boot | Reconcile only under the existing full evidence guards, then allow the normal bounded connection path. |
| Game running, unknown state or busy/unavailable admission | No restart; report the categorical reason. |

Record before/during/after results, including refusals, for the exact candidate.
The 0.3.94 failure must be diagnosed from live status before claiming its cause
fixed. A green test suite is software evidence; only the applicable supervised
device trials can promote the candidate over the preserved checkpoint. Do not
run powered software reconnect or live unplug trials as part of this matrix.

Unit/integration fixtures exercise request binding, ordered teardown/consume/
power execution, changed evidence, incomplete scans, expiry, busy admission,
ambiguous submission, unsupported sleep, and next-boot reconciliation. Linux
filesystem fixtures additionally cover concurrency, corrupt/symlink/hardlink
records, durability failure, and archival rollback; CI explicitly runs them.

Software checks do not certify sleep/wake, shutdown completion, or physical
removal. No version bump, release ZIP, installation, or device test is part of
this backend-only change.

The read-only `get_egpu_disconnect_status("power_capabilities")` backend request exposes this contract without
initializing a hardware runtime. It is available for later UI wiring; its
capability response cannot replace the execution preflight.

The [inhibitor handoff proposal](dock_power_inhibitor_handoff.md) records the
remaining two-lease cancellation, crash-continuity and wake contracts, with
fixture coverage of the existing seams. It does not enable cable-connected sleep.
