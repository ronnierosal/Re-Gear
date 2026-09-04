# Architecture

## Design rule

Separate policy from mechanism from hardware.

```text
Decky UI / diagnostics CLI
            |
      application services
       /             \
read-only snapshot   transition engine (0.2+)
       \             /
        pure domain policy
          /        \
 SteamOS adapters  hardware profiles
```

## Domain

`backend/hdm/domain` owns immutable observations, user-facing mode inference,
support tiers, blockers, and future transition vocabulary. It performs no I/O and
does not know Decky, sysfs, systemd, subprocesses, or hardware commands.

Physical connection, display target, render GPU, Gamescope, workload, support,
and health are separate axes. `OperatingMode` is derived only from an exact
combination of verified axes.

The initial health aggregate is pure and categorical. It does not change
placement or authorize recovery: it assesses placement, Gamescope session,
active display, applicable eGPU storage, and (for external placements) a
read-only current PCIe link observation bound to the already verified G1 root
bridge. Link observation reports up, down, or unknown and, when the kernel
exposes parseable values, preserves the current GT/s and lane-width evidence.
Those values are observations only: HDM does not apply a universal performance
threshold or infer bandwidth, stability, safe removal, or certification.
Controller and audio are intentionally omitted until independently usable-state
observations are available. An authoritative workflow owner may additionally
project only recovery and terminal Action Required/Failed phases into the
separate health aggregate: recovery is `Recovering`; a terminal workflow is
`Attention Required`. Connecting and other requested-transition phases do not
change health, and none of these projections overwrites observed placement.
Unknown evidence is Attention Required rather than a healthy guess; degraded
evidence takes precedence over a pending recovery signal.

The runtime-budget policy is also pure and currently unconsumed by a production
scheduler. It classifies transition safety, direct player requests, and the
bounded placement watch as necessary work, while deferring background telemetry
and throttling optional explicit diagnostics during a running or unknown game.
It provides no clock, collector, loop, or mechanism authority; future callers
must re-observe before executing deferred work.

Mode profiles are likewise pure player intent. A `ModeProfile` keeps the
physical display preference (target, mode, HDR, and VRR) separate from a game's
render-resolution/FPS target and high-level experience goal. An exact stable
observed mode may look up its local profile; Unknown or Degraded observation
gets no fallback. The contract has no display, GPU, audio, controller, power,
or game-setting mechanism authority. Any future consumer must prove capability,
perform TRY/VERIFY, and preserve observed placement as independent truth.

The shared telemetry contract is also domain-only. A periodic collector must
declare a bounded metric set, interval, and measured collection cost, and may
be admitted only after that cost is benchmarked and stays within one tenth of
the configured interval. Admission delegates to the existing game-aware runtime
budget: optional background collection defers during running or unknown game
state, while player-requested diagnostics use the narrower diagnostic delay.
Auto TDP collection has a separate opt-in: the consumer must be AUTO_TDP,
explicitly enabled, benchmarked at no more than one percent of its interval,
and bound to known running-game state. Idle/unknown state defers it. This pure
admission rule starts no timer and authorizes no power write; other consumers
retain the existing game-time deferral. The one-percent threshold is a development
budget, not a measured device-impact claim.
Samples contain only typed numeric metrics; this contract has no collector,
scheduler, optimization, TDP, or mutation authority.

The HDM-overhead measurement assessment consumes at most one caller-supplied
snapshot/optional-observer timing sample under that same admission gate. It
reports identity-free bounded cost only when fresh and within the declared
budget, labels game impact Unknown, and cannot authorize any action. See
[HDM overhead measurement](PERFORMANCE_MEASUREMENT.md).

The link-instability assessment separately compares exactly two fresh
opaque-bound observed Up/Down link facts. It exposes only categorical state
change/stability evidence and has no quality, performance, recovery, removal,
or action authority. See [Link-instability evidence](LINK_INSTABILITY.md).

Controller Safe Undock presentation separately maps the existing pure Guide +
Y hold policy into non-authorizing delivery/input/revalidation states. It has no
listener, relay invocation, controller ownership, transition, or device-action
authority. See [Controller Safe Undock presentation](CONTROLLER_SHORTCUT_PRESENTATION.md).

The recovery explanation policy maps public link, interrupted-sleep, and
portable-recovery categories to deduplicated calm wording only. It owns neither
evidence collection nor notification delivery, and cannot make a recovery or
hardware claim. See [Recovery explanation policy](RECOVERY_EXPLANATION_POLICY.md).

