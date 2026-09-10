# Product definition

## Brand identity

The player-facing brand is **Re-Gear**, formerly Handheld Dock Mode (HDM).
Use that spelling and capitalization in new UI and product copy. The existing
status colors and functional icons remain unchanged; the README and plugin use
the supplied Re-Gear brand artwork. Historical evidence retains its original name.

Current repository builds use the `Re-Gear` Decky directory, the `regear` Python
package, the `re-gear-steamos` distribution name and the `regear-diagnose` source
installation entry point. Existing state/helper paths, preference keys and
managed-file markers retain their exact bytes to preserve recovery and upgrades.
See [rebrand completion](REBRAND_COMPLETION_2026-09-10.md) for retained identities
and reasons. Repository changes do not establish a release, installed migration
or supervised rollback success.

## Objective

Re-Gear's North Star is console-like SteamOS handheld gaming: systematically reduce
PC-gaming paper cuts by detecting problems, preventing avoidable failures,
explaining state in player language, and safely guiding or performing verified
recovery where authority and evidence allow. Docking and eGPU safety are the
first domains, not the product boundary. The current scope remains narrowly
limited to the implemented, evidence-gated capabilities below.

Games always come first. Re-Gear is a lightweight, mostly dormant SteamOS
reliability layer: it must not become a performance problem while it removes
avoidable friction and makes uncertain state understandable.

## Target user-facing placement

- **Portable:** internal GPU renders to the internal panel.
- **Boosted Handheld:** a verified eGPU renders to the internal panel.
- **Docked-iGPU:** the current game remains on the internal GPU while its
  presentation is verified on the external display.
- **Docked-eGPU:** a verified eGPU renders to its directly attached external
  display.

These labels are derived only from independently observed render-GPU and display
state. Incomplete or conflicting evidence is reported as Unknown or Degraded.
The current executable `TV Docked` label corresponds only to the target
Docked-eGPU placement. Docked-iGPU is research, not an implemented claim.

Connecting, Preparing to disconnect, Safe to disconnect, Returning to portable,
Sleep pending disconnect, Action required, and Failure are workflow phases, not
placement modes. Re-Gear keeps both dimensions visible internally so a pending or
failed operation cannot overwrite observed hardware truth.

## Product behavior

Every future transition follows:

```text
DETECT → VALIDATE → PLAN → PREPARE → APPLY → VERIFY → COMMIT
                                      │
                                      └─ failure → ROLL BACK or retain known-good state
```

Manual and automatic requests use the same policy and transition engine.

## Experience and runtime principles

Re-Gear is performance-first: it remains event-driven and dormant whenever no
transition, fault, or explicit player request requires work. Adaptive polling
is permitted only where an event source is unavailable, must have bounded
cadence and cost, and must defer nonessential analysis while a game is active.
Any measurable game-performance regression attributable to Re-Gear is a defect.

Observed placement is not a complete player experience. Re-Gear's target model uses
a separate health dimension: **Ready**, **Recovering**, **Degraded**, or
**Attention Required**. Implemented typed aggregation uses available observations;
independent controller/audio inputs and production integration retain their own
validation gates in [Roadmap](ROADMAP.md). It
must never guess a healthy experience merely because a device is present.
Detailed diagnostics remain optional and technical evidence stays out of the
happy path.

Player-facing wording is capability-based: **handheld**, **eGPU**, and
**external display**, rather than a particular manufacturer or model. Exact
device/eGPU names belong only in profile detection, diagnostics evidence, and
certification documentation.

Physical controls and UI affordances resolve to typed logical requests such as
Safe Undock, Return to Handheld, Recovery, or Change Performance Profile. They
must all enter the same authoritative transition engine. The controller hotkey candidate
opens the existing confirmation and approval flow; it is not a parallel detach
implementation. Native event delivery still requires hardware validation.
The physical power button remains platform-owned: Re-Gear must not delay, suppress,
or synthesize ordinary Sleep merely to recognize a gesture. See [physical
power-button Safe Undock feasibility](POWER_BUTTON_SAFE_UNDOCK.md).

Until a verified global controller-event source exists, the Decky panel owns
the controller-focusable fallback. **Prepare G1 disconnect** first routes the
dock through the ordinary verified Portable transition. After its durable
result is acknowledged, the same control may request a normal shutdown from a
fresh idle Portable observation. “Safe” means the Ally has completely powered
off; this workflow does not promise powered live removal.

