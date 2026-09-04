# HDM worker queue

This is the current coordination source of truth for bounded local work. It
does not replace executable behavior, [the roadmap](ROADMAP.md), or the
[safety invariants](SAFETY_INVARIANTS.md). The North Star is console-simple,
games-first SteamOS: HDM stays light, mostly dormant, event-driven where
practical, and never trades safety or game performance for automation. Licensing
remains GPLv3+ for community use and separately negotiated for commercial/OEM
use; see [Licensing](LICENSING.md).

## Rules

- An idle worker may take the first unblocked item only when it is within its
  authority and can remain bounded, reversible, and independently verifiable.
  Otherwise record the blocker and take the next safe item.
- **Implemented**, **Simulated**, **Remotely Observed**, **Hardware Validation
  Required**, **Hardware Validated**, and **Certified** are distinct statuses.
  Code or capture never upgrades hardware validation.
- No deployment, sleep/reboot, Gamescope restart, display/GPU/audio/controller
  mutation, USB4/PCIe reset, process signaling, or G1 removal without the
  explicit supervised gate. Read-only capture does not authorize a transition.
- This queue enables fast continuation; it does not schedule autonomous work.
  A worker must be triggered, or a separately authorized future heartbeat must
  be active.

## Ordered queue

### 1. Ally ↔ G1 end-to-end dock, play, sleep, and undock journey

**Status: Proposed parent journey.** It is the overarching player-facing focus,
not a claim that the journey is currently supported. HDM must never promise
live GPU migration or game survival. No disruptive hardware action is allowed
without explicit supervision, and no safe-to-unplug result is allowed without
verified clients, topology, display, and input evidence. Read-only Ally evidence
is permitted.

| Priority | Bounded sub-item and owner | Status | Acceptance evidence |
| --- | --- | --- | --- |
| 1.1 | Attach detection and health. Owner: mode/link worker. | **Implemented (local, link-gated):** `ready_idle` now also requires an observed Up exact bridge link; Down/unknown remains waiting. End-to-end behavior is **Hardware Validation Required**. | Exact attach/health replay tests and redacted read-only supported-profile evidence. |
| 1.2 | Game-open deferred dock intent. Owner: transition worker. | **Implemented (pure, local-only):** direct player intent may expire, cancel, or invalidate while a game runs, then yield only a fresh idle eligibility handoff. No automatic transition authority exists. | Deterministic creation/cancellation/expiry/binding-change/unknown-game/idle-handoff tests; later supervised proof only after a reviewed mechanism. |
| 1.3 | Game-closed verified TV, audio, and controller handoff. Owner: transition/peripheral worker. | **Implemented (pure eligibility/rollback contract):** only fresh, consistent, verified Idle TV/render/audio/controller and Portable rollback facts can become non-authorizing eligible; partial failure requires rollback. Handoff is **Hardware Validation Required**. | Exact idle, display, audio, controller, and rollback evidence in a supervised test. |
| 1.4 | Five-second post-game prepared-docked-idle state. Owner: transition worker. | **Implemented (pure revalidation contract):** two fresh consistent Idle samples with the same attachment/generation and a new sample at >=5 seconds can yield non-authorizing prepared evidence. No timer or prepared-dock authority exists. | Deterministic under/exact/over-boundary and invalidation tests, then supervised observation without a running game. |
| 1.5 | Safe Undock readiness scans. Owner: recovery worker. | **Implemented (pure read-only revalidation contract):** complete fresh opaque-bound client/topology/game/Portable-fallback/display facts can be only `ready_for_revalidation`; any gap stays insufficient/not-ready/invalidated. Physical unplug safety is **Hardware Validation Required**. | Fresh exact client, storage, topology, display, and input scans; incomplete evidence remains unsafe. |
| 1.6 | Human-acknowledged Safe Undock result presentation. Owner: recovery worker. | **Implemented (pure, local-only):** Stage 1.5 revalidation-bound evidence can be presented only as insufficient, not-ready, revalidate-required, or eligible to begin supervised physical validation. It never says safe-to-unplug or takes action. | Deterministic acknowledgement/stale-binding/generation/sample invalidation tests; every physical test remains separately approved and **Hardware Validation Required**. |
| 1.7 | Unexpected removal recovery to handheld. Owner: recovery worker. | **Implemented (pure, local-only assessment):** fresh opaque-bound before/after bridge/topology loss plus verified internal display/input/audio can report only portable-fallback evidence. Unknown, stale, changed, or contradictory facts fail closed; no recovery/relaunch action exists. Hardware recovery is **Hardware Validation Required**. | Deterministic loss, fallback, missing-signal, unknown-game, stale/binding-change, and contradiction tests; separately approved supervised handheld recovery scenario. |
| 1.8 | Sleep/wake with G1 present or missing, with honest game-relaunch policy. Owner: sleep/recovery worker. | **Implemented (pure, local-only eligibility):** verified handheld fallback, stopped-game observation, clear risks, fresh evidence, and explicit opt-in can only label a future relaunch flow eligible. Unknown/running game, risks, repeated failure, stale/contradictory evidence, or uncertain preference block it. Wake behavior and relaunch are **Hardware Validation Required**. | Deterministic recovery, first-prompt, opt-in/out, risk, failure-limit, stale, and contradiction tests; separately approved supervised scenarios. No crash or relaunch claim from passive evidence. |

