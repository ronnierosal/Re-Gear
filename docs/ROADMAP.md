# Authoritative roadmap

This roadmap reconciles the product north star with the behavior present on
`main`. Product intent does not constitute executable or hardware evidence.
Detailed work items remain in [Backlog](BACKLOG.md); completed hardware
observations remain in the dated validation records.

Meaningful verified checkpoints and worker integrations are recorded concisely
in [Operator handoff](OPERATOR_HANDOFF.md), with evidence status, blockers,
verification, and the next safe task. Product intent never upgrades an
Implemented or Simulated item to Hardware Validated.

## Evidence vocabulary

HDM uses these labels consistently:

- **Designed:** documented, but no executable proof.
- **Implemented:** code and deterministic tests exist.
- **Simulated:** replay or failure-injection tests pass without hardware.
- **Installed:** the exact built artifact is present on a device.
- **Hardware tested:** a bounded supervised test produced captured evidence.
- **Verified:** all acceptance criteria for the stated combination passed.
- **Certified:** verified behavior is supported for a named hardware/software
  profile and version range.

No broader label may be inferred from a narrower one.

## Current baseline: 0.2.0 on `main`

| Capability | Current evidence | Remaining gate |
|---|---|---|
| Decky-native plugin lifecycle and typed RPC | Implemented and hardware tested | Release packaging/publishing is separate. |
| Read-only host, DRM, Gamescope, game-scope, PCI, USB4, and G1 discovery | Implemented and hardware tested on Ally X/G1; exact DMI tuple, bound-driver topology, backend identity binding, typed capability diagnostics, and fail-closed partial PCI/USB4 candidate presence are locally regression tested | Revalidate the stricter matcher and diagnostic presentation on hardware after material firmware/SteamOS/kernel changes. |
| Exact G1 DRM/audio clients and storage blockers | Implemented and hardware tested read-only | Guarded signaling remains simulated and requires supervised proof. |
| Portable inference | Implemented and hardware tested | Other presentation modes remain unverified in native HDM. |
| Backend login1 sleep inhibitor | Implemented and hardware tested | It prevents suspend but cannot alone preserve Steam presentation. |
| Steam-native preflight blocker | Implemented; lifecycle and blocking behavior hardware tested | Corrected persistent warning dialog still needs one supervised visible proof. |
| Adaptive polling and discovery timings | Exact attach and correlated unexpected-loss sampling run at 250 ms. Automatic attach now requires four distinct consecutive fully-ready samples; repeated samples or any gate regression resets the quorum. | Measure cable-to-PCI, PCI-to-DRM/EDID, ready-quorum, restart, and active-TV timelines separately. Kernel enumeration and Gamescope restart remain independent latency budgets. |
| Redacted support-bundle preview/token/save | Implemented and simulated; includes bounded categorical peripheral observation state when available | Controller-visible preview and save acceptance remain pending. |
| Display/GPU transitions | Durable guarded orchestrator, boot-scoped Gamescope shim/config store, fresh exact-G1 launch binding, reversible conflict-aware drop-in manager, fixed user-service command boundary, presentation mechanism, Decky-native preparation, visible TV and Portable targets, and an off-by-default persistent automatic-dock opt-in with a one-shot exact/stable/idle coordinator are implemented. One exact Ally X/G1 automatic attach on installed `0d66127cd0c2` visibly activated the TV, selected the RX 7600M XT, and committed. All presentation controls use the same transition engine. | Repeat-cycle, controller-driven return-to-Portable, and startup recovery hardware proof remain. |
| Shutdown-before-disconnect workflow | Controller-focusable Decky flow, TV-to-Portable revalidation, durable target-aware redock suppression, 30-second single-use shutdown approval, changed-evidence rejection, and fixed root-only no-block power-off adapter are implemented. Installed `a988c0cf1d61` returned successfully to Portable in a watched run. | D5.2 failed because the Ally lost networking but retained fan and two top LEDs until a manual long power-button hold. Command acceptance remains physically unverified; complete-off and next-boot/reconnect proof remain. It does not enable powered live removal or the dormant Guide + Y listener. |
| Exact G1 TV audio handoff | Direct supervised G1 HDMI selection is hardware exercised. A guarded presentation child now records the current Portable default, freshly resolves the exact G1 PipeWire loopback sink, changes and verifies the default, and rolls back on presentation failure. | The automatic path and Portable restoration are implemented/simulated but require one watched hardware cycle before capability promotion. |
| Docked-iGPU promotion/recovery path | Durable transition path plus bounded natural-exit watcher, serialized lifecycle, non-authorizing preview composition, and single-owner async driver are implemented and simulated; production runs the watcher in no-preview mode and exposes identity-free status/acknowledgement | Hardware proof, production read-only preview construction, and separately gated confirmation/execution remain. |
| Process release/termination | Approval/classification, redacted Decky inspect/confirm flow, guarded facade, Linux pidfd adapter, mandatory re-scan runner, root-owned durable pre-signal journal, and no-repeat startup recovery implemented and simulated | Supervised disposable-process proof remains. |
| Physical G1 live removal | Unsupported. One idle pull natively recovered after approximately 80 seconds, but did not prove clean teardown or repeatability. A bounded local supervisor now observes and verifies native Portable recovery without restarting Gamescope. | A separate teardown experiment must prove removal safe before capability enablement; the supervisor and post-recovery audio restore remain simulated. |
| Typed placement/workflow/capability and journal contracts | Implemented and unit tested | Decky request facade and mechanism wiring remain gated. |
| Atomic fixed-path transition journal store | Implemented and unit tested; constructed for process release | Presentation/sleep orchestration wiring and supervised persistence proof remain. |
| Transition snapshot replay and failure injection | Implemented and simulated | No production display/GPU mechanism endpoint exists. |
| Remote read-only capture harness | Implemented and hardware tested unprivileged; captures the static archive build label and compares its short revision only against a clean local checkout, alongside fixed-file hashes | Its fixed root read-only mode is locally verified but unavailable on the current Ally because non-interactive sudo is refused. Neither mode can observe the Decky-owned sleep lease. Build metadata is provenance only, not hardware validation. |
| Guarded process-release approvals | Implemented and simulated in Decky-native flow | Supervised disposable-process proof remains. |
| Process-release signal/re-scan runner, audit, and journal | Implemented and simulated | Supervised mechanism proof remains; hardware removal authority is always false. |
| Exact-instance Linux pidfd signal adapter | Implemented, unit tested, and guarded by Decky orchestration | Supervised disposable-process proof remains. |
| Canonical sleep/disconnect reducer + durable coordinator | Implemented and simulated, delivery-independent | Save/removal/display/sleep mechanisms, Decky wiring, and supervised proof remain. |
| Exact-identity guarded game-close child | Implemented and simulated, mechanism-injected | Production SteamOS close mechanism, Decky delivery, and supervised proof remain. |
| Exact-recipe verified game-save child | Implemented and simulated, proof/mechanism-injected | Reviewed production recipes, proof/mechanism adapters, Decky delivery, and per-game hardware proof remain. |
| Backend-owned canonical sleep delivery facade | Implemented and unit tested, dormant | Decky RPC/UI wiring, physical-button interception, all directive mechanisms, and supervised proof remain. |
| Independent game compatibility dimensions and review gate | Implemented and unit tested, with dormant fixed-path atomic persistence and a backend-only reviewed-evidence transaction service | Collection UI, production plugin construction, intentional hardware tests, and catalog publication remain. |
| Temporary verbose diagnostic logging | Policy and Decky controller flow implemented and simulated; explicit consent, four bounded durations, status/countdown, disable, sanitization, rotation, and reboot reset are wired | Controller-visible and expiry acceptance remain. |
| Optional troubleshooting overlay | Implemented and frontend tested, off by default | Controller-visible hardware acceptance remains. |
| Exact Steam-scope AppID extraction | Implemented and unit tested, internal read-only | Steam title/version and consumer wiring remain. |
| Private active-game process/runtime evidence | Implemented and unit tested, dormant read-only | Exact Proton version, consumers, Decky wiring, and hardware proof remain. |
| Bracketed game/eGPU render-client correlation | Implemented and unit tested, dormant read-only | Production consumers and hardware comparison with engine evidence remain. |
| Bounded exact DRM engine-activity evidence | Implemented and simulated for independently re-resolved Ally internal and G1 bindings; one-shot shared-window categorical comparison is wired into existing Support Preview | Hardware proof, continuous consumers, and reviewed compatibility use remain. |
| Independent hardware capability catalog and review gate | Implemented and unit tested, with dormant fixed-path atomic persistence and a backend-only reviewed-evidence transaction service | Collection UI, production plugin construction, and intentional capability tests remain. |
| Reduced transition/compatibility support context | Implemented and privacy tested, dormant optional input | Live owners and controller-visible preview acceptance remain. |
| eGPU attach readiness watch | Implemented and simulated; an exact attach candidate, including a partial-USB4-to-exact-profile sequence, is bound to the same private eGPU identity and a later fresh observation reports settling, display readiness, observed exact-bridge link health, running-game, or Action Required state. An opted-in backend coordinator may consume `ready_idle` once and only through the shared transition engine. | Hardware proof of the automatic path and a future operating-system event source remain pending; the current implementation uses bounded polling. |
| Compatibility Test Mode session policy | Implemented and simulated with dormant exact internal-baseline/external-render collectors and a read-only player-initiated graceful-exit collector, each session-bracketed; an application-only single-session temporary-diagnostics lifecycle and an unwired identity-free status mapper are available | Plugin construction/UI, persistence, supervised game-specific save evidence, trusted hardware runs, and reviewed tests remain. The future gate is documented with explicit stop/recovery criteria. |
| Secure support-submission approval/protocol | Implemented and unit tested, dormant | Fixed TLS client adapter is unwired; Cloudflare Worker/R2 deployment, endpoint configuration, abuse controls, and UI remain. |

