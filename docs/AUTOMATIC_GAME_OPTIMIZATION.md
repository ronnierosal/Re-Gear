# Automatic game optimization: architecture and staged plan

Status: proposed architecture, 2026-09-23. This document does not enable runtime
optimization. The player chooses an experience; Re-Gear selects a validated way
to deliver it. Learn during ordinary play, settle on a sustainable profile, then
leave it alone. No runtime LLM, gameplay upload, continuous graphics tuning or
unsupervised hardware trial is part of this design.

## Existing foundation and gaps

Inspection baseline: profile foundation PR #375 at `9d48d61`, semantic engine
PR #386 at `27eeda0`, inert resolver/provider continuation PR #388 at `cce3d75`.
These are source artifacts, not installed or hardware-validated functionality.

| Reuse | Boundary / missing work |
| --- | --- |
| [Profile foundation](GRAPHICS_PROFILES_ARCHITECTURE.md) | Claude owns adapters, discovery, schema checks, baseline backup, provenance, conflict protection and atomic writes. Real-game evidence remains separate. |
| [Semantic engine](GAME_PROFILE_ENGINE.md) | Consumes declarative settings. Do not fork its catalog or ownership model. |
| `performance_target_resolver.py` and `performance_plan_bridge.py` | Pure evidence-driven decisions and previews; execution remains forbidden. Current strict native-first precedence does not implement the quality policy below. |
| [Frame-generation research](research/frame-generation.md) | Pinned upstream evidence, user-installed components and unresolved launch/failure gates. A fake provider is not runtime validation. |
| [Auto TDP](TDP_CONTROL.md) | Existing power authority; reuse its admission, bounds, writer and explicit-stop semantics. No second power controller. |
| [Overhead assessment](PERFORMANCE_MEASUREMENT.md) | Pure diagnostic assessment, not a gameplay collector. Its current running-game deferral does not authorize learning telemetry. |

Learning, lock persistence, quality floors, community distribution and a real
game launch hook are not implemented by this proposal.

## Ownership and data flow

Existing identity, observed mode, game-session, display and capability ports
supply observations. Unknown/degraded mode or ambiguous game identity withholds
automatic application. Marketing device names are labels, not capabilities.

Player intent + capability snapshot + contextual evidence + adapter-owned
candidate profiles feed a pure Performance Resolver. It produces a versioned
PerformancePlan and explanations. Claude's engine translates game-owned fields;
the provider layer prepares provider-owned configuration. A future coordinator
checks current admission immediately before each action. Planning itself performs
no discovery, writes, process launch, GPU selection or power operation.

Codex owns resolver, evidence assessment and provider planning. Claude owns game
schema, settings and preservation. Mode/session/display owners retain their
observation ports. Auto TDP retains power execution. UI and community transport
need their respective owners before integration. A proposed interface is not a
cross-owner agreement.

## Intent, eligibility and selection

Persist global enablement and a per-game choice: inherit, automatic or manual.
Global off stops all automatic management, including pending work, without
rewriting settings. Per-game manual likewise cancels that game's pending plan.
Restore Original Settings is a separate explicit engine operation. Re-enabling
must not silently claim player-edited bytes; reuse engine resume/conflict rules.

Intent includes Balanced / Smooth / Quality, optional presentation target,
battery preference and user constraints. Hardware context separates rendering GPU
from display owner, CPU/APU capabilities, RAM/shared memory/VRAM, physical display
refresh and VRR, mode, power bounds and evidence freshness. Missing capabilities
are unknown. Windows is a future provider boundary, not current support.

Selection proceeds deterministically:

1. Reject stale or incompatible candidates, unacceptable quality, unsafe provider
   combinations, insufficient sustainable base performance or excessive measured
   latency/artifacts. Unknown evidence cannot become validated by selection.
2. Compare the remaining candidates against the player's experience constraints.
   Prefer reaching an acceptable target with headroom, retaining visual quality
   and responsiveness. Evaluate measured power only when comparable evidence
   exists; missing power is not zero power.
3. Use a versioned preference policy to rank quality, base responsiveness and
   energy tradeoffs. Balanced seeks a compromise; Smooth emphasizes stability
   and responsiveness; Quality emphasizes retained detail within acceptable
   performance. Tests must fix deterministic ties and explain tradeoffs.
4. Prefer fewer technologies when experience is otherwise comparable. Native
   precedence is a tie-breaker, not permission to sacrifice quality for a counter.
   Fall back to a validated lower experience or Advisor when constraints conflict.

This deliberately supersedes unconditional native-first ranking in the inert
prototype. A good-quality stable base plus validated FG may beat low-quality
native 60. Generated frames never count as base responsiveness. No arbitrary
weighted score or universal 30-FPS floor is accepted without policy review.

