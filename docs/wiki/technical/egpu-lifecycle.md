# eGPU lifecycle: baseline and acceptance

Re-Gear's ordinary **Safe Disconnect** journey has recorded hardware passes on
v0.3.98 (the preserved reference), a 0.3.127 maintainer report and a supervised
0.3.129 trial, all on one configuration. Development build 0.3.154 adds
first-time authorization, staged connection progress, a still-connected
authorization hold, and guarded **Disconnect + Sleep** and **Safe Disconnect +
Shutdown** wiring. It is built and software-validated only; see
[its status record](#development-build-03154-built-not-yet-hardware-tested).
Repeatability, other hardware, sleep and shutdown are not established.

## For players — no technical background needed

The trial returned play to the handheld, disconnected the external graphics
device, and later restored TV picture, audio and controls after physical
reconnection. It does not qualify every handheld or dock for powered unplugging.
Use the [eGPU player guide](../player/egpu.md) and the instructions for your exact
supervised build. Software reconnect is out of scope; do not treat a retained
developer command as a supported way to reconnect a still-cabled dock.

A newer source-only foundation can observe cooling data and classify a prepared,
still-connected state. It is not wired to the player interface or production
disconnect path, so it does not change the current player instructions.

Build 0.3.154 has not been installed on a handheld yet. Until it is, treat its new
sleep, shutdown and authorization behavior as untested, and keep following the
[eGPU player guide](../player/egpu.md).

## Technical details — for advanced users and contributors

### Development build 0.3.154: built, not yet hardware-tested

| Build field | Recorded value |
|---|---|
| Version and profile | `0.3.154`, development profile |
| Revision | `f6be3edd5702f3f4c258465df861edc8f8642373` |
| Archive | `Re-Gear-0.3.154.zip` |
| SHA-256 | `db017e82915f2bf2fb95f03c61bfbcd30cb01815f1d0d2f1c224fbffd18eb860` |
| Composition | `origin/main` `9dcdaff` + [PR #418](https://github.com/ronnierosal/Re-Gear/pull/418) head `f98f8d0` + Safe Disconnect authorization-hold fix `5887900` |
| Status | Built locally and software-validated. **Not installed, deployed, released or hardware-tested** |

Source location matters for review. `main` at `9dcdaff` carries truthful
connection status ([PR #420](https://github.com/ronnierosal/Re-Gear/pull/420)) and
the stage-driven connection popup ([PR #421](https://github.com/ronnierosal/Re-Gear/pull/421)).
The open PR #418 stack (on [PR #417](https://github.com/ronnierosal/Re-Gear/pull/417))
carries first-time USB4 authorization, the PipeWire sink readiness fix,
production sleep/shutdown admission and UI wiring, and multi-connector display
aggregation. The authorization-hold fix `5887900` and build revision `f6be3ed`
were recorded from the maintainer's local build and are not yet published
branches. "Implemented in source" below does not mean merged to `main`.

Evidence tiers used in the table:

- **Source** — implemented in source (location as above), with software tests.
- **0.3.154** — included in the 0.3.154 package.
- **Previously observed** — hardware behavior recorded on an earlier build, on
  the maintainer's single configuration only.
- **Awaiting** — still needs supervised 0.3.154 validation on the Ally.

| Capability | Source | 0.3.154 | Previously observed on hardware | Awaiting 0.3.154 hardware validation |
|---|---|---|---|---|
| **First connection and authorization.** USB4/eGPU attachment observed in Gaming Mode; first-time device popup; **Allow once** authorizes this attachment; **Always trust** shown only when the backend reports remembered trust; success requires a verified backend readback and never claims GPU, TV or audio readiness | Yes (PR #418 stack) | Yes | No authorization popup trial recorded | Popup appearance, both choices, readback, and that a verified approval leads into the normal connection flow |
| **Connection progress and automatic TV.** Compact staged progress for USB4 link, GPU, external display, audio and Gaming Mode readiness; blocked prerequisites show **Needs attention** with the backend reason; automatic TV switching and bounded retries after physical connection preserved; dynamic **Switch to TV** / **Switch to Handheld**; TV audio readiness from real PipeWire sink observations | Yes (#420/#421 on `main`; sink fix in PR #418 stack) | Yes | Automatic TV after physical connection on 0.3.98 and 0.3.129; both display switches on 0.3.129 | Stage cadence, **Needs attention** reasons, audio readiness with the real sink, retries |
| **eGPU status.** Overall status follows the lifecycle result; USB4 link, GPU rendering, external display, display output, session and game state kept as separate facts; multiple external connectors aggregated (any verified active connector wins, all must be verified off for a negative); stale or unavailable observations shown as unknown/unavailable | Yes (#420 on `main`; aggregation `f98f8d0`) | Yes | Status display on earlier builds; aggregation not observed | Correct status with the TV on a later connector; stale/unavailable rendering |
| **Ordinary Safe Disconnect.** Return picture to the Ally display, release active holders, remove the GPU and dock USB branch, deauthorize the USB4 tunnel, then instruct the player to physically unplug | Yes | Yes | Passed on 0.3.98 (supervised), 0.3.127 (maintainer report) and 0.3.129 (supervised) | Regression check that 0.3.154 still passes this acceptance baseline |
| **Still-connected authorization hold.** Immediately before USB4 deauthorization, a remembered device's policy changes from automatic to manual so `boltd` cannot reauthorize a still-cabled eGPU. The hold is bound to the exact operation, attachment identity, generation and internal device UUID. After strict physical-absence verification, automatic policy is restored for the next physical connection. Internal UUIDs never cross the RPC, diagnostic or log boundary | Yes (`5887900`, local) | Yes | No | That the dock stays off while cabled, and automatic policy returns after unplug |
| **Disconnect + Sleep.** Production backend admission and UI wiring. Sequence: return to Ally display → Safe Disconnect → tell the player to unplug → verify physical removal → continue the original sleep request before its deadline | Yes (PR #417/#418 stack) | Yes | 0.3.129 attempt **failed** before software-down; source fixes followed ([PR #383](https://github.com/ronnierosal/Re-Gear/pull/383)) | The complete journey, deadline behavior and wake |
| **Safe Disconnect + Shutdown.** Production backend admission and UI wiring. Sequence: return to Ally display → guarded disconnect → continue the original shutdown request. USB-C Power Delivery is not intentionally disabled, so the dock is expected to keep charging the Ally | Yes (PR #417/#418 stack) | Yes | Clean manual shutdown with continued charging observed on 0.3.98 (not this one-button path) | The complete one-button journey and charging |
| **Next physical connection.** After physical unplug and reconnect, remembered authorization can return to automatic policy and the preserved automatic connection and TV flow runs again | Yes | Yes | Physical replug with automatic TV return on 0.3.98 and 0.3.129 (before the authorization hold existed) | Replug after the hold is released |

**Excluded — not supported and not to be documented as supported:**

- Software reconnect, and software reauthorization used as a reconnect mechanism.
  Reconnection is physical replug only.
- Any powered reconnect trial.
- Sleeping while the eGPU stays logically connected ("sleep connected"). It is
  not an offered lifecycle action.
- Treating software removal alone as clearance to unplug the cable. Unplug only
  when the product instructs it, within a supervised test.
- Treating CI or software tests as evidence of hardware safety.

**Software verification recorded for 0.3.154** (software checks only):

| Check | Result |
|---|---|
| Golden behavior gate | 49/49 tests across 8 contracts |
| Frontend tests | 1,233/1,233 passed |
| Focused eGPU and authorization backend tests | 608 tests plus 764 subtests passed |
| Architecture, compileall, Ruff F82, TypeScript, development build, production build, package integrity | Passed |
| Broader backend suite on Windows | Known POSIX directory-fsync failures retained; these are platform limits, not evidence of an eGPU regression |

The authority for installed and hardware results remains
[CURRENT_STATE](../../CURRENT_STATE.md). When 0.3.154 is installed and read back,
its result belongs there first; this section is then updated from that record.

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

### Fan-safe prepared-connected foundation

[PR #343](https://github.com/ronnierosal/Re-Gear/pull/343) merged the source
foundation as `8eeb6c856aa47409c49247b922d14768b1ddc23d`. It has two parts:

- `EgpuCoolingDiscovery` observes one exact PCI eGPU through the loaded `amdgpu`
  driver's `hwmon` files. It reads temperature channels, fan RPM and whether the
  exposed PWM mode is automatic. The scan is bounded and fails closed if the PCI
  address is invalid, caller-supplied attachment/generation fields are empty, or
  driver, sensor data or scan completeness is missing or ambiguous. Those supplied
  fields do not independently prove attachment identity continuity. The observer
  never writes fan, PWM, power, driver or transport state.
- `decide_prepared_disconnect` is a pure decision contract. A
  `prepared_connected` result requires the handheld display, released clients,
  an authorized USB4 tunnel, the GPU still present and bound to `amdgpu`, and
  complete observations reporting automatic fan mode. Zero observed RPM is valid
  input, so this result does not prove cooling effectiveness or thermal safety.
  The state deliberately keeps the cable connected and requires transport
  authorization and driver presence.

The contract never sets `safe_to_unplug`. After final software teardown,
`decide_post_teardown` classifies `software_down` without verified physical
transport absence as `unplug_required`. This includes still-present and unknown
transport state. It is a short transition, not a stable connected state, reconnect
state or safety clearance. The flow is complete only when physical transport
absence is verified.

This foundation is merged and covered by source tests, but has no production
lifecycle entry point, runtime UI wiring, package/install evidence or hardware
qualification. It implements no fan writes and no software reconnect.

Authoritative source and validation: [cooling observer](../../../backend/regear/adapters/steamos/egpu_cooling.py),
[prepared-disconnect contract](../../../backend/regear/domain/prepared_egpu_disconnect.py),
[observer tests](../../../tests/test_egpu_cooling.py), and
[decision tests](../../../tests/test_prepared_egpu_disconnect.py).

### Lifecycle acceptance matrix

Entry points below were inspected in merged source `9421c6f` (the sleep/shutdown row
was re-checked against PR #418 head `f98f8d0`), with the later
RPC exclusion verified at merged `a16ba34`; tested revisions
are listed separately. The eGPU primary owns backend lifecycle integration; the
UI primary owns mounting and request routing. Ronnie owns supervised observations.

| Stage | Trigger | Production entry point | Required evidence | Successful result | Failure/recovery path | Tested revision | Hardware evidence | Owner | Next gap |
|---|---|---|---|---|---|---|---|---|---|
| Attachment observation | Physical replug | `Plugin._automatic_dock_loop`, `_observe_automatic_link_recovery` | Fresh physical attachment, identity and game/session state | New attachment observed; readiness assessed | Unknown evidence remains unavailable; no invented GPU/display result | `f6059fa` / 0.3.98 | Initial settling sampled 03:33:49.436 UTC | eGPU | Repeated cycles and other configurations |
| Bounded connection recovery | Eligible fresh attachment lacks endpoint readiness | `_run_automatic_connection_recovery` | Current admission, idle game, exact attachment, attempt budget | One recovery; endpoint/display readiness can then progress | Existing 10-second initial delay, max two attempts; preserve unknown-state and active-operation inhibition | `f6059fa` / 0.3.98 | One automatic recovery after physical replug | eGPU | Broader hardware/second-attempt evidence; not USB4 software reconnect |
| Automatic TV transition | Required readiness established | `_run_automatic_tv_transition` | GPU/display readiness, permitted transition and game state | TV active, readiness true, claim `none` | Report refusal/failure; preserve bounded recovery and handheld fallback | `f6059fa` / 0.3.98 | 03:34:20.994 UTC; user confirmed picture/audio/controls | eGPU + UI | Repetition; preserve timing and trigger |
| Player disconnect request | One **Safe Disconnect** press | `WholeDockControl intent="disconnect_only"` → `execute_egpu_disconnect(trial_action="whole_dock_disconnect")` | Current approved request and exact attachment; real mounted control | Original request enters teardown once | No repeat request merely because the session/RPC channel restarts; re-observe | `f6059fa` / 0.3.98 | Actual button press recorded | UI + eGPU | Acceptance of later mounted UI revisions |
| Prepared-connected cooling foundation | Future explicit preparation phase; not production-wired | No production entry point; `EgpuCoolingDiscovery.scan`, `decide_prepared_disconnect` and `decide_post_teardown` are merged library contracts | Handheld display, clients released, USB4 authorized, valid PCI address, nonempty caller attachment/generation fields, `amdgpu` bound, complete temperatures/fan RPM/reported automatic-mode evidence | `prepared_connected`; contract requires transport authorization, driver presence and reported automatic fan mode | Any missing or ambiguous requirement refuses; no identity-continuity proof, effective-cooling claim, fan write or unplug clearance | `8b700df` / merged `8eeb6c8` | None; source tests only | eGPU | Production integration, identity binding, UI contract and supervised hardware qualification |
| Return/release/remove | Accepted disconnect | `_run_whole_dock_trial`, `_return_portable_before_disconnect`, `LiveDisconnectService.disconnect`, `WholeDockRuntime.execute_claimed` | Verified return/release, identity, clients/storage, topology and operation ownership | `dock_teardown.software_down`, GPU removed, display released, filter disarmed | Refuse incomplete release; retain unresolved transaction evidence; no blanket retry/clear | `f6059fa` / 0.3.98 | 03:29:13.090 UTC; handheld picture/audio/controls confirmed | eGPU | Earlier 0.3.97 refusal cause and repeatability |
| Physical unplug reconciliation | User physically unplugs in supervised trial | `_reconcile_physically_disconnected_dock` | Verified absent transport, completed claim | Completed history clears, claim `none`; handheld continues | Unreadable/ambiguous state is not physical absence | `f6059fa` / 0.3.98 | 03:32:34.702 UTC | eGPU; Ronnie hardware | Broader live-removal qualification |
| Sleep/shutdown continuation | **Disconnect + Sleep** or **Safe Disconnect + Shutdown** request | `_run_dock_power_request`, `whole_dock_sleep`, `whole_dock_shutdown`; UI request coordinator | Correlated original intent, completed teardown, strict physical-absence verification before sleep, deadline | At most one continuation; sleep success requires observed kernel cycle | Sleep waits awake for verified physical absence and is not submitted after its deadline; failed prerequisites stay awake. Connected sleep is not an offered action | Production admission and wiring in the PR #417/#418 stack, packaged in 0.3.154; not a hardware pass | 0.3.98 manual sleep after teardown blocked; 0.3.129 **Disconnect + Sleep** failed before software-down | eGPU + UI | Supervised 0.3.154 sleep and one-button shutdown journeys |
| Charging and wake continuity | Disconnect, sleep or shutdown with cable attached | Same power/disconnect paths; observed power supply and battery evidence | Preserve dock power delivery; record supply online, battery/charge trend when available, user indication and recovery-attempt counts | Handheld usable with data path down and charging retained; healthy sleep/wake with existing connection separately verified | No intentional power-delivery disable; report unknown charging; distinguish wake with recovery from wake without recovery | 0.3.98 manual observations; no automated power qualification | User confirmed clean manual shutdown and continued charging; controlled sleep/wake pending | eGPU + UI; Ronnie hardware | Capture actual connected sleep/wake, charging and before/after recovery-attempt count |
| Software reconnect (excluded) | Historical developer request; now rejected at RPC boundary | `execute_egpu_disconnect` returns `dock_reconnect.disabled`; lower-level reconnect machinery remains | No new trial authorized by retained code | Request refused before worker/state changes | Backend allowlist/fallback removed in #335; older installed packages do not inherit this gate | 0.3.92 `6c638a8` failed trial; #335 source/fixture gate | Timeout, authorized router but missing endpoints, later heat report; no new hardware trial | eGPU + UI | Include backend gate and UI removal in combined candidate; no powered trial |

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

Lower-level implementation remains in source, but [PR335](https://github.com/ronnierosal/Re-Gear/pull/335)
merged as `a16ba34c336cfe5813f9dceb15d10f7df029f928` disables the public reconnect
RPC before worker creation or state changes, removes it from the allowlist and
removes generic reconnect fallthrough. The eGPU primary supplied 22 focused and
49 golden passes, independent review and final CI. These are software checks,
not a new device trial. Older installed packages do not acquire this restriction
from a source merge. The UI primary separately owns removal of the reconnect
model/modal and inclusion of both restrictions in the combined UI candidate;
that task remains distinct from backend acceptance. No powered trial is authorized.
The [incident record](../../WHOLE_DOCK_DISCONNECT_MECHANISM.md#thermal-incident-software-reconnect-trials-paused)
retains the investigation and thermal stop/recovery requirements.

### Evidence coverage

Read-only probes assess readiness and mechanism policy; they do not execute the
button path. See [the explicit probe boundary](scripts-and-ci.md#what-the-readiness-probe-actually-does).
The 0.3.98 button/cycle record is separate stronger evidence. New components,
draft UI consumers, green CI and later package versions do not inherit its
installed or hardware-tested status.