## Required architecture corrections

The expanded product model is accepted with these boundaries:

1. **Observed placement and workflow phase remain separate.** Portable,
   Docked-iGPU, Boosted Handheld, and Docked-eGPU describe verified render and
   presentation placement. Connecting, PreparingToDisconnect,
   SleepPendingDisconnect, ReturningToPortable, ActionRequired, and Failure are
   workflow phases. A phase must not overwrite observed hardware truth.
2. **Capabilities are profile data, not scattered conditionals.** Host and eGPU
   profiles conservatively expose support for display, audio, controller,
   sleep, and removal mechanisms. Unknown profiles inherit no mutation rights.
3. **The transition engine owns every mutation.** Manual, automatic, sleep,
   recovery, and future game-restart requests use one journaled
   TRY/OBSERVE/VERIFY/COMMIT engine with bounded recovery.
4. **Game identity is independent evidence.** `game_state=running` remains the
   safety minimum; AppID, title, process tree, Proton, and rendering GPU are
   additional typed observations and may each be unknown.
5. **Compatibility records never self-certify.** Game and hardware test results
   require intentional review before promotion to Verified or Certified.
6. **Performance is a runtime budget.** HDM prefers event-driven observation;
   any required polling has a bounded cadence, does not overlap expensive
   scans, and defers nonessential work during an active game. Telemetry is a
   shared, lightweight evidence source rather than a collection of optimization
   loops.