## Plan contract and resolution semantics

Proposed extension to the existing plan, to agree with Claude before coding:

| Field | Meaning |
| --- | --- |
| `profile_binding` | Existing game profile identity/version and schema, not another game database |
| `internal_render_resolution` | Actual shading resolution, possibly dynamic or unknown |
| `game_output_resolution` | Game/swapchain output, e.g. 1920x1080 with native temporal upscaling |
| `display_output_resolution` | Physical presentation, e.g. 3840x2160 TV |
| `sustainable_base_evidence` | Observed distribution, demanding-scene coverage, uncertainty and duration |
| `base_fps_target` | Selected real-frame cap, not the highest observed rate |
| `requested_display_fps` | Original player intent, retained separately from a lower fallback |
| `target_display_fps` | Selected planned presentation rate, not a measured achievement |
| `upscaling_plan` | Named provider, concrete mode, scaling location and allowed interactions |
| `frame_generation_plan` | Provider/version, multiplier, pacing and compatibility binding |
| `power_objective` | Advisory base target/headroom and permitted bounds for existing Auto TDP |
| `validation` | Evidence identity, context, freshness, confidence and reason codes |

Current `render_resolution`/engine `resolution` fields are not sufficient to
represent all three resolution domains. Do not reinterpret them silently: version
the contract, agree migration, and refuse ambiguous mappings. With FSR at 1080p
game output, reducing that output to 900p is not equivalent to selecting an
internal render resolution. No accidental game + compositor + external scaler
stack. A profile explicitly declares supported combinations.

Keep sustainable capacity, selected cap, multiplier and measured presentation
separate. Stable 38 FPS times two is 76, not 60. A fixed 2x provider targeting 60
needs a compatible 30-base cap and enough measured headroom after provider cost;
adaptive pacing is unavailable unless that provider supports and validates it.
A request for 90 with a validated 30 x 2 fallback retains requested 90 but plans
60; measured presentation remains separate from both.
Refresh/VRR and limiter interactions remain provider-specific. 900p portable and
1080p docked are candidate preferences, not universal constraints.

## Two loops and a bounded learning lifecycle

The fast loop is existing Auto TDP only: maintain the admitted base objective
inside observed bounds. A plan never starts a stopped power session or bypasses
its safety checks. FG presentation counters must not feed a base-FPS controller.
Power optimization seeks minimum measured cost sustaining the experience with
headroom, not a universal watt setting; APU package power is not total eGPU/system
power. The Auto TDP owner must agree target semantics before wiring.

The slow loop evaluates across sufficiently representative play and launches.
Adapter metadata describes each setting's visual importance, measured cost,
quality floor, restart requirement and interactions. A game-specific ladder may
try power efficiency, quality upscaling, less damaging settings, more aggressive
upscaling, then beneficial FG. No generic texture-low or shadows-first heuristic.
Unknown games remain Advisor until there is a validated safe settings adapter.

Change one interpretable candidate between launches, preserve the last accepted
plan, compare equivalent evidence and either accept or reject. Confounded or
insufficient observations leave the result inconclusive. Never restart gameplay
to complete an experiment. Mode changes queue a newly contextualized plan for the
next launch; fresh mode and run-state checks still apply at dispatch.

| State | Transition evidence / behavior |
| --- | --- |
| UNKNOWN | Resolve identity/capabilities; unsupported paths go Advisor or Unsupported |
| BASELINE | Preserve originals through engine; ordinary gameplay observations only |
| LEARNING | Accumulate qualified windows; no graphics writes during gameplay |
| TESTING_PROFILE | Stage one eligible candidate for next launch; bounded attempt budget |
| VALIDATING | Compare qualified repeated samples; inconclusive stays provisional |
| OPTIMIZED_LOCKED | Persist accepted plan; no recurring benchmark or tuning |
| NEEDS_REVALIDATION | Retain last plan as evidence, assess affected fields before reuse |
| USER_OVERRIDE | Cancel pending management; preserve player changes |
| ADVISOR_ONLY / UNSUPPORTED | Explain missing support; launch remains normal |
| OPTIMIZATION_DISABLED | Cancel pending work; explicit restore remains separate |

Persist versioned state, context fingerprint, accepted/pending plan IDs, evidence
summary and bounded attempt history atomically through an agreed persistence
owner. After a crash, never replay an uncertain write or infer completed
validation. Reconcile with engine provenance; corrupt/unknown state yields
passthrough/Advisor. Disable and user override dominate pending transitions.

## Observation quality and overhead

