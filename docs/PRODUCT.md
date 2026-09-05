# Product definition

## Brand identity

The player-facing brand is **Re-Gear**, formerly Handheld Dock Mode (HDM).
Use that spelling and capitalization in new UI and product copy. The existing
status colors and functional icons remain unchanged; the README and plugin use
the supplied Re-Gear brand artwork. Historical evidence retains its original name.

This is a presentation-only rebrand. Decky identity `Handheld Dock Mode`,
package/install directory `HandheldDockMode`, `hdm` modules and commands,
`handheld-dock-mode` state/helper paths, stored preference keys, and managed-file
markers remain unchanged for compatibility. Their migration requires separate
upgrade, rollback, and safety-state continuity tests. The Decky plugin list may
therefore still show the legacy name while the opened panel shows Re-Gear.

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
**Attention Required**. Its future typed aggregation will report whether
verified display, input, audio, eGPU/link, and session evidence is usable; it
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

Current scope does not include TDP control, automatic graphics tuning, game
configuration writes, Steam Library badges, travel automation, or controller
wake. Future work must place those behind narrow telemetry, device-profile,
and game-adapter boundaries and preserve the same recovery and explicit-consent
rules.

**Implemented foundation only:** Offline Readiness is a pure local classifier
for supplied categorical install, download, entitlement, cloud-save, storage,
and known online-check evidence. Its strongest positive result is **ready to
try offline**, never a launch guarantee. It has no Steam collector, account or
game-title delivery, persistence, UI, or automation.

**Implemented admission contract only:** a future source may supply evidence
only after a reviewed, local-only, identity-minimized, benchmarked declaration
passes its bounded-cost gate. Results must be fresh; stale, unreviewed, or
cost-unverified evidence is **Unknown**, never offline-ready. No collector is
implemented or authorized.

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
command endpoint. Root privilege is isolated to narrow observation and future
approved mechanisms, while policy remains pure and testable.

## Initial scope

The first certified profile is:

- ASUS ROG Ally X
- SteamOS
- GPD G1 with AMD Radeon RX 7600M XT
- TV connected through the G1 display output

Milestone 0.1 implements reliable read-only discovery and diagnostics. The first
approved 0.2 mechanism is a reversible login1 sleep-inhibitor lease for the G1;
display/GPU transitions remain unavailable. Guarded non-game process release is
implemented as an experimental Decky-native 0.2 flow with redacted inspection,
explicit approval, durable journaling, mandatory rescans, and separate force
confirmation; supervised disposable-process validation remains pending.

The proposed eGPUBridge-derived feature selection, including sleep blocking and
guarded process closure, is documented in
[eGPUBridge feature review for Re-Gear](EGPUBRIDGE_FEATURE_REVIEW.md). These are 0.2
candidates. The sleep guard and guarded process release are now explicitly in
0.2 scope; other mutation boundaries remain closed until their own design and
validation gates pass.
The complementary [Steam sleep preflight](ADR_STEAM_SLEEP_PREFLIGHT.md) is now
implemented and has passed its non-sleep lease-lifecycle proof. Sleep protection
is not considered complete until its supervised request proof also passes.
Read-only responsiveness instrumentation, adaptive Decky refresh, progressive
connection states, and the [privacy-safe support bundle](SUPPORT_BUNDLE.md) are
also implemented in 0.2. They do not authorize display/GPU mutation or live
hardware removal.

The reconciled product ordering and evidence status are maintained in the
[authoritative roadmap](ROADMAP.md). Its staged
[deployment and validation strategy](DEPLOYMENT_VALIDATION.md) is a release
gate for hardware-facing work.

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
OFFLINE_EVIDENCE_SOURCE_REVIEW.md. Earlier foundation-only snapshots above do
not describe this later frontend delivery.