Offline Readiness source review composes a local/read-only/non-networked,
identity-minimized declaration with the existing cost/freshness/game-aware
admission policy. It is a pure declaration review, not a Steam/launcher
collector or delivery mechanism. See
[Offline Readiness source review boundary](OFFLINE_EVIDENCE_SOURCE_REVIEW.md).

Future game configuration is bounded by a pure Game Adapter change contract.
Only a reviewed adapter can begin a typed, allowlisted setting change. The
future mechanism must compare the expected opaque revision, create an exact
backup, write a distinct staged revision atomically, validate that staged
revision, then confirm commit. A failure after backup requires verified rollback
before terminal success is possible. No adapter is yet constructed: the domain
contract accepts no paths, bytes, commands, PIDs, arbitrary setting names, or
frontend-provided game identity.

Transparent action history is a bounded projection of the existing HDM event
log, not a second audit or telemetry store. It retains only time, a categorical
action kind, categorical outcome, and stable event code; it deliberately drops
event details and correlation IDs. A future Decky history view can therefore
explain attempted, completed, recovered, blocked, failed, or attention-required
actions without exposing private hardware/process/session evidence.

Health aggregation can also accept one independent private peripheral
observation. Only exact, verified usable built-in input and current audio output
produce Ready components; incomplete mapping, default-output, or input evidence
is Attention Required, and a known loss of the built-in controller fallback is
Degraded. The snapshot service accepts optional authoritative workflow and
peripheral observers, samples each at most once per snapshot, and reports a
configured observer failure as Attention Required. No default production
observer is constructed yet, so sysfs inventory alone cannot improve health or
authorize handoff.

Runtime host/eGPU resolution is catalog-driven. Each explicit entry contains
only a profile ID, conservative capability metadata, and—in the eGPU case—a
strict stable-ID matcher. The registry never recognizes hardware by a fuzzy
name or profile similarity; absent or ambiguous catalog matches retain Unknown
capabilities. The initial catalog still contains only the certified Ally X and
GPD G1 definitions, but adding a future profile no longer requires branching
the central resolver.

The target model also keeps **placement** separate from **workflow phase**.
Portable, Docked-iGPU, Boosted Handheld, and Docked-eGPU are placement results;
Connecting, PreparingToDisconnect, SafeToDisconnect, ReturningToPortable,
SleepPendingDisconnect, ActionRequired, and Failure describe a request's
progress. The typed split, durable journal, deterministic replay, and guarded
runtime orchestrator are implemented; mechanism wiring remains experimental and
uninstalled. See [Authoritative roadmap](ROADMAP.md).

An exact attach candidate can also enter a small readiness watch. It binds the
private exact eGPU identity and accepts only a newer sample before classifying
external-display readiness, exact link health, and known game state. A partial
USB4 observation may become an attach candidate only when a later observation
resolves the complete exact profile. The separately persisted player opt-in can
then let a one-shot coordinator submit `ready_idle` through the same transition
engine used by the manual control; see [eGPU attach readiness](ATTACH_READINESS.md).

A separate pure deferred-dock-intent contract can retain one direct player Dock
request while the game is known running. Its opaque binding, expiry, explicit
cancellation, and invalidation rules can yield only a fresh idle eligibility
handoff; it creates no transition plan, permit, scheduler, persistence, or
delivery authority. Any future owner must revalidate and route through the
unified engine. See [Deferred dock intent](DEFERRED_DOCK_INTENT.md).

The combined handoff-eligibility contract similarly consumes only one fresh,
opaque-bound set of verified TV/render/audio/controller and Portable rollback
facts. It reports ineligible or rollback-required on missing, stale,
contradictory, inactive, or game-active evidence; eligibility is still only
evidence for a future unified engine. It has no device mechanism or delivery
authority. See [Combined handoff eligibility](COMBINED_HANDOFF_ELIGIBILITY.md).

A pure prepared-docked-idle contract compares two caller-supplied monotonic
samples after combined eligibility. It can report only not-yet-stable,
invalidated, or a five-second fresh idle evidence result; it owns no timer,
scheduler, state persistence, permit, or mechanism. See
[Prepared docked idle eligibility](PREPARED_DOCKED_IDLE.md).

Safe Undock readiness is also a pure, opaque-bound current-evidence contract.
It distinguishes insufficient, not-ready, invalidated, and ready-for-revalidation
states across client scan, topology, game, Portable fallback, and external
display facts. The positive state is never a physical-unplug claim and has no
action authority. See [Safe Undock readiness](SAFE_UNDOCK_READINESS.md).