Reuse a reviewed telemetry source; do not introduce a second per-frame poller.
Separate base and presented frame times, lows, sustained duration, CPU/GPU load,
memory pressure and power/temperature where actually observed. Average FPS alone
is insufficient. Stable quiet-scene performance is not demanding-scene evidence.

Exclude identified loading, menus, startup, shader compilation, cinematics and
background interference. Classification itself needs evidence: an unexplained
slow window is neither automatically discarded as loading nor treated as proof
the graphics profile failed. Require repeated qualified windows and preserve
coverage/uncertainty. A policy must bound attempts and time spent learning; on
exhaustion retain the safe prior plan and report inconclusive, not tune forever.

Before enabling collection, agree explicit numeric budgets for CPU time, resident
memory, wakeups, bytes/day and measured power impact. Measure observer on/off with
the same workload and report uncertainty. Use low-frequency aggregate delivery,
fixed-capacity windows and bounded retention; disable optional observation on
budget breach. No raw gameplay upload, unrestricted log growth or claim of zero
overhead. Current diagnostic assessment is not evidence for in-game admissibility.

Revalidate on relevant game/schema, Proton, driver/OS, hardware/display/mode or
provider changes, player edits, or repeated qualified degradation. Invalidate
only affected evidence; do not erase originals or relearn every launch. Retaining
a previous profile does not authorize applying it to a changed incompatible
schema. Engine ownership/conflict checks remain final authority.

## Sharing and trust

Community profiles are candidate evidence, never automatic authority. Keep source
provenance (local, community, community-reviewed, Re-Gear-reviewed) distinct from
local compatibility/validation. Even verified community data needs local context
checks and bounded validation. Match capability classes to discover candidates;
use exact local context/version evidence to admit them. This avoids both a single
universal profile and a separate catalog for every marketing model.

Future imports need a bounded declarative schema, versioning, integrity/source
checks and no executable commands or arbitrary paths. Contributions require
explicit consent and an allowlist preview: no saves, account names, local paths,
raw configs or gameplay. Export only permitted settings, capability class and
aggregates. No transport or sharing UI is authorized by this architecture.

## Failure and installation behavior

Users supply their purchased Lossless Scaling installation and the separately
installed Linux provider, following the pinned research guidance. Re-Gear may
eventually guide setup and verify availability; installed does not mean validated
for a game. No redistribution right is assumed.

Pre-launch preparation failure discards the whole proposed overlay and related
game plan, preserves player inputs and launches normally. The prototype proves
only this planning behavior. In-process provider failure after launch cannot be
advertised as recoverable until demonstrated; no launch retry/restart loop.
Keep live integration gated pending launch ownership, per-game Steam Cloud
ordering, schema evidence and reliable provider failure behavior.

## Staged delivery and acceptance

| Stage | Deliverable and owners | Acceptance / stop point |
| --- | --- | --- |
| 0: agree contracts | Codex + Claude: three resolution domains, profile binding, evidence/intent versions; Auto TDP and observation owners review proposed seams | Recorded agreements; keep current prototype inert; resolve dependency integration and outstanding attribution separately |
| 1: pure policy | Codex: quality floors, preference ranking, contextual invalidation, bounded learning state machine with fake observations | Deterministic tests for quality-vs-native tradeoff, base/presentation separation, disable/override, corrupt state, noise, exhausted attempts, lock and next-launch queuing; no runtime caller |
| 2: passive evidence | Telemetry owner with Codex: reviewed aggregate source and local persistence | Measured overhead budgets, trustworthy base source, exclusions/uncertainty; observer-only supervised trial before any tuning |
| 3: one-game controlled plan | Claude validates adapter/schema; Codex provider; shared launch owner agrees ordering | FFVII Remake Intergrade Steam AppID 1462040 is first candidate, not certified. Backups/restoration, Cloud ordering, launch passthrough and player-edit protection demonstrated |
| 4: supervised learning | Codex slow evaluator + existing engine/Auto TDP owners | Same-scene native/upscaled/FG comparison: base frame times, responsiveness, artifacts, power and provider overhead; demanding-scene coverage, lock/revalidate and easy disable tested. No automated random-game trials |
| 5: product and sharing | UI owner implements simple controls; separate community owner | Approved presentation, privacy consent/import validation, local trust checks, measured fleet variability; no expansion from fixtures alone |

The next coding slice is Stage 1 after Stage 0 contract review, not a live
auto-tuner. Cross-owner integrations remain separate assignments. This plan does
not modify eGPU/USB4 lifecycle, render-GPU selection, controllers, sleep/shutdown,
hardware recovery or Command Center presentation.
