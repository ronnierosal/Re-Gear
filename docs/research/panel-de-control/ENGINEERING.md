# Engineering opportunities from Panel de Control

Panel de Control has substantial implementation depth behind its feature list:
capability-specific controls, per-game stores, background workers, configuration
journals, and tests for races and failed restoration. The useful transfer is a
set of narrow behaviors and verification cases. Re-Gear should retain its own
separation of pure policy, application orchestration, provider adapters, and
independently verified hardware state.

All observations below refer to the immutable revisions in [the source
inventory](SOURCES.md). “Tests inspected” means the relevant assertions were read;
none of the upstream tests were executed. Counterexamples are static reasoning
about the inspected code, not measured device regressions or full security findings.

## 1. Battery Care: separate capability, preference, and observed charge limit

**Observed implementation.** The upstream battery backend distinguishes unsupported
control, an adjustable threshold, and fixed conservation mode. Disable is
provider-specific: a standard threshold uses 100, while its Steam Deck backend
uses zero. Its RPC reports saved enabled/percentage preferences separately from
observed percentage and apply/reconciliation information. A fake-backend test
explicitly retains a requested 70% after a failed write while reporting actual
100%. This is considerably better than treating slider position as hardware truth.

**Re-Gear adaptation.** Add a typed battery observation and a separate charge-control
port. Keep unsupported, unreadable, fixed-mode, adjustable, pending, and recovery
states explicit. Reuse the transaction concepts around power controls, but do
not give battery mutations authority through the TDP writer. A battery-power
sensor already existing in Re-Gear does not establish charge-control support.

The generic upstream search takes the first matching threshold path. Re-Gear
must bind to the intended internal battery, reject ambiguous supplies, and avoid
persisting a sysfs enumeration index as identity. Fixed conservation should
report its observed on/off state without inventing a percentage.

**First slice.** Read-only Battery module, no charge writes. Follow with explicit
charge-limit preview/apply and a capability-specific restoration policy. Decide
whether disabling Re-Gear relinquishes control, restores the prior threshold,
or deliberately leaves a persistent player setting; “100%” is not universally
the prior state.

**Acceptance.** Multiple batteries, external supplies, absent/read-only nodes,
unknown capacity, fake zero cycle counters, both disable sentinels, rejected
writes, mismatching readback, firmware reset, owner conflict, and reboot/resume.
Verify behavior on each admitted provider; do not inherit upstream's support table.