The separate Safe Undock presentation contract consumes only that
revalidation-bound result. It can present insufficient, not-ready,
revalidate-required, or eligible-for-supervised-physical-validation categories.
An acknowledgement and an exact current binding/generation/sample match are
required for the last category; it remains non-authorizing and must be rerun
immediately before any separately approved physical test. See
[Safe Undock result presentation](SAFE_UNDOCK_PRESENTATION.md).

Unexpected-removal recovery assessment is a separate pure before/after evidence
contract. It requires a fresh opaque-bound loss observation and independently
verified internal display, input, and audio before reporting portable fallback
evidence. Stale, unknown, and contradictory facts require supervised diagnosis;
it has no recovery mechanism or game-outcome authority. See
[Unexpected removal recovery assessment](UNEXPECTED_REMOVAL_RECOVERY.md).

Interrupted-sleep relaunch eligibility is likewise a pure policy over one
fresh opaque-bound recovery observation. It requires verified handheld fallback,
an observed stopped session, clear update/cloud/launch/repeat-failure risks, and
an explicit preference before it can label a future flow eligible. It creates
no relaunch or preference-storage authority. See
[Interrupted sleep relaunch eligibility](SLEEP_RELAUNCH_ELIGIBILITY.md).

The first control-plane slice now defines typed placement and workflow states,
request/plan/deadline/failure/recovery values, conservative host/eGPU capability
composition, and a strict bounded transaction-journal schema. Decky now uses the
fixed-path store for guarded process release and one explicitly confirmed,
player-watched idle TV-switch test. Automatic display/GPU transition endpoints
remain disabled.

The guarded-process backlog has an internal approval service that issues
single-use tokens for backend-discovered eligible instances and requires a fresh
exact revalidation before returning internal signal targets. Graceful and force
approvals are distinct, and force requires prior graceful-attempt evidence.
Decky exposes the service only through redacted inspect/confirm/token/acknowledge
operations; the frontend never supplies a process target or signal.

A deterministic process-release runner exercises either a fake or narrow real
signal port. It re-scans after every action, revalidates the remaining approved
subset before every next action, enforces per-signal deadlines, and exports an
identity-free audit. With a journal port, every event is persisted and
`step_started` is durable before signaling. Restart recovery never repeats a
signal; it terminalizes the operation as Action Required. Clearing software
clients never sets hardware-removal authority. See
[Guarded eGPU process-release contract](PROCESS_RELEASE.md).

Each release operation owns a generated operation ID and records its request,
fresh observation, approval validation, plan, per-target typed signal steps,
re-scans, and terminal result in the shared transition journal. Tokens and
process/hardware identity never enter the exported journal.

The journal's fixed-path file adapter enforces atomic append-only
progress for one operation, no-follow/exclusive temporary creation, byte bounds,
file and directory synchronization, and matching-terminal-only cleanup. Decky
constructs it for process release under the separately hardened fixed root-owned
mode-0700 `/var/lib/handheld-dock-mode` state directory; the user-owned Gamescope
config root is not control-state authority. See
[Durable transition journal](TRANSITION_JOURNAL.md).

The guarded runtime orchestrator uses that journal contract for real mechanism
ports. It revalidates the exact profile/device/display binding and idle game
immediately before every attempt, persists `step_started` before the mechanism
call, polls fresh observations only inside the step deadline, commits only a
verified destination, and recovers to the source after apply, verification, or
commit-persistence failure. Startup recovery distinguishes pre-mutation
interruption from a persisted attempted step and never resumes the original
request automatically. The mechanism port is still unwired.

Runtime observation generations hash the complete semantic snapshot but exclude
the collection timestamp. Two unchanged polls can therefore satisfy a
preview/approval boundary, while any game, GPU, display, Gamescope, readiness,
sleep-guard, client, or blocker change invalidates the generation.
Each observation also carries a separate per-scan sample ID that includes the
collection timestamp. Operations such as process signaling use that sample ID
to prove a new scan occurred even when its semantic facts are unchanged. A
semantic generation is never treated as proof of a fresh scan.

The dormant presentation mechanism now composes fresh binding/profile
revalidation, exact Gamescope-user revalidation, reversible integration status,
daemon-reload, fixed-unit verification, atomic target configuration, and a
non-blocking fixed-target restart. It rechecks the user before and after staging
the config. A synchronous restart failure restores the currently observed
source config immediately; a rollback-write failure is reported separately.
The orchestrator skips a redundant recovery restart when a fresh observation
already proves the source placement. Neither component is constructed by Decky.