7. **Health and controls are independent contracts.** Placement does not imply
   a usable display, controller, audio route, or eGPU link. Future physical
   button/controller delivery maps to typed logical requests and enters the
   same transition engine as Decky UI actions.

## Safety conflict: current G1 removal

The desired one-press flow ends with a physical eGPU disconnect followed by
automatic sleep. That flow is not currently available for the certified G1
profile: prior teardown evidence includes AMDGPU removal stalls, and
[Safety invariant 10](SAFETY_INVARIANTS.md) requires internal restoration and
shutdown before disconnect.

The eventual workflow must therefore branch on an explicit removal capability:

- `live_removal_verified`: the engine may verify SafeToDisconnect, wait for
  removal, recover Portable, and continue the original sleep request.
- `shutdown_before_disconnect`: the engine may prepare internal state and offer
  a shutdown-first flow, but must not claim live removal is safe.
- `untested`, `unknown`, or `known_issue`: fail closed and provide diagnostics.

The GPD G1 remains `shutdown_before_disconnect`/known issue until a separately
approved supervised experiment proves otherwise.

## Ordered roadmap

### R0 — Close current installed acceptance gaps

- Prove the corrected Steam warning is visible and persistent during one
  supervised blocked Sleep request.
- Prove controller-visible support preview and exact token-approved save.
- Record installed artifact identity and redacted before/after evidence.