Evidence: [charge backends](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/battery/charge_limit.py#L19-L181),
[battery RPC state](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L4926-L4952),
[write/lifecycle entry](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L6877-L6916),
[tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_battery_rpc.py#L346-L408).
Re-Gear seam: [existing power sensor adapter](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/adapters/steamos/tdp_sensors.py),
[preference intent contract](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/auto_tdp_preferences.py).

## 2. Latest intent must survive late hardware writes

**Observed implementation.** Charge reconciliation checks generation before an
operation, before retry, and before publishing the result. New requests invalidate
old reconciliation tasks; shutdown does the same. This addresses firmware changes
that happen after an apparently successful initial apply.

**Re-Gear adaptation.** Adopt request generations and final-state reconciliation,
not unlimited reassertion. Cancellation cannot undo an operation already inside
a driver. The owner must drain or account for an in-flight write, restore/verify
the latest intent, and suppress stale result publication. A competing controller
should cause relinquishment or a conflict state rather than a continuous fight.

**Acceptance.** Block an apply after it starts, request disable, then release the
old write. Verify the final device state, not only the returned status. Repeat
for plugin unload, backend replacement, a second request, and failed restoration.
Bound retries and retained diagnostics.

Evidence: [operation generation checks](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L4518-L4537),
[cancellation](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L4615-L4636),
[reconciliation](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L4876-L4924),
[shutdown invalidation](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L8718-L8726).
Re-Gear already has [worker stop/drain behavior](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/delivery/auto_tdp_worker.py#L58-L77);
a new module should fit that ownership model.

## 3. Profiles: preserve overrides, separate runtime learning, and use real identity

**Observed implementation.** Upstream keeps a game's stored override when the player
switches back to global settings. Editing reactivates the game override. This
supports an understandable distinction between inheritance and deletion.

Two details should not transfer. First, Auto-TDP writes its evolving PL1 into the
profile store before applying the change. An inheriting game selects the global
store, so adaptive tuning can change the saved global setpoint used by other games.
Second, non-Steam saved keys use a normalized display name; identically named
shortcuts can therefore share a key. Its launch editor separately targets the
live AppID, which is a better mutation boundary.

**Re-Gear adaptation.** Resolve explicit preferences by module, stable game identity,
and verified placement. A proposed precedence is explicit game+placement override,
then placement default, then global module default; confirm this product choice
before implementation. Unknown/degraded placement must not silently select a
hardware-mutating fallback. Keep the source of each effective value visible.

Keep adaptive session state separate from saved player intent. Offer “Save this
setting” or a reviewed suggestion as an explicit action. For non-Steam games,
define collision, rename, reimport, and relink behavior before accepting a stable
identifier; title text is presentation, not sufficient identity.

**Acceptance.** Global→own→global preserves the override; reset is distinct from
inheritance; global edits do not delete overrides; automatic tuning never modifies
saved defaults; game/output changes during a pending operation cannot retarget it;
duplicate shortcut names cannot share writes.

Evidence: [scoped store](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/scoped_store.py#L56-L139),
[inheritance tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_tdp_profiles.py#L183-L221),
[adaptive persistence](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L3303-L3311),
[adaptive scope selection](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L3542-L3550),
[non-Steam identity](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/tdp/gameIdentity.ts#L40-L62).
Re-Gear: [mode intent/resolution](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/mode_profiles.py#L79-L143),
[Auto TDP preferences](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/auto_tdp_preferences.py).

## 4. Auto TDP: preserve FPS feedback; test menu responsiveness separately

**Observed implementation.** Upstream's decision function uses GPU utilization:
recent saturation increases power, sustained slack reduces it, otherwise it holds.
The decision API has no sample timestamps. Missing values are filtered out. An
entirely missing window returns the current setpoint clamped to the supplied
bounds and preserves the slack counter; a raised UI floor can therefore change
the result even without GPU samples. The integration clears its window after a
setpoint change, which usefully avoids comparing samples from different settings.

A temporary floor is raised while QAM/plugin UI is active. Its default 13 W value
is a heuristic, not a cross-device capability or a measured Re-Gear requirement.
Upstream tests establish threshold behavior, not preservation of CPU-limited
game performance.

**Re-Gear adaptation.** Retain FPS-target policy, freshness/settling admission,
verified internal rendering, writer ownership, power/thermal readiness, and
ineffective-increase stopping. Low GPU utilization can reflect a CPU bottleneck
or frame cap; it does not by itself prove power can be reduced. eGPU utilization
must not automatically drive the handheld APU's power budget.

Investigate a bounded pause-down policy or temporary floor while the menu is
open. Route it through the existing owner and device bounds; never create a
second writer. Clear it after close, timeout, stale UI evidence, or restart.
Measure whether a change is needed before adding it.

**Acceptance.** CPU-heavy and GPU-heavy games, frame caps, menu open/close, missed
UI-close notification, power maxima below the proposed floor, stale samples,
eGPU rendering, controller navigation latency, frame times, and battery draw.
Report configured watts separately from measured power.

Evidence: [upstream control law/floor](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/auto_tdp.py#L33-L119),
[loop integration](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L3268-L3311),
[tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_auto_tdp.py#L34-L145).
Re-Gear's stronger existing seam: [policy admission and response handling](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/auto_tdp.py#L105-L188).

## 5. Telemetry and resume: share evidence without perpetual background tuning

**Observed implementation.** The local-learning sampler waits five seconds between
collection attempts and flushes every twelve accepted samples; the store bounds recent
entries and game count. Missing metrics remain missing. Learning defaults enabled
in the inspected initialization. Turning learning off stops that sampler, not
the separate power/GPU reads used by Auto-TDP. Thus “local” and “off” need precise
scope in the UI.

Resume detection pairs a wakeup-counter change with BOOTTIME−MONOTONIC suspension
evidence, including a bounded window for delayed counter changes. This avoids
equating every awake wake event with resume. However, AC discovery returns false
when supply information is absent, and its scheduling uses wall time.

**Re-Gear adaptation.** Use one bounded read-only collector with independent consumer
subscriptions, explicit local-history consent, monotonic freshness, and measured
cost admission. Keep game, placement, device/provider revision, configured limit,
and actual power evidence distinguishable. A learning toggle should name whether
it stops history, sensing, or control.

Feed resume/AC changes into invalidation and fresh observation. Only an explicitly
active owner may subsequently re-enter the normal apply/verify path. Unknown AC
is not “on battery.” Use monotonic deadlines and cap settle retries; never resume
a dormant Auto-TDP session solely because a saved preference exists.

**Acceptance.** Disabled consumer I/O, duplicate collection, blocked sampler,
mid-sample context switch, bounded storage, damaged history, awake USB wake events,
clock jumps, stale suspend evidence, missing AC, ownership change, and late firmware
reset. Measure collection cost on hardware before enabling game-time sampling.

Evidence: [sampler](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/telemetry/sampler.py#L17-L68),
[bounded store](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/telemetry/store.py#L5-L19),
[missing-metric tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_telemetry_store.py#L85-L116),
[default setting](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L245-L248),
[learning lifecycle](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L3054-L3075),
[resume detector](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/lifecycle.py#L165-L264),
[delayed/stale evidence tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_tdp_lifecycle.py#L156-L198).
Re-Gear: [telemetry admission](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/telemetry.py),
[runtime budget](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/runtime_budget.py).

## 6. MangoHud: implement ownership before a full editor

**Observed implementation.** Upstream tracks installing, managed, updating, and
restoring phases with content/backup hashes. It refuses external configuration
by default and detects edits after takeover. Restoration verifies ownership;
writes use atomic replacement and fsync. Its coordinator coalesces replaceable
refresh work while preserving ordered user mutations, rejects stale generations,
and restores after active work on close.

The close path waits for a restore future without an explicit timeout. This is a
useful ordering pattern, not proof of bounded shutdown. Each blocking operation
and the final drain require an explicit deadline. Several atomic file replacements
also do not become one filesystem transaction merely because each is atomic.

**Re-Gear adaptation.** Begin with one simple HUD preset and a preview. Define
saved, waiting for a compatible instance, applied/verified, conflict, unavailable,
and restore-required states. Resolve the actual MangoHud version, environment/config
precedence, and running instance. The official documentation describes global and
per-application configuration plus environment overrides; a file write alone does
not establish what an active instance displays.

Use existing observations, not another GPU discovery loop. Label requested TDP as
configured; renderer unknown stays unknown. Keep collection admission independent
from presentation. Do not enable log upload or arbitrary command metrics as a
side effect of enabling an overlay.

**Acceptance.** Existing user config, explicit takeover, external edits before
restore, interruption at each journal phase, missing/corrupt backup, symlink races,
reload/uninstall, stalled worker, version mismatch, and no running game. Verify
actual overlay contents and frame-time overhead on the target device.

Evidence: [ownership implementation](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/mangohud/ownership.py#L129-L177),
[conflict and restore paths](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/mangohud/ownership.py#L252-L424),
[ownership tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_mangohud_ownership.py#L37-L75),
[coordinator](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/mangohud/coordinator.py#L28-L118),
[coordinator tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_mangohud_coordinator.py#L8-L111).
Re-Gear already has [honest diagnostic overlay fields](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/src/diagnostics-overlay.ts#L111-L134).
Primary interface reference: [MangoHud configuration documentation](https://github.com/flightlessmango/MangoHud#hud-configuration).

## 7. Personalization: keep visibility, activation, and capability independent

**Observed implementation.** Upstream distinguishes visible, background, disabled,
blocked, and locked module states. Its layout migration discards stale IDs,
deduplicates order, appends new defaults, and retains pinned entries. Custom
views mount shared providers, including the display confirmation and power
conflict surfaces needed by those controls.

**Re-Gear adaptation.** Add preferences beside the current module registry, not
inside capability observations. Hidden can still mean running. Disabled is a
request until the backend confirms stop. Unavailable and blocked capabilities
should remain explainable. Retain the approved Command Center structure and
make customization explicit; do not reorder controls whenever hardware changes.

One provider should own each module's state across tiles/details/custom views.
No duplicate poller or writer should be created when the same control appears
twice. Recovery, stop, confirmation, and result access must survive hiding a tile.
The existing stable order and blocked-but-reachable destinations are useful
Re-Gear behavior, not missing functionality.

**Acceptance.** Corrupt layout storage, removed/new IDs, user hides across upgrades,
failed disable, dependency disable, duplicate controls, pending confirmation
during navigation, and consistent status/error presentation.

Evidence: [module semantics](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/customize/moduleLogic.ts#L22-L52),
[tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/customize/moduleLogic.test.ts#L6-L69),
[layout migration](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/customize/layout.ts#L26-L156),
[layout tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/customize/layout.test.ts#L22-L135),
[provider composition](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/sections/providerMounts.tsx#L23-L115).
Re-Gear: [module registry](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/src/quick-access/module-registry.ts#L47-L86),
[shared performance hook](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/src/quick-access/use-performance.ts).

## 8. Native UI reliability deserves its own acceptance cases

Upstream injects focus styles into the rendered element's owner document, handles
hidden QAM documents, cleans up abort/listener state, and distinguishes scrolling
from navigation. These details matter when modal and panel documents differ.
Mocked observer/document tests provide useful cases but do not validate actual
Steam controller focus.

Re-Gear already has native informational focus stops and root Back handling.
Review future Battery/HUD/customization UI against the actual native shell:
D-pad traversal, return to originating control, scroll boundaries, modal focus
rings, hidden-view work, missing observer support, and unload cleanup. Stop
optional UI work when hidden without stopping backend safety work. A static
screenshot is not sufficient evidence for these interactions.

Evidence: [owner-document focus](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/components/FocusRoot.tsx#L10-L24),
[QAM visibility/navigation](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/components/QamPanelGate.tsx#L78-L175),
[geometry/navigation tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/components/QamPanelGate.test.tsx#L94-L276),
[visibility/cleanup tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/components/QamPanelGate.test.tsx#L341-L459).
Re-Gear: [focus stop](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/src/section-focus.tsx#L4-L18),
[navigation and restoration](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/src/quick-access/module-registry.ts#L118-L193).

## 9. Launch-options assistant: preserve meaning, require explicit Apply and readback

**Observed implementation.** The upstream parser refuses several unsafe-to-rewrite
forms: shell operators, unbalanced quoting, multiline input, and ambiguous
%command% placement. That restricted-domain approach is valuable.

The three-zone serializer does not preserve all accepted token ordering. It
collects assignment-looking tokens from the whole prefix and emits them before
wrappers. Static example: wrapper FOO=bar %command% can serialize as
FOO=bar wrapper %command%. A wrapper argument has become an environment
assignment. This is a source-derived counterexample, not an executed shell test.

The UI saves after 500 ms and flushes pending changes on unmount. The native
setter adapter reports success if invocation does not throw; it does not read
back the resulting string. A baseline read once also cannot detect an external
edit made while the dialog is open.

**Re-Gear adaptation.** Start with read-only explanation, capability/version
evidence, and exact before/after preview. Keep unsupported options unknown.
Reject assignments following wrapper tokens unless a reviewed parser preserves
their positional meaning. Before explicit Apply, re-read and compare the source
revision/string; after Apply, verify exact persistence. Closing or cancelling
should not apply changes. Use the existing game-adapter transaction concepts,
not a root arbitrary-command endpoint.

**Acceptance.** Wrapper arguments, quoting/escapes, custom launchers, duplicate
%command%, malformed input, unknown tokens, concurrent Steam Properties edits,
wrong/missing AppID, async/no-op setter, failure retry, cancel, and game exit.
Preserve byte-identical input for no-op edits where practical.

Evidence: [parse/serialize](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/launch/compose.ts#L87-L129),
[parser tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/launch/compose.test.ts#L15-L129),
[autosave/unmount](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/launch/useLaunchEditor.ts#L99-L143),
[baseline acquisition](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/launch/useLaunchEditor.ts#L49-L77),
[native setter](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/launch/steamApi.ts#L167-L182),
[mocked save tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/launch/useLaunchEditor.test.tsx#L58-L96).
Re-Gear: [existing future adapter protocol](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/game_adapter.py).
This baseline has a pure contract, not a production launch-options writer.

## 10. Display presets: bind previews to the exact output; verify HDR separately

**Observed implementation.** Color preview validates game context, binds scope/AppID,
and has a backend monotonic confirmation window and revert task. This is a good
UX pattern. It is not bound to the physical output, and tests retain a legacy
unbound confirmation path. An in-memory timeout is not a crash-recovery journal.

HDR application is a separate weaker path: the setter stores preference, schedules
a command, and does not consume its Boolean result. A command exit code is not
active-mode readback.

**Re-Gear adaptation.** Bind preview to game, verified user/session, physical output
identity, topology generation, and the specific change. Persist enough evidence
for bounded recovery if the change can survive backend restart. Invalidate
confirmation on monitor switch or undock. Restore only the same resource when
safe, otherwise report action required instead of applying an old calibration
to a new TV.

Treat color calibration, desired HDR, active HDR, active display, and render GPU
as distinct observations. Never describe an LCD color preset as actual OLED/HDR
capability. Keep disruptive display changes within existing transition authority.

**Acceptance.** Monitor removal during preview, replacement display, game switch,
QAM closure, failed revert, backend crash, Gamescope restart, external setting
change, and missing/contradictory HDR readback.

Evidence: [preview binding and timeout](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L7104-L7193),
[tests inspected including legacy path](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_color_rpc.py#L269-L336),
[HDR setter/reapply](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L7327-L7352),
[HDR adapter](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/display/hdr.py#L1-L15).
Re-Gear: [safety invariants](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/docs/SAFETY_INVARIANTS.md),
[mode preferences](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/domain/mode_profiles.py).

## 11. Audio: share routing ownership and preserve volume/mute

**Observed implementation.** The PipeWire EQ path contains prepared/active route
journals, original/requested output tracking, channel volumes, mute, cleanup,
and recovery information. Tests check that failed or ineffective restarts cannot
publish a new curve and that retry backs off.

Two assumptions do not fit Re-Gear: unknown/missing route information becomes
speaker, and session discovery selects the first matching PipeWire socket.
These can target the wrong profile/session in an ambiguous setup. They are
source-level limitations; no resulting device incident is claimed here.

**Re-Gear adaptation.** Use the existing verified Gamescope user context and audio
handoff owner. Add EQ as a consumer/extension of that owner, not an independent
default-sink watcher. Classify internal speaker, headphones, external output and
unknown explicitly. Unknown EQ should remain flat/off. Preserve independently
observed per-channel volume and mute during every route/processing transition.

PipeWire's documented filter-chain mechanism supports constructing an EQ graph;
it does not certify presets, speaker safety, routing correctness, or latency on
a particular handheld.

**Acceptance.** Speaker/headphone/HDMI transitions, mute, asymmetric channel volumes,
multiple user sessions, service restart/no-op/failure, hot-unplug/replug,
eGPU audio removal, missing restoration target, and retry without loudness jumps.
Measure audio latency and CPU cost.

Evidence: [route defaults](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/audio/route.py#L17-L42),
[session discovery](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/audio/pipewire.py#L174-L183),
[journal state](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/audio/pipewire.py#L482-L578),
[restart tests inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_audio_pipewire.py#L1357-L1428).
Re-Gear: [existing verified audio handoff](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/adapters/steamos/audio_handoff.py#L89-L159),
[restore/select/readback](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/adapters/steamos/audio_handoff.py#L294-L346).
Primary reference: [PipeWire Filter-Chain](https://docs.pipewire.org/page_module_filter_chain.html).

## 12. Controllers: daemon cooperation must preserve the actual active profile

**Observed implementation.** InputPlumber controls are built from live capabilities
and device labels, and invalid source controls are rejected. However, applying
an override first resets the daemon to its shipped default, then reads/merges
that baseline and loads the result. This is used by ordinary
set_controller_button/set_button calls,
not only by an explicit “reset entire profile” operation.

The source-level failure sequence is: reset succeeds; reading, merging, or loading
the replacement fails; the previous active custom profile has already been
replaced. Updating the plugin's store only after success does not undo that reset.
Even on success, merging from the shipped default can discard mappings made by
another tool. This is a static concern, not a reproduced hardware loss.

**Re-Gear adaptation.** Preserve the existing canonical shortcut delivery boundary.
Full remapping is a separate capability. If added, establish one provider owner,
snapshot the actual active profile, edit only owned mappings, verify the loaded
result, and conditionally restore the prior profile. Capability/API availability
does not prove native Steam/game delivery.

**Acceptance.** Existing custom profile, failed snapshot/merge/load, changed external
profile, provider restart, duplicate virtual devices, transport change, controller
reconnect, ordinary controls, gyro and rumble continuity, and actual in-game input.
No global raw-input grab should be introduced simply to expose additional buttons.

Evidence: [ordinary button RPC](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/main.py#L1814-L1825),
[remap call and reset-first helper](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/controllers/inputplumber.py#L42-L82),
[capability model](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/controllers/inputplumber.py#L13-L39),
[ordinary-edit reset assertion inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_controllers_backends.py#L108-L134).
That fake records a reset call; it does not reproduce loss of an existing profile
after a successful reset followed by failed merge/load.
Re-Gear: [canonical shortcut delivery](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/application/controller_shortcut_delivery.py#L47-L73).

## 13. Fan curves and download mode: useful ideas with larger validation costs

The software fan loop serializes control/release, verifies a previous requested
target against RPM, and tests that release wins over a blocked in-flight tick.
Those are good lifecycle cases. However, missing temperature returns without a
new write or handback in the shared path. A prior target can remain in effect;
an ordinary unload callback also cannot guarantee recovery after process kill.

Start with read-only temperature/RPM status. Manual curves require a separate
device-specific thermal safety and ownership design: stale sensor policy,
firmware/daemon fallback, startup crash recovery, and independent protection.
Do not adopt EC writes or learned curves from a support-table checkmark.

Download mode should be a temporary coordinated session, not a collection of
unrelated global setting writes. The upstream feature combines lower power,
disabled boost, and screen dimming. Test total download/decompression time and
energy; reduced instantaneous watts can prolong CPU-heavy unpacking. Restore
the captured prior settings only when still owned, and preserve intervening
player changes. A sleeping device cannot be assumed to continue downloading.

Evidence: [fan target handling](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/fans/software_loop.py#L112-L116),
[fan read/write path](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/fans/software_loop.py#L185-L202),
[blocked-write release test inspected](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/tests/test_fan_software_loop_lifecycle.py#L131-L166),
[download dimming semantics](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/src/system/eco.ts).
Upstream [feature description](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/README.md) supplies download-mode intent;
full download lifecycle/energy behavior remains unvalidated in this review.

## 14. Storage and release lessons should reinforce existing Re-Gear contracts

The small upstream atomic JSON helper uses a unique sibling and replacement, but
does not fsync file/directory or validate a schema. Its simplicity is useful for
noncritical preferences; it is not a replacement for Re-Gear's durable privileged
transaction stores. The HUD ownership and audio journal implementations have
more extensive controls and should not be conflated with this helper.

Upstream CI separates frontend/backend path selection and fails on invalid
classification. This is a useful test-cost pattern if Re-Gear later splits jobs:
an unknown path classification must not silently skip validation. Its release
workflow builds a helper and attests the ZIP, but also uploads with --clobber.
Retain Re-Gear's immutable versioned archives and no-clobber publication.

The README/bundled-helper disagreement and the Re-Gear full-license-text mismatch
are detailed in [Attribution](ATTRIBUTION.md). Validate the actual deliverable,
not merely a notice claiming it contains something.

Evidence: [small JSON helper](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/py_modules/json_store.py#L6-L22),
[CI classification](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/.github/workflows/ci.yml#L18-L115),
[release workflow](https://github.com/Hooandee/panel-de-control/blob/c8b8d1eb363ce42317e0bcfb4c39b8cf8a22c1cc/.github/workflows/release-please.yml).
Re-Gear: [durable preference storage](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/backend/hdm/delivery/auto_tdp_preferences.py#L154-L188),
[immutable release rules](https://github.com/ronnierosal/Re-Gear/blob/c09df57fe03a8d89c69afb0c8d9fb1664d14c741/docs/CHAT_COORDINATION.md).

## Proposed implementation slices

These are unassigned proposals. Check the live hub and active PRs before creating
tasks; another owner's work may have advanced beyond this pinned baseline.

| Slice | Scope and seam | Completion evidence |
|---|---|---|
| B1 Battery observation | New pure observation + bounded provider read; Battery module uses shared state | Fixture cases for unknown/multiple supplies; measured read cost; supervised read-only identity comparison |
| B2 Charge control | Separate provider ownership and generation-bound apply/readback/restore | Failure/race tests, exact policy for disable/unload, provider-specific live readback |
| P1 Profile resolution | Extend existing intent contracts, no automatic mutation | Precedence, inheritance, unknown placement, duplicate identity and migration tests |
| P2 Profile UI/store | Explicit save versus apply, source-of-value labels, bounded persistent schema | Game-switch races, corrupt storage, unchanged defaults during adaptive sessions |
| H1 HUD ownership | Preview, exact config ownership, journal and bounded worker | Conflict/crash/restore tests before live injection |
| H2 HUD delivery | Small preset using admitted shared observations | Exact instance/config verification and measured game-time overhead |
| U1 Personalization | Preferences beside module registry; shared providers | Layout migration, retained recovery, one poll owner, native D-pad/Back acceptance |
| L1 Launch explanation | Restricted parse/explain/diff only | Adversarial token/order corpus and byte-preserving no-op |
| L2 Launch apply | Expected revision, explicit apply, native setter/readback | External-edit rejection and no false Saved state; reviewed Steam adapter |
| M1 Media profiles | Exact output/session identity before EQ/color writes | Bounded preview/restore and route/volume continuity on real devices |

For each implementation PR, record original versus adapted source, corresponding
upstream revision, current Re-Gear base, owner, contract changed, deterministic
checks, and remaining device gates. A passing fake-device test must never become
a hardware support claim.

## Source and evidence limits

The linked code and specific test bodies support the statements above. Additional
test names encountered while indexing are not counted as inspected assertions.
Upstream examples and comments were checked against executable branches where
material; the conclusions do not certify every caller or all supported devices.
The [source inventory](SOURCES.md) records the scope and primary documentation.