A separate preparation service owns reversible integration activation.
It issues a maximum-two-minute, single-use approval only from a verified
Portable, idle, healthy Gamescope observation and binds it to the semantic
generation, exact Gamescope user, and SHA-256 of the shim plus expected drop-in.
Execution re-observes all evidence, installs the fixed file, rechecks the
fingerprint/user, reloads the fixed user manager, and verifies the fixed unit.
It never restarts Gamescope. A reload/verification failure removes a newly
installed drop-in and reloads again; incomplete rollback is Action Required.
The application service depends only on narrow ports. Decky exposes only its
read-only preview, explicit approval, and token-consuming preparation methods;
none can request a Gamescope restart or presentation transition.

The packaged Gamescope shim is the final presentation mechanism boundary. It
reads one strict, bounded, boot-scoped config from a fixed state root, removes
inherited eGPU render selection, and applies an external connector/GPU only
when the connector and vendor/device remain unique and a fresh full
DRM/PCI/USB4 G1 match reproduces the same boot-scoped SHA-256 binding. The
binding does not persist the boot ID or stable eGPU identity. Stale, malformed,
missing, changed, or ambiguous evidence selects a unique internal panel when
available and otherwise preserves the existing output arguments while clearing
the eGPU selector. The companion config store writes atomically from an exact
transition binding. The shim and config store cannot install integration or
restart Gamescope; those authorities remain in the guarded transition service.

The SteamOS signal adapter is a narrow Linux leaf mechanism: it maps only typed
graceful/force actions to `SIGTERM`/`SIGKILL`, opens a pidfd, verifies the
approved process start time, uses no shell or subprocess, has no numeric-PID
fallback, and returns categorical results. `main.py` constructs it only behind
the guarded service, root-owned journal, exact backend approvals, and mandatory
rescans. Missing pidfd capability blocks the preview before consent.

The Decky-wired `GuardedProcessReleaseService` composes redacted inspection,
explicit token issuance, fresh-sample execution, single-operation locking,
durable journaling, and no-repeat recovery. Graceful-attempt evidence remains a
private application value behind a bounded, expiring opaque receipt, so the
Decky facade cannot expose PID-plus-start-time-derived identities. Issuing a
force approval consumes that receipt; force is always a second confirmation.

The canonical sleep reducer is pure policy over exact eGPU presence/identity,
profile capabilities, game/save state, disconnect evidence, placement, and a
bounded original-request deadline. A delivery-independent coordinator now
normalizes Steam-menu/physical-button sources, binds the request to an exact
generation and eGPU/profile capability identity, persists every stage boundary,
requires fresh verification samples, and performs no directive itself. It
cannot show Safe to disconnect from
software-client readiness alone and cannot continue the original sleep request
before verified Portable recovery. Process release now participates as a child
of the same authoritative journal in simulation through strict substep events
and a backend-injected parent ID. Exact game close has the same child-step
boundary: one exact AppID/scope identity, explicit bounded consent, fresh
identity revalidation, durable pre-mechanism state, bounded Idle verification,
and fail-closed terminalization. The read-only scope adapter and application
service are implemented and simulated, but no production close mechanism or
Decky sleep delivery is wired. See
[Canonical sleep workflow](SLEEP_WORKFLOW.md).

Verified save is another strict child of that same parent. A backend-owned
recipe must match the exact game plus bound host/eGPU profiles, and a separate
proof observation must change to Verified after the attempt. The single-use
authority, durable pre-mechanism substep, bounded proof loop, close gate, and
privacy/capacity tests are implemented and simulated. No production recipe,
proof adapter, save mechanism, or Decky route exists. See
[Verified game-save child](GAME_SAVE.md).

The dormant canonical-sleep delivery facade keeps request identity and snapshot
generation backend-owned. It accepts only typed Steam-menu/physical-button
intent, re-observes through the coordinator, and binds consent/cancel to the
opaque active operation. Its payload mapper exposes only categorical flow
state, directives, durability, and the operation ID needed for exact consent or
acknowledgement. It is not constructed by Decky and has no directive mechanism.

Asynchronous cable-loss policy can request Portable recovery but can never
continue sleep. Even when the observed workflow is SleepPendingDisconnect, only
the canonical reducer may continue the exact unexpired request after separate
removal and Portable verification. Unknown pre-event placement fails closed;
after a verified loss invalidates the composite placement, every individual
recovery-critical identity and state must still be known before an attempt.

A pure topology-event detector can now bind two distinct, complete snapshots
into an attach, eGPU-removal, or external-display-loss candidate. It requires
an exact host profile on both snapshots and exact resource continuity; an
unproven disappearance is explicitly Unverified rather than treated as a
removal. The detector is not a watcher, scheduler, RPC, or recovery trigger.
The existing Decky snapshot refresh records a detected candidate in the bounded
identity-free action history only; it performs no recovery, mutation, or
transition request. Future action-bearing event sources must still route
candidates through the shared policy and transition authority.