Exit: warning and support UI are hardware tested without suspend, display
mutation, process signaling, or eGPU removal.

### R1 — Read-only control-plane foundation

**Status:** IMPLEMENTED AND SIMULATED — typed contracts, bounded journal schema,
fake clock/mechanisms, snapshot replay, asynchronous-event policy, and remote
read-only capture are implemented. The installed-device capture path has a
read-only hardware proof; no transition mechanism is enabled.

- Add typed placement state, workflow state, request intent, capability records,
  transition plans, deadlines, structured failures, and recovery outcomes.
- Add a durable, bounded, privacy-safe transaction journal contract.
- Add deterministic snapshot replay and a fake clock/mechanism harness.
- Replay partial ordering, stale evidence, timeouts, unexpected unplug,
  controller loss, and recovery failure.
- Add remote-safe capture tooling that performs observation only.

Exit: pure policy and simulator prove state/phase separation and fail-closed
behavior. R1 introduced no production mutation endpoint; R2 owns the later
guarded process-release boundary.

### R2 — Guarded non-game eGPU client release

**Status:** IMPLEMENTED AND SIMULATED — backend-owned preview/token/revalidation,
typed signal/re-scan flow, deadlines, privacy-safe audit, root-owned durable
pre-signal journaling, no-repeat startup recovery, and the guarded application
facade are composed into Decky-native inspect/confirm/execute/acknowledge RPCs.
Private graceful evidence remains behind an opaque, expiring, single-use force
receipt. No PID, signal, command, or path comes from the frontend.

- Generate backend-owned previews for exact eligible process instances.
- Bind short-lived single-use approval tokens to candidate set, device identity,
  resources, and observation generation.
- Revalidate before each bounded graceful signal; re-observe after each action.
- Keep force closure behind a second explicit approval.
- Never signal protected, system, other-user, storage, or unknown clients.

Exit: unit/replay/PID-reuse/failure-injection tests pass, followed by supervised
disposable-process validation. This does not enable physical removal.

### R3 — Manual verified transition engine and recovery

**Status:** DURABLE GUARDED ORCHESTRATOR IMPLEMENTED AND SIMULATED; PREPARATION
HARDWARE-EXERCISED; TV-SWITCH ACCEPTANCE FAILED ON FIRST ATTEMPT — a one-step
manual Portable↔Docked-eGPU plan is produced only from exact runtime profile,
device/display binding, game, display/render, and source-rollback evidence. A
two-minute single-use backend permit can authorize one explicitly confirmed
Experimental Ally/G1 plan without promoting the capability. The engine
re-observes before apply, journals before mutation, verifies within deadlines,
recovers after failure or a non-durable commit, and handles interrupted
journals without resuming the target request. No active presentation mechanism,
Decky construction, or RPC exists. The first packaged Gamescope shim/config
boundary is implemented and simulated but remains inactive: it installs no
override and cannot restart Gamescope. Exact Gamescope-owner resolution and a
fixed root-to-user command runner are also implemented and unwired; no plugin
path invokes the runner. Reversible fixed drop-in management is simulated and
fails closed on competing `PATH` ownership, including eGPUBridge. The dormant
presentation mechanism composes these parts with immediate config rollback on a
synchronous restart failure; the orchestrator still independently verifies or
recovers the observed placement. Approval-gated integration preparation is also
simulated; it can install/reload/verify without restarting Gamescope and rolls
back a new drop-in on failure.

- Implement one idempotent Portable/Docked transition path with journal,
  precondition re-observation, verification, rollback, and crash recovery.
- Restore a known-good internal display path before any shutdown/removal advice.
- Treat game-running or unknown game state as a blocker whenever Gamescope would
  restart.

The Decky preparation endpoint is hardware-exercised: an old eGPUBridge `PATH`
override was removed separately and recoverably, HDM installed its own
reversible drop-in, and the user service was reloaded/verified without a
Gamescope restart. The first watched ready-TV attempt did not switch to TV; the
shim safely used the internal panel because the transaction wrote its
shim-facing config to the root-only journal directory. `8c721fb` writes that
launch config to the exact prepared user's state directory while retaining the
root-owned journal. This is a corrected implementation, not a hardware pass.

