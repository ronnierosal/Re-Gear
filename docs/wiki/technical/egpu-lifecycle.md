# eGPU lifecycle: baseline and acceptance

Re-Gear has one recorded successful supervised disconnect, physical unplug and
physical replug cycle on v0.3.98. This is the lifecycle reference to preserve.
Repeatability, other hardware and sleep are not established by that result.

## For players — no technical background needed

The trial returned play to the handheld, disconnected the external graphics
device, and later restored TV picture, audio and controls after physical
reconnection. It does not qualify every handheld or dock for powered unplugging.
Use the [eGPU player guide](../player/egpu.md) and the instructions for your exact
supervised build. Software reconnect is out of scope; do not treat a retained
developer command as a supported way to reconnect a still-cabled dock.

## Technical details — for advanced users and contributors

### Preserved hardware baseline: v0.3.98

The authority is [EGPU_0398_CHECKPOINT.md](../../EGPU_0398_CHECKPOINT.md), not the
newest package number or current main.

| Evidence field | Recorded value |
|---|---|
| Source | `f6059fad8c213a059aa77cbba15524ef2d9149ae` |
| Tag | `checkpoint/0.3.98-egpu-cycle` |
| Archive | `Re-Gear-0.3.98.zip` |
| Size | 976983 bytes |
| SHA256 | `aa14dcab885492368ee86e26523a8da7cd156d7483d097ba86f6814ebbf413da` |
| Configuration | Ally + GPD G1; kernel `6.16.12-valve24.5-1-neptune-616-gb2f7cfe85e45` |
| Date and scope | September 13, 2026 UTC; one successful supervised physical disconnect/unplug/replug cycle |
| Provenance | Installed full revision read back before trial; local evidence `egpu-connection-admission-fix/out/golden-0.3.98/` |
| Settings | Automatic docking and recovery enabled; session restart strategy, 10-second initial delay, two-attempt maximum; unchanged for this trial |

Local evidence paths identify retained operator records, not downloadable public
artifacts. Preserve the immutable archive and tag. The earlier
[0.3.82 automatic-TV record](../../EGPU_0382_CHECKPOINT.md) and 0.3.97 release
refusal remain evidence; the success does not establish the cause of the refusal.

### Lifecycle acceptance matrix

Entry points below were inspected in merged source `9421c6f`; tested revisions
are listed separately. The eGPU primary owns backend lifecycle integration; the
UI primary owns mounting and request routing. Ronnie owns supervised observations.