A dormant application-level unexpected-undock coordinator now binds one raw
eGPU/display-loss event to an exact semantic generation and independent sample,
re-observes exact loss and internal recovery readiness, makes one injected
Portable recovery attempt, verifies a fresh Portable result, and returns a
bounded identity-free trace. Primary failure invokes one separately bounded
Portable-preservation fallback; unknown/stale evidence or failed verification
enters Action Required. A sleep-pending event also requires the exact canonical
operation identity, but the coordinator has no sleep port and can only request a
later canonical re-check. It is not constructed by Decky and has no production
mechanism adapter. See
[Unexpected-undock recovery coordinator](UNEXPECTED_UNDOCK_RECOVERY.md).

A separate production observer now supervises SteamOS' own recovery without
activating that dormant display mechanism. `NativePortableRecoverySupervisor`
keeps an in-memory exact idle TV-Docked baseline, recognizes only a correlated
interval in which Gamescope is stopped, the bound external display is verified
disconnected, and the bound internal GPU/panel remain available, then waits at
most 120 seconds for a fresh verified Portable observation. Timeout or
contradictory evidence becomes Action Required. A verified result may restore
the root-captured Portable audio sink, but the observer never restarts
Gamescope, advances sleep, or describes physical removal as safe.

While that observer is waiting on a correlated unexpected loss, production
sampling tightens from one second to 250 ms. Exact attach settling likewise uses
250 ms samples. Automatic docking requires four distinct consecutive samples
with the same exact G1 identity and verified EDID, link, Gamescope, and idle-game
state before it requests a restart; a repeated sample or any gate regression
resets that stability quorum. This adds a short bounded settle after readiness
while avoiding a restart on the first transient ready sample. Sampling cannot
shorten kernel enumeration or the Gamescope restart itself.

The Decky delivery adapter maintains a bounded, boot-local monotonic timing
timeline for troubleshooting this path. It emits only on categorical G1
presence/readiness changes and transition or shutdown attempts/results, reusing
the existing bounded support event log and Decky service journal. Event details
contain elapsed or operation duration, categorical target/result state, and
booleans only. The optional verbose snapshot event retains the already-public
collector timing rows rather than only their count. This instrumentation adds
no discovery loop, does not drive readiness, and cannot infer physical cable
time or completed physical power-off. Failure to retain or write a diagnostic
event is isolated from the transition engine and cannot block or authorize a
hardware action.

The manual planner supports only the bounded Portable↔Docked-eGPU path and
verified no-ops. A mutating plan requires exact runtime host/eGPU profile
resolution, an ephemeral binding to every participating GPU/display, idle game
state, target readiness, and a verified source-placement rollback path.
Verified capability is accepted normally. One explicitly confirmed,
two-minute, single-use backend permit can authorize an exact Experimental plan
without promoting that capability. Docked-iGPU, Boosted Handheld, unknown, and
degraded sources are not silently coerced into this path. See
[Guarded experimental transitions](EXPERIMENTAL_TRANSITIONS.md).

An unwired supervised facade now joins the planner, experimental approval
store, durable orchestrator, and journal lifecycle. Read-only preview can model
one exact Portable↔Docked-eGPU request without issuing consent. Explicit
confirmation issues a maximum-two-minute single-use permit; execution consumes
it, requires the same semantic generation and ready integration, reconstructs
the exact plan, and delegates to the orchestrator. An incomplete journal blocks
new approval until recovery; a terminal journal blocks until its exact random
operation ID is acknowledged. The manual Decky control and the root-owned
automatic attach coordinator both construct this facade. Manual use consumes a
short-lived on-screen approval; automatic use requires persistent player opt-in
and an exact unchanged generation. Both enter the same journaled plan and remain
Hardware Validation Required.

The controller-focusable Safe Disconnect fallback exposes the already-modeled
Docked-eGPU-to-Portable target through that same supervised facade. A separate
`SafeDisconnectShutdownService` accepts shutdown only after a fresh exact-host,
known-idle, verified-Portable observation. Confirmation creates one backend-only
approval valid for at most 30 seconds; execution consumes it, requires the same
semantic generation, and invokes only `/usr/bin/systemctl --no-block poweroff`
through a root-only fixed command adapter. It does not unbind, reset USB4, or
authorize removal while powered. A terminal presentation journal must still be
acknowledged before the UI enables shutdown. Presentation journals persist the
categorical requested target. Acknowledging an intentional Portable return
latches automatic docking off for that exact attachment until the G1 is removed;
acknowledging a TV attempt may still re-arm one retry. A successful systemctl
return proves only that the power-off request was accepted, never that firmware
completed physical power-off.