### Supporting queue

**Active separate workstream: TDP / Auto TDP.** The maintainer assigned research,
development and remote checks to `codex/tdp-control` on 2026-09-04. Its initial
thermal fix, ASUS read-only inventory and pure FPS proposal policy are locally
implemented and tested. SteamOS Manager ASUS provider, fixed D-Bus runner,
manual apply/verify/restore and atomic journal are also implemented/simulated.
Manual lifecycle/RPC/UI delivery, known-controller detection and a Re-Gear writer
lease are implemented and locally tested. Live provider discovery, Linux lock
validation, actual gameplay telemetry and the live Auto TDP loop remain pending. See
[TDP control](TDP_CONTROL.md). It does not own G1 lifecycle transitions.
The composed Auto evidence collector now checks workload/power context around
every retained frame and resets history across setting/source changes; the
session factory is implemented and integration-tested. Host configuration, Decky
RPC/UI wiring, justified thermal profile and measured admission remain.
The complete-path read-only benchmark is implemented and fixture-tested, including
context changes, expiry, cancellation, time/cadence bounds and no-write behavior.
Actual device measurement and binding its evidence to host configuration remain.
Explicit benchmark run/status/cancel RPCs now share runtime ownership with power
writes, with pending-request cancellation and drain tests. Backend checkpoint:
1,106 tests successful, 14 platform skips. Benchmark UI remains pending.
Exact host/firmware/kernel/provider/range compatibility binding is implemented
and checked on collection and dispatch. Strict private-file configuration loading
is implemented/tested. Main now supplies the lazy factory and explicit Auto
status/start/stop RPCs with request-bound cancellation. Expandable frontend
controls and availability explanations are implemented, with schema/race tests
and mock browser interaction/layout checks. Benchmark RPC integration, provenance
evidence, actual device measurements and native Decky/controller checks remain.