Exit: simulation passes first; then a fresh supervised Ally X/G1/TV test of the
corrected build with G1 connected naturally, game idle, before/attempt/after
evidence, and no live unplug. Automatic attach remains disabled regardless of
that single test.

### R4 — Canonical sleep request orchestration

**Status:** COORDINATOR IMPLEMENTED AND SIMULATED — Steam-menu and physical
button sources enter one generation-bound service; request expiry, consent/save
branching, process-release routing, removal capability, independent removal
readiness, Portable recovery, original-request continuation, fresh verification
samples, append-only persistence, exact acknowledgement, and fail-closed restart
recovery are covered. An exact AppID/scope game-close child now binds explicit
single-use consent to the same parent operation, persists before its injected
mechanism, and advances only after a fresh verified Idle observation. No
production game-close or live sleep mechanism and no sleep-continuation RPC is
enabled. A verified-save child now binds the already-granted close consent to
one exact reviewed recipe and requires an independent new Verified proof before
unlocking close; no production recipe or adapter is present. A dormant delivery
facade now owns request IDs/generations and exposes privacy-safe result/status,
exact operation-bound consent/cancel, recovery, and acknowledgement without
executing any directive.

- Normalize Steam menu and physical-button attempts into one request intent
  where the platform exposes a verified interception mechanism.
- Obtain consent before closing a game; add save capability warnings without
  claiming universal autosave.
- Release only classified clients, verify final state, and choose the
  profile-specific removal/shutdown branch.
- Resume the original sleep request only when its complete preconditions are
  verified and the request has not expired or been cancelled.

Exit: simulator covers every branch. G1 certification remains limited by its
removal capability.

Composition status: guarded process release is now a child step of the same
sleep transaction journal in the application/simulation layer. It does not run
two authoritative journals or drop pre-signal persistence. Decky sleep delivery
and live mechanisms remain gated. Guarded game close uses the same composition
rule and records no AppID or scope identity in the journal. A
verified-triggerable-autosave game remains blocked unless the save child proves
completion for that exact parent request. The 26-target sleep-child release
bound leaves room for save, close, graceful plus force release, every remaining
sleep stage, and recovery within the 128-entry journal.

Read-only G1 suspend investigation now has a bounded exact-topology PCI
wake-capability/runtime collector in the remote capture payload. It exports
only categorical aggregate evidence and does not identify a wake source or
change any wake/power setting. The same categorical evidence is now included
only in an explicit redacted support-bundle preview, never normal polling.
The local wake-capture comparator can show aggregate evidence changes between
two already validated read-only captures without reconnecting to the Ally or
attributing a wake source.
Actual suspend/resume proof remains a supervised D6 hardware gate; see
[G1 suspend/wake diagnostics](SUSPEND_WAKE_DIAGNOSTICS.md).

### R5 — Unexpected-undock recovery

**Status:** APPLICATION COORDINATOR IMPLEMENTED AND SIMULATED — unsolicited and
exact canonical sleep-pending loss remain distinct, and both route only through
fresh detect/validate/attempt/verify/commit Portable recovery. The coordinator
returns a bounded identity-free trace, uses a separately bounded
Portable-preservation fallback, and rejects stale/unknown evidence. It has no
sleep port: a verified sleep-pending result only requests a later canonical
transaction re-check. Production topology, display/GPU, audio, controller,
Decky, journal/facade, and startup-recovery wiring remain gated. Physical G1
removal remains unsupported. See
[Unexpected-undock recovery coordinator](UNEXPECTED_UNDOCK_RECOVERY.md).

A pure snapshot-delta detector now supplies only exact attach, eGPU-removal,
or external-display-loss candidates. It has no event source or execution
authority: a future watcher must still feed its result into the shared policy
and transition authority. Missing, reused, ambiguous, or unproven loss evidence
is explicitly unverified.

- Distinguish unsolicited loss from an expected SleepPendingDisconnect event.
- Restore internal display, audio, and controls; verify Portable; never sleep
  after an unsolicited unplug.

Exit: deterministic replay is implemented. Production exit still requires the
shared serialized transition authority, reviewed SteamOS event/mechanism
adapters, audio/controller recovery coverage, and a separately approved D6
hardware test on a profile with verified live removal. Any test that can strand
SSH remains supervised; the GPD G1 is not eligible.