Manual TDP and optional Auto TDP controls are implemented in the development
source. Provider support, installed behavior and hardware validation remain
separately gated; see [TDP control](TDP_CONTROL.md). Saving preferences never
activates control. This does not authorize automatic graphics tuning, game
configuration writes, travel automation, or controller wake.

Offline Readiness combines bounded local Steam evidence with selected-game
guidance, confidence labels, and temporary game-tile badges. A reviewed,
local-only, identity-minimized source must meet the bounded-cost admission
contract; missing or stale evidence remains uncertain. There is no automatic
game launch, network change, or offline-launch guarantee. See
[source evidence and limits](OFFLINE_EVIDENCE_SOURCE_REVIEW.md),
[UI contract](OFFLINE_READINESS_UI.md), and the confidence semantics below.

## Command Center and module direction

The approved interface direction puts immediate controls and status in Command
Center, with deeper configuration in Modules. The complete rebuild remains in
development; existing Quick Access navigation is not evidence that the new shell
has shipped. See [Wiki/interface structure](WIKI_INFORMATION_ARCHITECTURE.md) for
the approved layout and screenshot policy, and [UI specification](UI_SPEC.md)
for implemented interaction contracts.

eGPU, performance and controller controls share existing state and guarded action
ownership. Read-only status links never mutate hardware. Unsupported capabilities
remain unavailable; a prepared Safe Disconnect tile does not authorize live unplug.

## Interrupted docked-sleep recovery policy

**Product intent; not current hardware behavior:** if an eGPU is removed while
the handheld sleeps and wake leaves the original game/session no longer
running, Re-Gear should first establish a usable handheld path. It may describe
handheld recovery only after independent display, input, and audio verification.
It must not claim that a game crashed, that sleep caused the loss, or that
recovery succeeded without that evidence.

Only after those checks are complete, and only when the current game has no
known update, cloud-sync, or repeat-failure concern, the intended default is to
offer a safe game relaunch. On the first successful use of that capability, Re-Gear
will show one non-intrusive choice to keep automatic restart enabled or turn it
off. That preference is future player policy, not authority to bypass Steam,
game, save, update, or recovery gates.

The locally implemented foundation is limited to a privacy-safe canonical sleep
checkpoint, a redacted terminal result, post-wake evidence classification, and
deduplicated notification policy. Production still needs owner-checked startup
wake wiring, game/update/sync/repeat-failure evidence, a reviewed relaunch
adapter, recovery verification, and supervised hardware validation.

## Decky-native delivery

Re-Gear is a Decky Loader-native plugin. Its player interface uses Decky's Quick
Access components and typed Decky RPC. The Python backend runs under Decky's
managed plugin lifecycle; there is no separate web dashboard or general-purpose
command endpoint. Root privilege is isolated to narrow observation and explicitly
approved mechanisms, while policy remains pure and testable.

## Initial scope and current evidence

Initial work established read-only discovery, sleep protection, and guarded
process-release foundations. Later development added guarded display transitions,
audio handling, support export, local Offline Readiness delivery and power
controls. These are not all equally validated or installed.

Exact profiles and certification limits belong in [Hardware support](HARDWARE_SUPPORT.md).
The [roadmap](ROADMAP.md) and [dated reconciliation](DOCUMENTATION_CLEANUP.md)
link current source evidence; historical device records remain dated. The
[deployment strategy](DEPLOYMENT_VALIDATION.md) defines separate hardware gates.
Neither the growing implementation nor the live-disconnect development objective
changes the current physical-disconnect safety contract.

## Non-goals for the initial release

- Windows support
- Every handheld or eGPU
- Physical live eGPU removal
- Running-workload GPU migration
- Arbitrary desktop Linux distributions
- GPU tuning, fan control, overclocking, or driver installation
- TV network automation, cloud services, or a general plugin ecosystem


### Offline confidence implementation

The selected-game frontend now distinguishes Needs preparation, Likely
offline-ready, Tested offline, and Unverified. These are confidence labels,
not guarantees or replacements for the backend entitlement classification.
Likely requires independent local preparation and explicit cached single-player
internet-compatibility evidence. Tested requires an explicit player attestation
bound to the displayed account/build and a fresh matching recheck. Confirmation
lasts at most 24 hours in the current plugin session, with a Forget control.
No automatic game launch, network change, external query, or persistent play
history is introduced. Source handling and limits are owned by
OFFLINE_EVIDENCE_SOURCE_REVIEW.md. This delivery extends the pure classifier without changing its conservative
backend evidence contract.