| Stage | Trigger | Production entry point | Required evidence | Successful result | Failure/recovery path | Tested revision | Hardware evidence | Owner | Next gap |
|---|---|---|---|---|---|---|---|---|---|
| Attachment observation | Physical replug | `Plugin._automatic_dock_loop`, `_observe_automatic_link_recovery` | Fresh physical attachment, identity and game/session state | New attachment observed; readiness assessed | Unknown evidence remains unavailable; no invented GPU/display result | `f6059fa` / 0.3.98 | Initial settling sampled 03:33:49.436 UTC | eGPU | Repeated cycles and other configurations |
| Bounded connection recovery | Eligible fresh attachment lacks endpoint readiness | `_run_automatic_connection_recovery` | Current admission, idle game, exact attachment, attempt budget | One recovery; endpoint/display readiness can then progress | Existing 10-second initial delay, max two attempts; preserve unknown-state and active-operation inhibition | `f6059fa` / 0.3.98 | One automatic recovery after physical replug | eGPU | Broader hardware/second-attempt evidence; not USB4 software reconnect |
| Automatic TV transition | Required readiness established | `_run_automatic_tv_transition` | GPU/display readiness, permitted transition and game state | TV active, readiness true, claim `none` | Report refusal/failure; preserve bounded recovery and handheld fallback | `f6059fa` / 0.3.98 | 03:34:20.994 UTC; user confirmed picture/audio/controls | eGPU + UI | Repetition; preserve timing and trigger |
| Player disconnect request | One expanded **Safely disconnect** press | `WholeDockControl intent="disconnect_only"` → `execute_egpu_disconnect(trial_action="whole_dock_disconnect")` | Current approved request and exact attachment; real mounted control | Original request enters teardown once | No repeat request merely because the session/RPC channel restarts; re-observe | `f6059fa` / 0.3.98 | Actual button press recorded | UI + eGPU | Acceptance of later mounted UI revisions |
| Return/release/remove | Accepted disconnect | `_run_whole_dock_trial`, `_return_portable_before_disconnect`, `LiveDisconnectService.disconnect`, `WholeDockRuntime.execute_claimed` | Verified return/release, identity, clients/storage, topology and operation ownership | `dock_teardown.software_down`, GPU removed, display released, filter disarmed | Refuse incomplete release; retain unresolved transaction evidence; no blanket retry/clear | `f6059fa` / 0.3.98 | 03:29:13.090 UTC; handheld picture/audio/controls confirmed | eGPU | Earlier 0.3.97 refusal cause and repeatability |
| Physical unplug reconciliation | User physically unplugs in supervised trial | `_reconcile_physically_disconnected_dock` | Verified absent transport, completed claim | Completed history clears, claim `none`; handheld continues | Unreadable/ambiguous state is not physical absence | `f6059fa` / 0.3.98 | 03:32:34.702 UTC | eGPU; Ronnie hardware | Broader live-removal qualification |
| Sleep/shutdown continuation | Explicit original power request | `_run_dock_power_request`, `whole_dock_shutdown`, `whole_dock_sleep`, `whole_dock_sleep_connected`; UI request coordinator | Correlated original intent, teardown/lease evidence where required, observed suspend counters | At most one continuation; sleep success requires observed kernel cycle | Failed prerequisites stay awake; unresolved submission/restoration is reported | Merged #315/#316 component evidence; not a 0.3.98 power pass | 0.3.98 manual sleep after teardown was blocked; no sleep/wake occurred | eGPU + UI | Combined mounted path and supervised sleep/wake |
| Software reconnect (excluded) | Historical developer request only | Retained `whole_dock_reconnect`, `_run_whole_dock_reconnect_trial`, `WholeDockRuntime.reconnect_owned` | No new trial authorized by retained code | No supported product success claimed | Keep excluded; see incident and gating below | 0.3.92 `6c638a8` failed trial | Timeout, authorized router but missing endpoints, later heat report | eGPU + UI | Gate retained backend route and UI exposure; no powered trial |

Source: [Plugin composition](../../../main.py),
[mounted control](../../../src/whole-dock-control.tsx),
[native expanded adapter](../../../src/quick-access/expanded-command-center/native.tsx),
[whole-dock mechanism](../../WHOLE_DOCK_DISCONNECT_MECHANISM.md),
[power contract/status](../../EGPU_POWER_NEXT.md), and
[golden contracts](../../../contracts/golden-behaviors.json).

### Software reconnect: decision and retained machinery

Ronnie excluded software USB4 reconnect, wake reauthorization and PCI rescan
recovery after the 0.3.92 incident. Physical replug followed by the existing
automatic connection/session recovery is a different path and remains part of
the preserved 0.3.98 observation. Keeping an already-connected dock through sleep
is also distinct from reauthorizing an intentionally disconnected dock.

On September 12 UTC, installed 0.3.92 source `6c638a81607bd2b16f9976cc3d6723b00dfe34c7`
had verified software removal and usable handheld operation. A separate completion
helper recorded `software_down` without hardware writes. One software reconnect
request timed out after 30 seconds; the router was authorized but external
GPU/audio/USB PCI functions were absent, with `reauthorize_intent` retained. The
owner subsequently reported unusual heat and unplugged. No temperature/fan
telemetry established a measurement, causation or damage. This failed incident
closed further powered software reconnect trials; it was not a successful cycle.

The implementation remains in source. The disconnect-only expanded control does
not offer reconnect, but that alone does not prove every backend dispatch route
is gated. The eGPU primary owns backend admission/retained machinery; the UI
primary owns exposure and request routing. Their gating work must prove excluded
requests cannot execute while ordinary physical-attachment recovery still works.
This document neither removes the machinery nor claims that gating is complete.
The [incident record](../../WHOLE_DOCK_DISCONNECT_MECHANISM.md#thermal-incident-software-reconnect-trials-paused)
retains the investigation and thermal stop/recovery requirements.

### Evidence coverage

Read-only probes assess readiness and mechanism policy; they do not execute the
button path. See [the explicit probe boundary](scripts-and-ci.md#what-the-readiness-probe-actually-does).
The 0.3.98 button/cycle record is separate stronger evidence. New components,
draft UI consumers, green CI and later package versions do not inherit its
installed or hardware-tested status.