### R6 — Docked-iGPU research and game-aware launch policy

**Status:** PARTIAL READ-ONLY FOUNDATION IMPLEMENTED — exact Steam AppID/scope
identity can be enriched with bounded PID/start-time process instances,
parent/launcher relationships, executable basenames, and native-versus-Proton
classification. All exact identity remains private and fail closed; the only
production consumer is the existing user-invoked Support Preview, and no
mutation, relaunch path, or new Decky RPC exists. See
[Active game runtime evidence](GAME_RUNTIME.md). Stable exact game processes can
also be correlated with a complete exact G1 client scan to prove render-node
ownership or absence, but that result deliberately does not claim active
rendering or identify another GPU. A separate bounded DRM `fdinfo` sampler can
now prove that one exact game's engine counters increased on one exact GPU
during a stable sample window. Exact read-only Ally internal and G1 binding
resolvers revalidate their profiles and one render node before sampling. The
existing Support Preview action can now collect one bounded shared-window,
identity-free internal/G1 comparison; either Unknown target remains incomplete
and hardware validation remains absent. The dormant
Compatibility Test Mode collector can consume this proof
only for a
same-AppID internal-GPU baseline and Docked-eGPU observation; it cannot finish,
review, promote, or publish the result.
Exact idle Docked-iGPU can now be previewed and promoted to Docked-eGPU through
the existing experimental approval and durable transition engine, with
Docked-iGPU as the verified rollback target. Automatic natural-game-exit
detection now exists as a bounded read-only one-shot watcher. A serialized
lifecycle owns its private watch, bounded polling, Action Required
acknowledgement, and unload cleanup. Its identity-free inspection always uses
an unconfirmed preview and rejects unexpected transition authority. The
lower-level facade composes the private ready generation with the existing
supervised preview and can consume the watch only after a separate explicit
approval-token issuance; neither layer executes the token. Production now
constructs the watcher, facade, lifecycle, and single-owner async driver in
watch-only mode for the exact Gamescope user. Decky exposes identity-free
status and Action Required acknowledgement, while inspection, approval, and
execution remain absent. The observer polls every five seconds while actively
watching; ineligible checks use a fifteen-second cadence and
skip full discovery when no exact game runs. Watch-only readiness is cleared
after one reporting interval, Gamescope restarts invalidate the exact watch,
and a bounded supervisor recovers transient observer failure. The task closes
on plugin unload. See
[Docked-iGPU workflow](DOCKED_IGPU.md).
The support-preview comparison adds no scheduler, transition approval, or
execution authority and never promotes a compatibility record.

- Complete the existing read-only experiment and prove unchanged Gamescope and
  game identity, iGPU rendering, and TV presentation.
- After natural game exit, select G1 for subsequent launches and verify the
  actual render GPU.
- Add optional same-AppID restart only after graceful close, save policy, loop
  prevention, relaunch, and fallback are independently proven.

Exit: each game/profile result is recorded in both eGPU-handoff and save/sleep
dimensions. Docked-iGPU remains experimental until real proof exists.

### R7 — Controller and audio handoff

**Status:** POLICY/PLANNING IMPLEMENTED; EXACT-PROFILE AUDIO CHILD INTEGRATED — versioned private
observations bind semantic generation, fresh sample identity, exact opaque
controller/audio targets, rollback targets, and categorical failures.
Controller/audio decisions preserve verified fallbacks, separate promotion from
suppression, order external disconnect/power-off last, and require verification
after every future step. Each subsystem fails closed independently; changed or
repeated shared evidence emits no steps at all. Partial safe work is distinct
from a fully ready plan. Real Ally/G1 controller capabilities remain
Unknown; audio handoff remains Experimental. A bounded
read-only sysfs inventory now discovers gamepad and sound-card candidates using
hashed private bindings; absent supervised mapping it reports controller
identity/default audio as unverified and authorizes no steps. See
[Controller and audio handoff foundation](PERIPHERAL_HANDOFF.md). The optional
troubleshooting overlay exposes only the associated categorical mapped/unmapped
diagnostics and remains non-authorizing. Mapping evidence is now typed,
reviewed, and bound to the complete opaque inventory fingerprint; a changed
inventory makes it stale and still cannot verify controller input or audio
output usability. Separately, the authoritative presentation mechanism now owns
one exact-profile PipeWire child. It records the current Portable default before
attach, resolves the single SteamOS loopback sink bound to the freshly verified
G1 HDMI-audio PCI function, selects and verifies its ephemeral node ID, and
restores the captured sink on rollback or Portable return. It exposes no separate
RPC and refuses missing rollback or ambiguous identity.