That same durable path now treats exact idle Docked-iGPU as a supported source
for a Docked-eGPU target. Boot config represents Docked-iGPU explicitly as TV
output plus the exact internal render GPU, and recovery can restore it. The path
remains experimental, approval-gated, and unwired; the durable path itself does
not watch for game exit or initiate promotion automatically.

A separate read-only watcher binds an exact running Steam game in Docked-iGPU
and its PID-reuse-resistant Gamescope session generation, then emits only a
one-shot `promotion_ready` state after two exact Idle samples bracket a fresh,
unchanged-profile Docked-iGPU snapshot. The production backend uses a
fifteen-second ineligible cadence with an idle fast path that skips full
hardware discovery, then a five-second cadence while watching. It is bounded,
cancels on game, Gamescope, placement, or profile change, exposes no private
identity in its payload, and is constructed without a transition/approval port. See
[Docked-iGPU workflow](DOCKED_IGPU.md).

The opaque facade can compose a ready watch with the existing supervised preview
without accepting private identity or generation from delivery. That
preview-capable composition binds preview to the stored generation, requires
Docked-iGPU again, and consumes the watch only after an explicit approval token
is issued. It remains dormant. Production constructs the same facade in
watch-only mode: inspection is unavailable, no approval token can be requested,
and no transition service or mechanism is imported into `main.py`.

A serialized lifecycle now owns exactly one facade watch and supplies bounded
arm/poll timing, Action Required acknowledgement, and idempotent unload
cancellation. Preview-capable composition retains promotion readiness;
watch-only production clears the ready watch after one reporting interval so
stale evidence cannot survive a new game or topology. Its read-only inspection always calls the
facade with `user_confirmed=False`, maps only categorical placement/readiness
and sanitized blockers, and treats any unexpected approval token as Action
Required. A delivery-side async driver provides single-run ownership, bounded
polling, explicit wake-up from terminal states, terminal-state quiescence, and
close-on-cancellation. The backend owns one such task for the watch-only
lifecycle behind a bounded retrying supervisor and cancels it on unload. Decky
exposes only categorical status plus
acknowledgement of Action Required; acknowledgement cancels the private watch
and resumes observation but cannot inspect, approve, or execute a transition.

Controller and audio handoff have pure decision policies plus a versioned,
delivery-independent composite planning foundation. External
controller promotion is independent from built-in suppression; suppression is
never planned without verified external input and a verified built-in recovery
path. Controller loss/undock restores and promotes built-in input first.
When promotion is verified but suppression is not, HDM keeps the built-in
controller active instead of failing the entire dock handoff.
External power-off may fall back to an independently verified disconnect
capability but is never assumed. Audio selection requires a verified usable
rollback output; otherwise the current usable output is preserved or Action
Required is reported. The composite plan binds exact private controller/output
targets, one semantic generation, and one independent sample ID. Controller and
audio completeness/identity gates are independent, but stale shared evidence or
a repeated sample blocks all work. Every typed child step requires a fresh
verification sample. Categorical public traces omit all bindings and observation
identities. Partial safe work remains distinguishable from a fully ready plan.
No production observer, mechanism, or RPC is wired.
See [Controller and audio handoff foundation](PERIPHERAL_HANDOFF.md).

The initial SteamOS peripheral adapter is read-only sysfs inventory only. It
recognizes gamepad-capable input nodes and sound-card nodes, hashes their paths
into private opaque bindings, and never opens an input node or invokes an audio
session command. Unmapped controller identity and unobserved default audio both
remain non-exact and non-actionable. That generic adapter is not used to
authorize mutation. The separate exact Ally X/GPD G1 presentation mechanism
owns one narrow PipeWire child: it records the current Portable default in
root-only state, freshly derives the G1 audio PCI function from the certified
topology, resolves the single matching SteamOS loopback sink, selects its
ephemeral numeric ID, and verifies the new default. It restores the recorded
sink on presentation rollback or Portable return and exposes no independent
RPC. The capability remains Experimental pending watched automatic and restore
proof; controller mechanisms remain absent.

Any future profile-specific mapping is typed reviewed supervised evidence bound
to the complete opaque inventory fingerprint. A changed inventory invalidates
it for both subsystems. It remains identity evidence only and cannot verify a
working controller/default output or authorize a handoff.

