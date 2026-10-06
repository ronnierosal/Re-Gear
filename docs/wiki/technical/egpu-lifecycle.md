# eGPU lifecycle: baseline and acceptance

Development build **0.3.183 is installed and loaded**, verified against source
`ba9d2395d449e211a0b60c776b0177e5ac329e40` and its immutable development ZIP.
Two Safe Disconnect + Shutdown runs were user-observed successes; the first
subsequent boot/TV reconnect was claim-free, while the final detached boot retained
**`software_down`, not `none`**. This is bounded evidence, not complete Class D
acceptance, general hardware support or a public release. See the
[current-state authority](../../CURRENT_STATE.md#installed-03183-shutdown-checkpoint--october-6-2026-utc).

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

On the recorded setup, Safe Disconnect + Shutdown powered off twice and the
first reboot returned to a healthy TV connection. A final detached boot remained
usable on the handheld but retained a completed teardown claim; cleanup still
needs validation. Later sleep successes were reported. An accidental R2 press
near sleep is an uncorrelated observation, not a confirmed defect. Follow the
[eGPU player guide](../player/egpu.md) and the exact supervised build instructions.
Software reconnect remains excluded.

## Technical details — for advanced users and contributors

### Installed 0.3.183: shutdown and retained-claim boundary

[The exact checkpoint](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-6009350961)
verifies installed disk/live backend/loaded frontend: source
`ba9d2395d449e211a0b60c776b0177e5ac329e40`, development archive
`Re-Gear-0.3.183.zip`, 1,372,956 bytes, SHA-256
`da51b7d4277b3f0bffd9894c59ff573ccd327fefcd28ccd3e2bfbc2c5e642c5e`.
The prior failed old-boot `tunnel_remove_intent` automatically archived to `none`
without manual clearing. Two shutdown successes are user-observed; the first
changed boot and healthy TV reconnect were independently captured claim-free.

The [final detached boot](https://github.com/ronnierosal/Re-Gear/issues/18#issuecomment-6009330454)
was exact 183, new boot, idle Portable/internal/eGPU absent/journals idle/no
reported blockers or retained inhibitor, **but durable claim `software_down`
remained**. Completed teardown is supported; exact intent correlation and
retirement/admission clearance remain unverified. Terminal power-off markers,
substage timing and independent controller tests are missing; transport loss or
chat intervals do not prove power-off timing. Local checkpoint archive SHA-256:
`966e03d1e96597668d2700bf2773b415f20c84ec84b1471f11fd2cf7be7938b5`.

[Source characterization](https://github.com/ronnierosal/Re-Gear/issues/18#issuecomment-6009350086)
shows a cleanup coverage gap with a synthetic consumed old-boot shutdown intent,
not a proven final-device cause or additional shutdown failure. Runtime cleanup
is separately owned; no future fix is claimed. [Later sleep success and R2 observation](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-6009393535)
remain user reports: cancel/wake/coincidence is unknown; subsequent normal Sleep
button success does not establish a causal defect or broad controller acceptance.

0.3.180's two sleep successes remain historical; its later
[shutdown timeout FAIL](https://github.com/ronnierosal/Re-Gear/issues/18#issuecomment-6005442766)
and ordinary OS recovery are not retroactively changed. 0.3.182 is intermediate
source/artifact evidence. Eight ancestor PRs closed unmerged under #464 revision
25 as source-superseded, not hardware PASS. The
[#18 proposal](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-6009420758)
is historical supersession, not proof that the original ordinary shutdown hang
was fixed or retested. See the [authority](../../CURRENT_STATE.md#installed-03183-shutdown-checkpoint--october-6-2026-utc)
for preserved successor and independent obligations.

The 183 CI development artifact is available, distinct from a public Release;
no new tag/Release was created by this update. [Release gates](../../RELEASE_PIPELINE.md)
and full Class D/procedure, cleanup/power correlation, native F6/controller,
fault and latency checks remain. No private raw topology or photos are published.

### Installed 0.3.180: bounded working checkpoint

Historical October 5 checkpoint; 183 is the latest installed record above.

The [October 5 UTC checkpoint](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-5987964708)
verifies installed disk source, live backend and loaded frontend against the
immutable development-profile `Re-Gear-0.3.180.zip` (1,371,670 bytes), source
`d1ee13dc54db1f789eaec683717072ab1090f3a8`, SHA-256
`2a36f021f8aa02c036d4192c1f0f61a930bac315589476fa0f39918d619a2c13`.
Two consecutive connection/TV/Safe Disconnect + Sleep successes are separately
user-observed. Normal B-close/reopen and controller navigation were confirmed;
four attached/absent GPU-display captures share one boot identity.

The [superseding terminal/timing addendum](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-5989274483)
reports `sleep_cycle_observed`, verified physical absence, completed teardown,
**one accepted suspend request**, no retained whole-dock claim, idle journal/no
acknowledgement required, and Portable/internal GPU/eGPU absent/no blockers.
This independently instruments one retained request, not two distinct cycles;
it supersedes earlier unavailable suspend/terminal/timing statements.

| Latest retained-request measurement | Duration |
|---|---|
| Before power verification | 40.9 seconds |
| Dock teardown | 30.9 seconds |
| Portable return | 6.0 seconds |
| GPU release | 3.6 seconds |

Teardown is the largest measured phase. Do not add these potentially overlapping
durations or attribute them to the first cycle without request-identity matching.
No historical latency regression or inner teardown cause is established.
Separate local timing/terminal archive SHA-256:
`a9512da5661e5a2d6f3cf45fb37f3aa7462e21b646a56cb8b715cb11f8f16d53`.
Original ZIP/checkpoint archives remain unchanged; private photos/raw device
records are not published.

Shutdown, next-boot acknowledgement retirement, genuine eligible acknowledgement
activation, failure recovery and Hide-while-pending remain open. Normal
B-close/reopen is not pending-warning F6 or eligible acknowledgement acceptance.
[#464](https://github.com/ronnierosal/Re-Gear/issues/464) remains Class D,
hardware-required, with separate approved-procedure and full exact-candidate
acceptance gates. The residual expired deauthorized sleep alarm remains a
fail-closed limitation until correlated absence; these successes do not qualify
that negative path. Software reconnect is excluded. See the
[technical authority](../../CURRENT_STATE.md#installed-03180-working-checkpoint--october-5-2026-utc)
for milestone #54's accepted successor and the still-open #438/#136/#161
obligations; unresolved PRs are not closed by this checkpoint.

### Candidate 0.3.180: software validation only

Historical October 3 software-review snapshot. Installation and bounded hardware
observations are superseded by the October 5 record above; all original software
evidence and outstanding acceptance boundaries are retained below.

As of October 3, 2026, source `d1ee13dc54db1f789eaec683717072ab1090f3a8` was
reviewed against merged main `cb8f0199f3aa5954a66b1061934fff70c696abdd`.
The immutable development-profile archive is `Re-Gear-0.3.180.zip`, 1,371,670
bytes, SHA-256
`2a36f021f8aa02c036d4192c1f0f61a930bac315589476fa0f39918d619a2c13`.
The [artifact/test handoff](https://github.com/ronnierosal/Re-Gear/issues/464#issuecomment-5972496453),
[combined software PASS](https://github.com/ronnierosal/Re-Gear/issues/448#issuecomment-5972339102),
[exact final-head software PASS](https://github.com/ronnierosal/Re-Gear/issues/448#issuecomment-5972475393),
[CI PASS](https://github.com/ronnierosal/Re-Gear/actions/runs/37146099028) and
[privileged delivery PASS](https://github.com/ronnierosal/Re-Gear/actions/runs/37146099055)
are separate from device acceptance.

The producer/reviewer records report both profiles' 5,130 backend tests with 33
skips each, 1,382 frontend tests per profile, 49 golden checks, architecture,
compilation, typecheck, builds and package validation passing. F1–F6 and factual
Portable GPU presentation fixes are software-validated: the combined candidate
repairs retained-result, warning and sleep-cleanup paths while preserving exact
request/attempt identity, ownership, strict absence and durability guards.
These are attributed candidate software results, not this documentation worker's
runtime or hardware acceptance.

The residual expired deauthorized sleep request can keep its unplug alarm until
correlated physical absence is verified. Native acknowledgement visibility and
controller focus, real F6 warning close/reopen, and the exact-candidate connection,
TV, disconnect, physical reconnect, sleep/wake, shutdown, boot and power checks
remain open. [Task #464](https://github.com/ronnierosal/Re-Gear/issues/464) remains
**Class D, hardware-required**: an explicitly approved supervised procedure and
exact-candidate hardware acceptance are required before the normal integration
gates can complete. Neither 0.3.179 nor 0.3.180 has installed/hardware PASS;
0.3.173 remains the last recorded installed build, without a fresh readback here.
Software reconnect stays excluded. No test PASS grants unplug clearance, hardware
support, deployment authority or public-release readiness.

The [current-state authority](../../CURRENT_STATE.md#software-validated-candidate-03180--october-3-2026)
records the candidate separately from every historical build below. The 0.3.154
artifact and acceptance matrix remain historical snapshots; their outstanding
checks and older observations do not certify 0.3.180.

### Development build 0.3.154: built, not yet hardware-tested

Historical 0.3.154 snapshot; retained identity, source composition and validation
limits below apply to that artifact rather than the current candidate.

| Build field | Recorded value |
|---|---|
| Version and profile | `0.3.154`, development profile |
| Revision | `f6be3edd5702f3f4c258465df861edc8f8642373` |
| Archive | `Re-Gear-0.3.154.zip` |
| SHA-256 | `db017e82915f2bf2fb95f03c61bfbcd30cb01815f1d0d2f1c224fbffd18eb860` |
| Composition | `origin/main` `9dcdaff` + [PR #418](https://github.com/ronnierosal/Re-Gear/pull/418) head `f98f8d0` + Safe Disconnect authorization-hold fix `5887900` |
| Status | Local development artifact, built and software-validated. **Not installed, deployed, released or hardware-tested** |

At this historical checkpoint, all 0.3.154 lifecycle source was merged. Truthful connection status
([PR #420](https://github.com/ronnierosal/Re-Gear/pull/420)) and the stage-driven
connection popup ([PR #421](https://github.com/ronnierosal/Re-Gear/pull/421))
merged first. [PR #425](https://github.com/ronnierosal/Re-Gear/pull/425) then
integrated the [PR #417](https://github.com/ronnierosal/Re-Gear/pull/417)/[PR #418](https://github.com/ronnierosal/Re-Gear/pull/418)
stack (first-time USB4 authorization, PipeWire sink readiness, production
sleep/shutdown admission and UI wiring, multi-connector display aggregation) and
the authorization-hold fix `5887900` as merged `main` `fb334f2`. The package
version on `main` at that checkpoint was 0.3.153. `Re-Gear-0.3.154.zip` at build revision
`f6be3ed` is a separate local development artifact built from the same source.

Evidence tiers used in the table:

- **Source** — implemented and merged in `main` (revision noted), with software tests.
- **0.3.154** — included in the 0.3.154 package.
- **Previously observed** — hardware behavior recorded on an earlier build, on
  the maintainer's single configuration only.
- **Awaiting** — still needs supervised 0.3.154 validation on the Ally.

| Capability | Source | 0.3.154 | Previously observed on hardware | Awaiting 0.3.154 hardware validation |
|---|---|---|---|---|
| **First connection and authorization.** USB4/eGPU attachment observed in Gaming Mode; first-time device popup; **Allow once** authorizes this attachment; **Always trust** shown only when the backend reports remembered trust; success requires a verified backend readback and never claims GPU, TV or audio readiness | Yes (`fb334f2`, PR #425) | Yes | No authorization popup trial recorded | Popup appearance, both choices, readback, and that a verified approval leads into the normal connection flow |
| **Connection progress and automatic TV.** Compact staged progress for USB4 link, GPU, external display, audio and Gaming Mode readiness; blocked prerequisites show **Needs attention** with the backend reason; automatic TV switching and bounded retries after physical connection preserved; dynamic **Switch to TV** / **Switch to Handheld**; TV audio readiness from real PipeWire sink observations | Yes (#420/#421; sink fix in `fb334f2`) | Yes | Automatic TV after physical connection on 0.3.98 and 0.3.129; both display switches on 0.3.129 | Stage cadence, **Needs attention** reasons, audio readiness with the real sink, retries |
| **eGPU status.** Overall status follows the lifecycle result; USB4 link, GPU rendering, external display, display output, session and game state kept as separate facts; multiple external connectors aggregated (any verified active connector wins, all must be verified off for a negative); stale or unavailable observations shown as unknown/unavailable | Yes (#420; aggregation in `fb334f2`) | Yes | Status display on earlier builds; aggregation not observed | Correct status with the TV on a later connector; stale/unavailable rendering |
| **Ordinary Safe Disconnect.** Return picture to the Ally display, release active holders, remove the GPU and dock USB branch, deauthorize the USB4 tunnel, then instruct the player to physically unplug | Yes | Yes | Passed on 0.3.98 (supervised), 0.3.127 (maintainer report) and 0.3.129 (supervised) | Regression check that 0.3.154 still passes this acceptance baseline |
| **Still-connected authorization hold.** Immediately before USB4 deauthorization, a remembered device's policy changes from automatic to manual so `boltd` cannot reauthorize a still-cabled eGPU. The hold is bound to the exact operation, attachment identity, generation and internal device UUID. After strict physical-absence verification, automatic policy is restored for the next physical connection. Internal UUIDs never cross the RPC, diagnostic or log boundary | Yes (`5887900`, merged in `fb334f2`) | Yes | No | That the dock stays off while cabled, and automatic policy returns after unplug |
| **Disconnect + Sleep.** Production backend admission and UI wiring. Sequence: return to Ally display → Safe Disconnect → tell the player to unplug → verify physical removal → continue the original sleep request before its deadline | Yes (`fb334f2`, PR #425) | Yes | 0.3.129 attempt **failed** before software-down; source fixes followed ([PR #383](https://github.com/ronnierosal/Re-Gear/pull/383)) | The complete journey, deadline behavior and wake |
| **Safe Disconnect + Shutdown.** Production backend admission and UI wiring. Sequence: return to Ally display → guarded disconnect → continue the original shutdown request. The implementation does not intentionally disable USB-C Power Delivery; retained charging is the design intent, not an observed 0.3.154 result | Yes (`fb334f2`, PR #425) | Yes | Clean manual shutdown with continued charging observed on 0.3.98 (not this one-button path) | The complete one-button journey, and whether charging is actually retained |
| **Next physical connection.** After physical unplug and reconnect, remembered authorization can return to automatic policy and the preserved automatic connection and TV flow runs again | Yes | Yes | Physical replug with automatic TV return on 0.3.98 and 0.3.129 (before the authorization hold existed) | Replug after the hold is released |

**Excluded — not supported and not to be documented as supported:**

- Software reconnect, and software reauthorization used as a reconnect mechanism.
  Reconnection is physical replug only.
- Any powered reconnect trial.
- Sleeping while the eGPU stays logically connected ("sleep connected"). It is
  not an offered lifecycle action.
- Treating software removal or source behavior alone as clearance to unplug the
  cable. Physical unplugging follows the exact product prompt, and only on a
  supervised or qualified setup; 0.3.154 has no device validation.
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
[CURRENT_STATE](../../CURRENT_STATE.md). Any later installed or hardware result
belongs there with its exact build identity; this historical snapshot does not
substitute for that evidence.

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

Historical source/acceptance snapshot. The next acceptance target is the exact
0.3.180 candidate above; the original tested revisions and gaps remain below.

Entry points below were inspected in merged source `9421c6f` (the sleep/shutdown row
was re-checked against merged `fb334f2`), with the later
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
| Sleep/shutdown continuation | **Disconnect + Sleep** or **Safe Disconnect + Shutdown** request | `_run_dock_power_request`, `whole_dock_sleep`, `whole_dock_shutdown`; UI request coordinator | Correlated original intent, completed teardown, strict physical-absence verification before sleep, deadline | At most one continuation; sleep success requires observed kernel cycle | Sleep waits awake for verified physical absence and is not submitted after its deadline; failed prerequisites stay awake. Connected sleep is not an offered action | Production admission and wiring merged in `fb334f2` (PR #425); packaged in the local 0.3.154 artifact; not a hardware pass | 0.3.98 manual sleep after teardown blocked; 0.3.129 **Disconnect + Sleep** failed before software-down | eGPU + UI | Supervised 0.3.154 sleep and one-button shutdown journeys |
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
