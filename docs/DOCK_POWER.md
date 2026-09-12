# Disconnect before sleep or shutdown

Status: offline implementation foundation. No new power action, native power
interception, inhibitor release, installation, or hardware trial is enabled.

The user-requested flow is one action: return to the handheld, release dock
users, remove downstream functions, deauthorize the USB4 tunnel, verify the
result, then continue the original sleep or shutdown request. Existing automatic
TV connection and manual disconnect entry points remain unchanged.

`application/dock_power.py` binds an operation ID, selected power action, and
deadline (at most five minutes). It requires retained mutation admission and
fresh owner-bound removal proof, persists power intent through an injected
atomic writer, rechecks evidence, and submits the selected action once. A lost
reply, refusal, expired request, or exception never triggers automatic replay.
Command acceptance is not proof that the device slept or powered off.

`WholeDockRuntime.verify_power_continuation` verifies the retained software-down
claim, attachment binding/generation, complete topology and storage scans,
absent downstream GPU/audio/USB functions, deauthorized tunnel, idle state, and
an independently supplied fresh Portable check. This method performs no writes
and does not grant physical unplug clearance.

## Remaining delivery work

1. Bind the explicit power choice before teardown in the backend; frontend
   remount after a Gaming-session restart must not recreate the request.
2. Implement an atomic durable power-intent record that rejects any prior
   submission for the operation, including after a backend restart. The current
   coordinator tests inject this contract; production persistence is not wired.
3. Invoke continuation while the existing whole-dock admission is still held.
   Do not nest ordinary mutation admission or use plugin unload as a hook.
4. Connect ordinary shutdown through the existing system-power adapter. The
   older shutdown service requires an attached eGPU and is not the verifier for
   an already-removed dock.
5. Keep sleep disabled until profile-specific docked sleep validation and
   coordinated inhibitor release/reacquisition exist. Successful software
   removal currently retains the trial sleep lease. Never bypass inhibitors.
6. Wire explicit player actions, then validate session restart, interruption,
   failure reporting, shutdown, and supervised sleep/wake separately.

This work does not revise the canonical sleep workflow's physical-removal
contract or intercept every OS power request. It provides no resume-triggered
reauthorization, PCI rescan, or software reconnect. Powered software-reconnect
trials remain paused following the reported heat incident; see
[the incident and isolation requirements](WHOLE_DOCK_DISCONNECT_MECHANISM.md).

## Verification

Focused fixtures cover complete removal, changed ownership, contradictory
authorization, incomplete storage scans, lost admission, Portable changes,
once-only submission, expiry, duplicate durable intent, callback exceptions,
concurrent execution, and the default refusal of unverified sleep. These are
software checks, not sleep/wake or physical-removal certification.