Its semantic generation includes the complete private hashed inventory and its
collection sample changes every scan. This lets a future transaction reject
topology changes without treating timestamp-only refresh as a semantic change.

Exact Steam scope identity can now be enriched by a dormant read-only cgroup
and procfs adapter. It binds PID plus start time, captures private parent and
executable-basename evidence, and classifies native versus Proton only from
allowlisted environment-key presence. Incomplete or changing evidence discards
the entire process graph and returns a categorical Unknown result. No process
identity is public or journaled, and no Decky route or game mechanism uses this
adapter. See [Active game runtime evidence](GAME_RUNTIME.md).

One dormant read-only application service can bracket an exact eGPU-client
snapshot between two unchanged game-runtime samples and report categorical G1
render-node ownership. PID/start time, exact profile/eGPU identity, complete
scan, and game classification must all agree. This evidence explicitly does not
prove active rendering or authorize a placement transition.

A stronger read-only path samples bounded DRM `fdinfo` engine counters
twice for an exact backend-resolved GPU binding. It requires stable game
processes, exact render node and PCI identity, unchanged DRM client/engine sets,
and monotonic counters. Only an observed counter increase proves activity on
that GPU for the sample window. The private G1 binding resolver independently
re-runs exact DRM/PCI/USB4 matching and accepts one character-device render node
under the exact GPU PCI device. The internal resolver independently rechecks the
Ally DMI profile, one matching AMD boot GPU, and one character-device render
node. Support Preview constructs both as a one-shot read-only diagnostic,
samples them under one shared runtime/snapshot window, and records only
categorical identity-free results. Either Unknown target makes the comparison
incomplete. It creates no new RPC, performs
no background polling, and cannot authorize a transition or certify a game by
itself.

Compatibility Test Mode has one dormant application consumer for this evidence.
Its read-only baseline collector requires an exact stable Steam session before
and after active internal-GPU evidence, retains only the evidence generation,
and rejects an idle, unknown, raced, or Docked-eGPU placement. The external
collector then requires that same-AppID baseline plus active G1 counters in a
Docked-eGPU snapshot and its own exact-session bracket, then records only a
hashed generation and categorical result. Its application-only lifecycle
serializes one ephemeral session and
enables or disables temporary diagnostics exactly as the session policy
requires, and invokes the injected baseline collector only with a backend-owned
user context. A missing/failed observer or post-sample session race becomes
Action Required; trusted
hardware-test authorization is an injected backend port, not caller data.
Existing explicit finish/review and simulation-promotion
prohibitions remain authoritative; no catalog update is automatic.
Its future delivery contract is deliberately identity-free: stage, categorical
code, selected dimensions, outcomes, and action/review flags only. No session,
game, profile, evidence, time, or authorization identity crosses it.

## Application layer

Application services coordinate ports and domain policy. The snapshot,
support-report, approval, replay, and guarded transition services share the
same authoritative observations and journal vocabulary. Manual and automatic
delivery still need one request facade before production wiring.

The root backend also owns one in-memory diagnostic-logging controller over the
same bounded support event log. Decky can request only an allowlisted duration
after a visible confirmation, read an identity-free countdown, or disable it.
Verbose snapshot events are reduced and sanitized before retention. Consent,
events, and the boot-session comparison are never persisted; reboot or plugin
restart therefore fails back to normal logging.

## Ports and adapters

Ports are narrow protocols defined by the application. The first SteamOS
adapters observe:

- DRM cards, connectors, modes, and EDID through sysfs
- PCI and USB4 topology
- Gamescope PID, arguments, active output, and render device
- Steam user-systemd game scopes
- exact certified-eGPU DRM/audio resource holders and mounted/swap storage
- bounded current PCIe link-health evidence for an exact verified eGPU bridge

The current-link collector is read-only and records categorical up/down/
unknown state plus parseable current speed and lane width after exact profile
resolution. It does not inspect kernel logs,
reset devices, or imply performance quality. The implemented snapshot adapter
cross-correlates the other sources and emits blockers when any required source is
missing, conflicting, or ambiguous. Process classification is pure domain
policy; procfs and sysfs enumeration remain read-only SteamOS adapters.

Hardware profiles classify observations and quirks. They do not select devices
by enumeration order. The runtime registry selects a known profile only from
the exact current snapshot; ambiguity receives unknown capabilities.

Host recognition uses reviewed, normalized full DMI tuples rather than vendor,
product, or board-name substring similarity. G1 recognition requires the full
DRM/PCI/USB4 topology, expected bound drivers, one privacy-preserving USB4
identity, and an exact backend-only binding between the external GPU and its
disconnect scan. A profile-like name or matching GPU PCI ID cannot resolve a
runtime profile.