- Add profile capabilities and independently observable input/audio state.
- Preserve a usable fallback before suppressing built-in controls or changing
  audio output.
- Treat controller power-off as optional per-controller capability.

**Implemented (simulated execution foundation):** a peripheral plan runner now
requires fresh same-generation revalidation and a separate post-step verifier,
then performs bounded reverse-order rollback of already verified work. The
generic runner has no production wiring. Direct TV audio selection has one
player-confirmed hardware proof; automatic audio and Portable restoration remain
Hardware Validation Required. Controller mutation remains unavailable.

Exit: rollback and disconnect-loss tests pass before certification.

### R8 — Diagnostics, compatibility, and support expansion

**Status:** PARTIAL DELIVERY IMPLEMENTED — independent eGPU-handoff and save/sleep
dimensions, exact-profile evidence, and intentional human-reviewed promotion
gates are unit tested. Explicit opt-in verbose logging durations, expiry,
rotation, reboot/reset behavior, Decky status/countdown, confirmation, and
disable controls are implemented and simulated. Fixed-path atomic catalog
persistence and backend-only reviewed-evidence transactions are implemented but
remain unconstructed by Decky. No catalog collection UI, publication, or support
upload is enabled.

- Add an opt-in overlay and bounded verbose logging with a maximum TTL that
  cannot survive reboot.
- Maintain the game schema/developer guidance and add the hardware catalog schema.
- Expand previewable support bundles and compatibility test mode.
- Design Cloudflare Worker/private R2 submission separately with explicit
  upload consent, validation, rate limits, and retention.

Exit: privacy/security tests pass; no client credentials or silent upload.

### R9 — Broader hardware support

- **Implemented (catalog boundary):** runtime resolution accepts explicit
  host/eGPU profile definitions rather than central model-specific conditionals.
  Absent or ambiguous catalog matches remain Unknown. The catalog contains only
  the existing Ally X/G1 entries, and new definitions are not certification.
- Add profiles one combination at a time.
- Make non-eGPU display, controller, and audio features independently useful.
- Never promote unknown hardware through similarity alone.

### Later foundation backlog — performance and game experience

These items are intentionally deferred until the safe transition/recovery and
hardware-validation gates above are closed. They must extend the existing core;
they are not authorization for a separate optimizer or launcher.

- Expand the implemented typed health aggregation from placement, session,
  display, storage, and current exact-bridge PCIe link observation (including
  read-only current speed/lane evidence where the kernel exposes it) to
  independently verified controller, audio, link-quality, and recovery
  evidence. **Implemented (optional input):** one independently collected
  peripheral observation now contributes controller/audio health only when it
  proves usable built-in input/current output; incomplete evidence is Attention
  Required and known built-in loss is Degraded. The snapshot service now has
  fail-closed optional workflow/peripheral observer inputs, but no production
  observer is constructed yet.
  Current link up/down is neither throughput proof nor removal authority.
- **Implemented (pure contract):** the shared telemetry admission contract
  requires a typed bounded metric set, declared collection interval, measured
  cost, benchmark evidence, and an explicit low-cost budget before a future
  periodic collector could run. It delegates to the existing game-aware runtime
  budget and has no collector, scheduler, Auto TDP, or mutation authority.
  A real collector remains deferred until cost and game-impact measurement are
  recorded for a supported profile.
- **Implemented (Decky UI budget):** the always-rendered Quick Access panel
  clears optional troubleshooting state when hidden and uses a five-second
  essential-snapshot cadence outside Quick Access. Reopening the panel returns
  immediately to the existing adaptive cadence. Backend sleep protection does
  not depend on this UI polling path.
