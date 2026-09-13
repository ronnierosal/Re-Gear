# Disconnect before power: implementation checkpoint

## Accepted behavior, 2026-09-13

Build from the [0.3.98 golden cycle](EGPU_0398_CHECKPOINT.md), preserving its
connection and button-disconnect behavior. User requests Sleep or Power off;
Re-Gear returns to handheld, runs the same verified resource/GPU/USB4 disconnect,
then continues that original power request once. A failed disconnect reports its
actual reason and does not silently execute power or retry removal.

Ronnie confirmed the G1 cable may remain connected for charging after either
sleep or shutdown. The dock stays logically disconnected on wake. Reusing the
eGPU requires physical unplug/replug; there is no software reconnect,
reauthorization or rescan on wake. Charging retention is a hardware trial outcome
to record, not something USB4 deauthorization alone proves.

## Existing implementation to reuse

- `Plugin._run_whole_dock_trial`: the verified portable return and teardown.
- `create_power_request`, `DockPowerIntentStore`, `continue_dock_power`:
  backend-owned operation/action/session/deadline, consumed once before poweroff.
- `SystemPowerCommandRunner`: existing ordinary shutdown adapter.
- `SleepLeaseHandoff`: unwired two-lease handoff with restoration handling.
- Existing UI confirmation/correlation: confirmation captures original intent;
  backend continues through frontend/session restart. Cancellation before dispatch
  does nothing. Do not let the frontend submit another power action after return.

## Work completed and remaining

`SystemSuspendCommandRunner` now provides a fixed ordinary suspend boundary with
explicit inhibitor checking, a timeout and categorical results. It executes no
command during construction, retries no uncertain request, does not bypass locks
and defines no wake behavior. It has no production caller yet. The command shape
was checked against installed systemctl help and the upstream systemd manual:
https://github.com/systemd/systemd/blob/main/man/systemctl.xml
This is API documentation consultation, not copied implementation.

`SleepGuardController` now supports an operation-owned temporary reconciliation
pause, distinct from terminal close. `GuardSleepLease` binds that controller to
the exact backend request for the existing two-lease handoff. Focused tests use
real guards and Login1 leases with only the OS process replaced: polling cannot
reacquire during submission, refusal restores protection, ownership cannot be
stolen, and late restoration cannot reopen a closed controller. These methods
are not yet called by the production sleep route.

Remaining: bind production sleep handoff to the original request and both actual
sleep leases; coordinate lease reconciliation and restoration with the platform
sleep/resume observation. Wire the existing shutdown continuation and the new
sleep continuation into explicit UI power actions through one backend route.
No-eGPU/already-disconnected ordinary power must not run teardown again. Keep
normal power actions and direct routing distinct from evidence of a new removal.
The UI owner has supplied a read-only routing assessment; shared index/shell
production edits await the agreed backend contract and joint sequencing.

Do not implement a disconnect/unplug/sleep workflow instead: the user explicitly
selected sleep with the charging cable attached. No forced power operation,
software reconnect or device experiment is part of this code checkpoint.

## Validation next

The user explicitly replaced blanket sleep/shutdown refusal with automatic
disconnect-before-power. The delivery service now accepts an original sleep
intent and can continue it through the exact-request `SleepLeaseHandoff` after
durable consumption. Intent creation alone does not start sleep. Existing
shutdown dispatch now routes verified transport absence to ordinary poweroff,
rechecking under admission and consuming before submission; connected docks
still use the same teardown. It does not require an idle game or supported eGPU
profile on the verified-absent path. This absence reader currently covers USB4
hosts; broader platform absence discovery remains separate.

Remaining production work: the still-cabled/already-down route, actual sleep
observer and two-lease handoff wiring, and exact Steam Sleep/Shutdown interception.
The current Steam observer drops request arguments; the UI primary is inspecting
the action contract. Do not remove interception before replacement routing is
connected, or native sleep could race the requested disconnect. No installed
blockers were removed by this source checkpoint; this build is not packaged.

Focused command tests and existing shutdown coordinator tests cover the new
adapter without hardware calls. Preserve current golden tests and add integrated
original-intent, duplicate/cancel, failure-before-power, ordinary-no-dock and
resume-without-reauthorization checks at actual production seams. Run one bounded
supervised poweroff trial first, then cable-connected sleep/wake with handheld
operation and charging observed. Prior automatic-TV evidence remains valid unless
new changes affect that path; do not repeat unchanged broad trials by default.

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