Profiles will expose conservative capabilities for eGPU transport, presentation,
audio, controller handoff, sleep behavior, and removal. A capability must be
supported by mechanism and evidence; unknown hardware receives no mutation
capability. Host and eGPU capabilities compose instead of forking the core.
The read-only diagnostic contract serializes these axes independently with a
typed value, confidence, and categorical evidence basis. It does not expose the
stable eGPU identity used for backend revalidation.

## Privilege boundary

Read-only discovery uses the least privilege that can verify each source. The
CLI runs unprivileged and reports protected Gamescope environment state as
unknown. The Decky adapter runs as root so it can read that environment, then
reads the Gamescope owner's user cgroups directly. A strict user-systemd command
allowlist remains only as a fallback. The dormant mutation runner independently
resolves the single verified Gamescope process owner's passwd record and live
user bus without username, UID, environment, or home-directory fallbacks. It
accepts only unit verification, daemon-reload, and a non-blocking restart of the
fixed `gamescope-session.target`; it uses absolute executables, a sanitized
environment, no shell, bounded output, and categorical errors. Decky constructs
it only for preparation, where the service can call daemon-reload and fixed-unit
verification but never the restart operation. Public RPCs are limited to
`get_snapshot`, the preview/token-approved support-bundle flow, the
preview/approval/token-consuming supervised preparation flow, and guarded
process inspect/approve/execute/acknowledge. No RPC accepts a command, system
path, device identity, PID, signal, or process target.

The first 0.2 safety mechanism is a backend-owned, parent-death-guarded
`systemd-inhibit` process. Exact G1 presence and partial candidate enumeration
acquire its login1 lease; only verified absence or plugin unload terminates it,
and backend process death terminates the holder chain. Warning suppression is
frontend-only and cannot affect the lease.

Future transition mutation is exposed through a small, typed API with no arbitrary command
or path inputs. The Decky entrypoint remains an adapter; it is not the domain or
transition engine.

Presentation activation will use a separately reviewed reversible user-service
integration. HDM will not patch SteamOS's `/usr/lib/steamos/gamescope-session`
script. The fixed integration store now installs or removes only HDM's exact
`90-handheld-dock-mode.conf`, refuses symlinks, unsafe ownership, modified
managed content, unknown environment files, and any competing `PATH` directive,
and retains the state directory on deactivation. File activation remains
separate from daemon-reload and restart. Existing eGPUBridge `PATH` ownership is
therefore reported as a conflict instead of being overwritten or chained. No
plugin path constructs the store yet.

Snapshot discovery records privacy-safe stage durations and the Decky frontend
uses an adaptive non-overlapping refresh loop: one second while discovering or
ready, 750 ms while identity/display evidence is settling, and three seconds in
a verified TV Docked state. The current certified live snapshot path measured 25–31 ms over
five end-to-end Decky RPC calls, so parallelizing sysfs/procfs sources is not
currently justified; snapshot consistency remains more important than shaving
that bounded observation time.

The Decky payload strips hardware stable IDs, connector/vendor identity,
Gamescope PID/output selectors, eGPU identity, and process PID/instance IDs.
Exact values remain in backend observations for revalidation and never cross
the frontend RPC boundary.

Support bundle construction, redaction, event rotation, size enforcement, and
one-time preview approval are application policy. The only file mechanism is a
fixed-boundary Decky delivery helper that creates the exact reviewed bytes in
the Decky user's Downloads directory. See [Privacy-safe support bundle](SUPPORT_BUNDLE.md).

## Transition design gate

Milestone 0.2 must add a durable transaction journal containing:

- request and trigger
- pre-transition snapshot
- desired state
- validated plan and blockers
- completed step and deadlines
- verification evidence
- rollback outcome

The engine re-observes safety-critical state immediately before applying a plan
to limit time-of-check/time-of-use races.

The sleep guard is not a display transition and does not use the transaction
journal. Its complete acquire/hold/release lifecycle and failure behavior are
defined in [ADR: G1 sleep guard](ADR_SLEEP_GUARD.md). The proposed frontend
layer that stops Steam before its preparation sequence is defined separately in
[ADR: Steam sleep preflight](ADR_STEAM_SLEEP_PREFLIGHT.md); it complements and
never replaces the backend login1 lease.

## Verification strategy

- Pure unit tests for mode and policy matrices
- Captured fixtures for discovery parsers
- Contract tests for Decky/backend payloads
- Failure injection for unavailable commands, stale identity, restart timeouts,
  partial configuration, and rollback failure
- Redacted supervised hardware captures for profile certification