- **Implemented (policy + dormant relay):** the default verified held **Guide +
  Y** chord maps to the existing controller Safe Undock logical request, which
  remains routed through the ordinary `UNDOCK` transition vocabulary. Its
  bounded relay consumes each opaque verified event once and invokes only an
  injected logical-action sink; it has no listener, Decky RPC, canonical-facade
  construction, or transition authority. A platform adapter must still verify
  and debounce physical input before connecting that sink to the canonical
  request facade.
- **Implemented (pure contract):** mode-profile data keeps display preference
  (including HDR/VRR) separate from game render targets and player experience
  goals. It resolves only exact stable observed modes and has no display,
  GPU, power, audio, controller, or game-setting mechanism authority. Future
  consumers still require capability proof and TRY/VERIFY.
- **Implemented (pure contract):** Offline Readiness maps supplied categorical
  local install/download/entitlement/cloud-save and online-check evidence to
  ready-to-try, attention, online-check, or Unknown. It has no Steam collector,
  storage scan, account/game identity, UI, persistence, or launch authority.
  A future source must first pass the reviewed, local-only, identity-minimized,
  benchmarked, bounded-cost admission contract; stale or unadmitted evidence
  remains Unknown. It still has no collector or delivery integration.
- **Implemented (pure contract):** a reviewed Game Adapter must use typed
  allowlisted settings and exact opaque revisions. Its future mechanism is
  constrained to compare-before-write, backup, atomic staging, validation,
  commit confirmation, and verified rollback on failure. No game adapter,
  config writer, game-setting UI, or frontend authority exists yet.
- Research community-settings licensing/attribution and Steam integration
  boundaries before collecting, redistributing, or presenting recommendations.
- **Implemented (projection only):** transparent action history derives a
  short controller-friendly timeline from the existing bounded HDM event log.
  It stores nothing new and exports only action kind, outcome, code, and time;
  detail fields and correlation IDs stay private. The optional Decky
  troubleshooting view renders at most three entries through a read-only RPC.
  The existing snapshot refresh also records only verified topology candidates
  there; no detection result is a recovery or transition authority.

## Smallest safe next milestone

Independent Offline Readiness delivery work is tracked in the
[workstream handoff](OFFLINE_READINESS_HANDOFF.md). A candidate local Steam
overview projection, guarded request service, reason guidance, and source
research are implemented on its isolated branch;
live source validation, cost measurement, game context, and production wiring
remain open. This does not change the G1 journey or release gates below.

Unattended-safe R1 policy/replay, guarded process-release implementation,
canonical sleep policy/coordinator, compatibility policy, temporary logging
policy, and the optional overlay are complete. The next release-facing gates are
R0's supervised controller-visible warning/support-preview acceptance and R2's
separate supervised disposable-process validation.

Without physical supervision, continue implementation, simulator, schema, UI,
and recovery work but do not deploy or invoke process signals,
display/GPU/audio/controller mutation, original-sleep continuation, reboot,
suspend, or physical-removal actions. The first future live presentation
transition remains R3 and requires its documented supervised rollback tests.

### Interrupted docked sleep recovery checkpoint

- **Implemented (local-only contract):** existing canonical sleep restart
  recovery remains the single durable authority and never resumes original
  sleep. A redacted projection exposes only its acknowledged terminal restart
  result. A separate pure classifier records G1 absence, game/session absence,
  and verified handheld display/input/audio only when each fact is supplied as
  explicit categorical evidence. It treats stale checkpoints and incomplete
  evidence as non-restored; it does not infer a crash, wake cause, or success.
- **Hardware Validation Required:** production startup recovery must take one
  fresh post-wake sample through the owner-checked canonical service, then
  supply independently verified display, controller, and audio evidence before
  showing a restored-handheld outcome. A supervised scenario is required for
  sleep with the G1 removed while asleep. No remote suspend, removal, recovery,
  or deployment is authorized by this contract.
- **Product policy; future implementation:** after complete verified handheld
  recovery and verified original game/session absence, HDM may default to a
  safe relaunch only when update, cloud-sync, and repeat-failure concerns are
  absent. First successful use must present one non-intrusive player choice to
  keep automatic restart enabled or turn it off. This needs owner-checked wake
  wiring, a reviewed game relaunch adapter, all prerequisite evidence, loop
  prevention, fallback, and supervised hardware validation. It does not imply
  that a game crashed or that sleep caused a loss.
