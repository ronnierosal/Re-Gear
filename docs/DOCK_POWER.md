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

The dock claim lives in persistent storage, so command acceptance does not clear
it. A canceled shutdown in the same boot remains inhibited. On a later automatic
connection attempt, the backend can archive an exact software-down claim only
when a matching consumed shutdown intent proves a different boot and fresh
observations establish the matching authorized dock/transport, idle supported
host/session, settled helper work, and no inner recovery or transition journal.
The current attachment generation must be stable; it need not equal the old
boot's generation. Ordinary mutation admission is retried after archival.

This path performs no device writes, does not reset recovery budgets, and cannot
retire ordinary disconnects, sleep intents, same-boot shutdowns, unconsumed or
missing intents, or failed reconnect records. Those continue to require their
own evidence-backed recovery. Consumed power records remain as audit evidence.

## Sleep and UI work remaining

UI wiring is deferred by user request. Neither normal Steam Sleep/Shutdown nor
the physical button invokes this new flow yet. The canonical sleep workflow's
physical-removal contract and existing frontend preflight remain unchanged.

Sleep needs supported-profile validation, coordinated inhibitor release and
reacquisition on failure, and an approved continuation of its exact original
request. The current trial retains its sleep lease after software removal;
never bypass inhibitors to make the command appear to work. Software removal
does not power off the enclosure. Powered software-reconnect trials remain
paused following the reported heat incident; see
[the incident and isolation requirements](WHOLE_DOCK_DISCONNECT_MECHANISM.md).
This implementation provides no resume reauthorization or PCI rescan.

## Verification and delivery

Unit/integration fixtures exercise request binding, ordered teardown/consume/
power execution, changed evidence, incomplete scans, expiry, busy admission,
ambiguous submission, unsupported sleep, and next-boot reconciliation. Linux
filesystem fixtures additionally cover concurrency, corrupt/symlink/hardlink
records, durability failure, and archival rollback; CI explicitly runs them.

Software checks do not certify sleep/wake, shutdown completion, or physical
removal. No version bump, release ZIP, installation, or device test is part of
this backend-only change.