| Priority | Work item and owner | Status | Acceptance evidence |
| --- | --- | --- | --- |
| 2 | Mode/link health: improve fail-closed usability signals and bounded link-instability diagnostics. Owner: next safe worker. | **Implemented (pure evidence + read-only UI):** fresh same-binding observed Up/Down samples can report stable/changed state or fail closed; `Ready to dock` also requires a current exact G1 profile, verified present external GPU/display facts, verified Gamescope, and a current observed-Up link—never only a stale display or sleep guard. Quick Access stays categorical; no collector, transition, or removal conclusion exists. Hardware link quality is **Hardware Validation Required**. | Pure/replay tests; privacy-safe snapshot/UI checks; supported-profile read-only capture when useful. |
| 2.1 | D2 graceful plugin retirement. Owner: lifecycle worker. | **Implemented (local-only):** `fd2d38f` executor draining did not clear the watched five-second Decky SIGKILL, so it is retained as a guard but not treated as the sole cause. `49c826c` additionally admits the Docked-iGPU watcher only for Running Docked-iGPU, keeping the portable/Idle D2 baseline dormant; deterministic admission and unload-guard tests pass. **Hardware Validation Required**. | Full local matrix; one player-watched G1-disconnected native install of `49c826c` and unload/reload observation before D2a. Stop on any SIGKILL, display/input/session issue. |
| 3 | Recovery and unified transitions: deterministic replay, journal, rollback, Portable recovery, and Safe Undock guards. Owner: transition/recovery worker. | Policy/replay and **transport-free explanation deduplication** are **Implemented/Simulated**; recovery notification transport and live execution are **Hardware Validation Required**. | Architecture + deterministic failure/explanation tests; a separately approved supervised run for any mechanism. |
| 4 | Offline Readiness delivery: review a local Steam/launcher source, then surface only fresh categorical results. Owner: evidence/UI worker. | Classifier/admission, **pure source-review boundary**, and read-only UI presentation are **Implemented**; current snapshot delivery and collection authority are not. Source declarations must be local/read-only/non-networked/non-persistent/minimized, then pass cost/freshness/game admission. UI accepts only optional public categorical status/reason payload and says “Not connected” when unwired. | Privacy review, declared/benchmarked cost, idle-only/defer/freshness tests, reviewed read-only delivery; no account/AppID/title/path in delivery. |
| 5 | Navigation/UI cleanup: keep Quick Access compact, controller-friendly, and non-authorizing. Owner: frontend worker. | **Implemented (read-only UI + optional delivery validation):** compact health plus deferred/prepare/Safe Undock/recovery journey rows, controller-focusable details, and runtime dropping of raw/malformed optional journey fields. Values remain fail-closed “Not connected” until reviewed snapshot wiring exists. Live evidence wiring and hardware behavior are **Hardware Validation Required**. | Frontend accessibility/navigation/schema-redaction tests, typecheck/build, reviewed read-only schema delivery, and a maintainer-visible package review before install. |
| 6 | Performance/resource measurement: measure snapshot and optional-observer overhead; retain only event-driven or budgeted work. Owner: performance worker. | Telemetry admission, UI cadence, pure one-sample assessment/reporting, and **optional Troubleshooting presentation** are **Implemented**; collector and actual supported-profile measurement are pending. Reports are identity-free and game impact remains Unknown; unwired delivery remains unavailable. | Reproducible bounded existing-work timing plus player-observed game-impact evidence on the supported profile; no meaningful regression. |
| 7 | TV wake / HDMI-CEC feasibility. Owner: future display worker. | **Implemented (pure contract):** stable eligible idle attach or verified external-controller activity in prepared TV context may form one deduplicated future request only with CEC eligibility and fresh external-display revalidation. Running games, unverified input, stale evidence, or prior attempt block it. No adapter, listener, collector, wake/display action, or G1/TV capability claim exists. | Reviewed adapter authority plus supervised observed before/attempt/after evidence. |
| 8 | Thermal/fan health. Owner: future health worker. | **Implemented (pure assessment):** optional Ally and eGPU readings remain unavailable/unknown without explicit available fresh data; attention requires three sustained >=90C samples. No sensor reader, poller, fan control, TDP, or device action exists. | Reviewed bounded sensor source and supported-profile observation. |
| Backlog | User-initiated Hardware Health Check / Guided Troubleshooting. | **Intentionally deferred:** preserve the pure healthy/attention/unknown design and calm next-step policy, but do not add an end-user flow in the active cycle. No stress workload, collector, poller, settings/process/device action, or support upload exists; future corrections require preview/approval/audit. | Resume only after the active thermal/provenance/TV-wake/controller/offline/UI/diagnostics sequence. |
| 10 | Status-first Quick Access visual refinement. Owner: frontend worker. | **Proposed:** keep four primary facts, native Decky controls, compact progressive details, controller focus, and fail-closed unknown wording. eGPUBridge may inform navigation taste only; no copied code, new authority, or hardware behavior. | Frontend visual/controller review, accessibility checks, typecheck/build/package review. |
| 11 | Release-candidate pipeline. Owner: release/verification worker. | **Implemented (local-only):** semantic version consistency, deterministic ZIP/build/SHA record, notes template, and CI artifact validation. No publication, credentials, deployment, GitHub Release, or Decky Store/channel action exists. | Local tests and CI archive verification; maintainer-reviewed manual publication plus separate channel registration remain required. |

## Required checkpoint check-in

Record each meaningful checkpoint in [Operator handoff](OPERATOR_HANDOFF.md)
and, when status/dependencies change, [Roadmap](ROADMAP.md):

```text
Change: <bounded files/behavior; state implemented vs proposal>
Verification: <exact commands/tests/build and result>
Hardware evidence: <none | redacted read-only capture | supervised validation>
Blockers: <authority, safety, or evidence gap>
Next safe task: <one concrete, bounded item>
```

Exclude secrets, raw device identities, and transient logs.

## Integration

Commit only small, coherent, verified slices. Before integration, inspect the
diff and relevant tests, confirm clean ancestry and no unrelated worktree
changes, then fast-forward or make the smallest safe merge. Resolve conflicts
deliberately, record the check-in, and do not leave completed worker commits
queued without a reason.
