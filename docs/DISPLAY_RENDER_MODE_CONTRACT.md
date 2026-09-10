# Display-only switching and internal-GPU TV output

Design and feasibility record for two distinct player requests. **Designed**
(plus one **Implemented** pure classifier). Nothing here is a hardware claim,
and nothing here authorizes a display or GPU mutation, an installation, or a
physical action.

## The two requests are not the same operation

| | Request | Meaning |
|---|---|---|
| **(a)** | "Keep the same rendering GPU and the same running game, change only the display." | The renderer stays put; the scanout target moves between the Ally panel and the TV. |
| **(b)** | "Use the internal GPU to drive the TV while the eGPU is attached." | The scanout target stays on the TV; the renderer moves from the eGPU to the internal GPU. |

(a) is a **display move**. (b) is a **render handoff**. They are separate axes
([`ARCHITECTURE.md`](ARCHITECTURE.md), "Physical connection, display target,
render GPU, Gamescope, workload, support, and health are separate axes") and
they have different costs. Conflating them is how "just move the picture" turns
into an unannounced change of which GPU runs the game.

The short answer, derived below:

- The renderer can be preserved across a display move. **The running game
  cannot.** Both requests require closing the game first, because the only
  supported output route is applied when Gamescope execs.
- (b) is already expressible end to end in the launch configuration and the
  shim, but no planner or RPC destination reaches it, and it has no public mode.
- The purest form of (a) — eGPU rendering to the Ally panel — is not expressible
  at all.

## The one supported output route

There is exactly one mechanism by which Re-Gear selects a display target or a
render GPU. It is a launch-time argument rewrite, not a runtime modeset.

1. A guarded transition writes a boot-scoped launch configuration
   (`backend/hdm/delivery/presentation_config.py:81` `build_target`). Its
   `target` is one of `portable`, `docked_igpu`, `docked_egpu`
   (`backend/hdm/delivery/gamescope_wrapper.py:46`).
2. The same attempt then queues
   `UserServiceOperation.RESTART_GAMESCOPE_SESSION`
   (`backend/hdm/adapters/presentation_transition.py:247`). Every presentation
   change — including a display-only one — goes through this single call.
3. On the next Gamescope exec, the packaged shim re-derives the current
   evidence, picks an output order and a Vulkan device
   (`backend/hdm/delivery/gamescope_wrapper.py:163`
   `select_launch_configuration`), rewrites `-O/--prefer-output` and
   `--prefer-vk-device`, and sets `MESA_VK_DEVICE_SELECT`
   (`gamescope_wrapper.py:99` `rewrite_gamescope_argv`, `:312` `main`).

### Compositor APIs that exist, and what they can do

| Surface | What it can do | Can it switch output or renderer? |
|---|---|---|
| Gamescope argv + `MESA_VK_DEVICE_SELECT` via the packaged shim | Select the output order and the Vulkan device **for the session being launched** | Yes — only at exec |
| `gamescope_control` Wayland protocol client (`backend/hdm/adapters/steamos/gamescope_performance.py`) | Bounded one-shot `request_app_performance_stats` | No. The module is explicitly "no compositor mutations"; only registry, sync, bind and the stats request are emitted |
| `drm_crtc` reader (`backend/hdm/adapters/steamos/drm_crtc.py`) | `DRM_IOCTL_MODE_GETRESOURCES` / `GETCRTC` observation | No — read-only |
| `drm_display_release` (`backend/hdm/adapters/steamos/drm_display_release.py`) | Legacy `MODE_SETCRTC` with `fb_id=0` to *release* a CRTC during teardown | No. It blanks a CRTC for removal; it cannot hand an output to another GPU or another session |

**Conclusion: no live display-switch API is implemented, and none is wired.**
Any change of display target or render GPU is a Gamescope session restart.

### A Gamescope restart ends the running game

This is the fact that decides both requests.

- Safety invariant 2: "A transition that requires restarting Gamescope is
  blocked while a game is running." Invariant 3 treats unknown game state the
  same way ([`SAFETY_INVARIANTS.md`](SAFETY_INVARIANTS.md)).
- [`ROADMAP.md`](ROADMAP.md): "Treat game-running or unknown game state as a
  blocker whenever Gamescope would restart."
- Hardware evidence that the session takes Steam with it:
  [the 2026-09-02 incident record](ALLY_X_GPD_G1_DOCKING_INCIDENT_2026-09-02.md)
  observed that during an unexpected loss "Gamescope and Steam were absent while
  the operating system, SSH, and Decky plugin remained responsive", and SteamOS
  then "relaunched Gamescope on the internal panel and restarted Steam". That
  record is about an unexpected loss, not about a Re-Gear transition; it is cited
  only as evidence that the Gamescope session and the Steam/game session share a
  lifetime.

Once a session is running in a combination, games launched *inside* it inherit
that combination with no further restart. The restart is the cost of **entering**
a combination, paid once, while idle.

## Capability and authority matrix

Rows are the four observable placements
(`backend/hdm/domain/inference.py:41`-`48`). This table is also executable:
`backend/hdm/domain/display_render_modes.py` encodes it and
`tests/test_display_render_modes.py` asserts it against the real planner and the
real inference rather than letting prose drift.

| Placement | Display | Render GPU | Launch-config target | Planner destination? | Public `OperatingMode` | Route support |
|---|---|---|---|---|---|---|
| Portable | Ally panel | internal | `portable` | **Yes** | `PORTABLE` | Plannable |
| Docked-eGPU | TV on the eGPU | eGPU | `docked_egpu` | **Yes** | `TV_DOCKED` | Plannable |
| Docked-iGPU | TV on the eGPU | internal | `docked_igpu` | **No** | **`UNKNOWN`** | Launch route only |
| Boosted Handheld | Ally panel | eGPU | *none* | **No** | `BOOSTED_HANDHELD` | **Unrepresentable** |

### Authority, per layer

| Layer | Portable | Docked-eGPU | Docked-iGPU | Boosted Handheld |
|---|---|---|---|---|
| `GamescopeLaunchConfig.target` (`gamescope_wrapper.py:46`) | yes | yes | yes | **no** |
| `PresentationConfigStore.build_target` (`presentation_config.py:119`,`:125`,`:136`) | yes | yes | yes | **raises** `presentation target is unsupported` |
| Shim `select_launch_configuration` (`gamescope_wrapper.py:163`) | yes | yes | yes (TV branch, plus an internal-panel fallback branch) | **no** |
| `TransitionStepCode` (`control_plane.py:89`) | `presentation.restore_portable` | `presentation.apply_docked_egpu` | **no step code** | **no step code** |
| `plan_manual_transition` target (`manual_transition.py:186`) | yes | yes | `placement.target_unsupported` | `placement.target_unsupported` |
| `plan_manual_transition` **source** (`manual_transition.py:192`) | yes | yes | yes | `placement.path_unsupported` |
| `SupervisedTransitionService.preview` (`supervised_transition.py:123`) | yes | yes | `placement.target_unsupported` | `placement.target_unsupported` |
| `PresentationTransition.apply` (`presentation_transition.py:116`) | yes | yes | `presentation.step_unsupported` | `presentation.step_unsupported` |
| `PresentationTransition.recover` source (`presentation_transition.py:146`) | yes | yes | **yes** | `recovery.target_unsupported` |
| Decky RPC | `PORTABLE`, hard-coded (`main.py:1811`,`:1831`) | `DOCKED_EGPU`, hard-coded (`main.py:1683`,`:1707`,`:1727`) | **none** | **none** |
| Audio handoff target (`adapters/steamos/audio_handoff.py:216`) | restore | yes | yes | **no** |

Docked-iGPU is therefore reachable today **only as the restore of a placement
already observed**: `recover()` is called with `plan.from_placement`
(`application/transition_orchestrator.py:387`,`:513`), so a `docked_igpu`
configuration can be written only when a plan that *started* in Docked-iGPU
failed. There is no forward path into it, and a boot-scoped configuration never
survives a reboot, so a device cannot arrive there on its own either.

### Capability vocabulary cannot express the difference

`EffectiveCapabilities` has a single `display_handoff` axis
(`control_plane.py:184`). For the certified pair it composes to
**Experimental**: the Ally X host declares
`display_handoff=EXPERIMENTAL` (`profiles/ally_x.py`), the GPD G1 declares
`display_output=VERIFIED` (`profiles/gpd_g1.py`), and `combine_capability`
(`control_plane.py:287`) keeps the conservative value. Consequences:

- Every mutating display transition needs the explicit, single-use,
  two-minute experimental permit ([`EXPERIMENTAL_TRANSITIONS.md`](EXPERIMENTAL_TRANSITIONS.md)).
- There is **no separate capability** for "display-only move", for "render
  handoff", or for "internal GPU scanning out through the eGPU's connector".
  They are different mechanisms with different hardware risk, and today one flag
  covers all of them. Splitting that axis is a shared-contract change; it is
  proposed below, not made here.

## Where a game close and relaunch is REQUIRED

**Explicit statement: every change in this matrix requires closing the running
game first. There is no display-only path that preserves a running game, and
Re-Gear must not offer one.**

The distinction that matters is what the relaunched game lands on:

| From → To | Display moves | Renderer moves | Game close required | Relaunched game's GPU |
|---|---|---|---|---|
| Portable → Docked-eGPU | yes | yes | **yes** | **different** (eGPU) |
| Docked-eGPU → Portable | yes | yes | **yes** | **different** (internal) |
| Portable → Docked-iGPU | yes | no | **yes** | same (internal) |
| Docked-iGPU → Portable | yes | no | **yes** | same (internal) |
| Docked-eGPU → Boosted Handheld | yes | no | **yes** | same (eGPU) |
| Boosted Handheld → Docked-eGPU | yes | no | **yes** | same (eGPU) |
| Docked-eGPU → Docked-iGPU | no | **yes** | **yes** | **different** (internal) |
| Docked-iGPU → Docked-eGPU | no | **yes** | **yes** | **different** (eGPU) |
| any → itself | no | no | no (verified no-op) | unchanged |

Reading of the two requests against that table:

- **(a) as literally stated is not achievable.** "Same render GPU, same running
  game, display moves" has no supported route: the move is a Gamescope restart
  and the restart ends the game. What *is* achievable is "same render GPU, game
  closed and relaunched, display moved" — the game returns on the same GPU.
  Re-Gear must say that plainly rather than implying the session survives.
- **(b) is a render handoff when entered from Docked-eGPU** and therefore
  changes which GPU runs the game. Entered from Portable it is a display move
  that keeps the internal renderer. Either way the game closes first.
- **Re-Gear never migrates a running workload between GPUs** (invariant 1). The
  close/relaunch is exactly what keeps that true: the old workload ends before
  the new GPU selection takes effect. Any wording that suggests a game "moves"
  to the other GPU is wrong.
- The existing running-game guard stays. This record removes nothing, and the
  guard must not be blanket-removed to make any of these paths reachable.

## Refusal behaviour

### Already implemented, and to be preserved

| Condition | Code | Where |
|---|---|---|
| Current placement Unknown/Degraded | `placement.current_unverified` | `manual_transition.py:184` |
| Destination not a supported placement | `placement.target_unsupported` | `manual_transition.py:186`, `supervised_transition.py:123` |
| Source placement unsupported as a path | `placement.path_unsupported` | `manual_transition.py:192` |
| Host DMI not the exact certified tuple | `identity.host_unverified` | `manual_transition.py:194` |
| eGPU profile or stable identity missing | `identity.egpu_unverified` | `manual_transition.py:242` |
| Any binding identity missing | `identity.transition_binding_incomplete` | `manual_transition.py:255` |
| Game running | `game.running` | `manual_transition.py:233` |
| Game state unknown | `game.state_unknown` | `manual_transition.py:231` |
| Capability not Verified and no matching permit | `capability.display_handoff_unverified` | `manual_transition.py:229` |
| External display not connected with EDID ready | `display.external_unready` | `manual_transition.py:244` |
| No verified rollback to the source placement | `recovery.source_unverified` | `manual_transition.py:235` |
| Mechanism step code not mapped | `presentation.step_unsupported` | `presentation_transition.py:126` |
| Binding changed between plan and attempt | `presentation.binding_changed` | `presentation_transition.py:169` |
| Shim: stale boot, ambiguous connector, or absent vendor/device | selects a unique internal panel, otherwise preserves existing argv and clears the eGPU selector | `gamescope_wrapper.py:163`-`216` |

That shim fallback is the last line: if a `docked_igpu` or `docked_egpu`
configuration cannot be matched against the current boot, a uniquely connected
external connector, a uniquely present vendor/device pair, and a freshly
re-resolved verified eGPU binding, the session comes up on the internal panel
instead of guessing. Unknown topology therefore degrades to the Ally screen, not
to a black TV.

### Required additions for either request

These are refusals that do not exist yet and must exist before a Docked-iGPU or
Boosted Handheld destination is offered:

1. **Connector ownership is unknown — fail closed.** The domain cannot currently
   tell which GPU owns an external connector. `DrmConnectorRecord` records
   `card` (`adapters/steamos/drm.py:57`), but `DisplayObservation`
   (`domain/models.py:119`) has no owning-GPU field, and `_display_stable_id`
   (`adapters/steamos/discovery.py:85`) derives identity from the EDID hash
   whenever EDID is present, so the card is dropped for every real TV.
   `infer_placement` classifies Docked-iGPU from "internal renderer + external
   display" regardless of which card that display hangs off. A request to drive
   the TV from the internal GPU is a cross-device request; making it without
   knowing that the TV is on the eGPU's connector is exactly the kind of guess
   the invariants forbid. Any new field must bind the connector to the owning
   GPU's **stable identity**, never to `cardN` (invariant 5).
2. **No usable connector, no TV.** Docked-iGPU and Docked-eGPU both require the
   external connector connected with EDID ready and verified; absence is a
   refusal, never a "the TV will come up" promise. The existing
   `display.external_unready` covers this and must be retained for any new
   destination.
3. **eGPU absent — Docked-iGPU is unavailable, not "internal-only TV".** The
   current representation structurally binds Docked-iGPU to an attached verified
   eGPU: `build_target` hashes `binding.egpu_stable_id` into the config
   (`presentation_config.py:136`-`146`), `TransitionBinding` requires every
   identity (`control_plane.py:106`), and the shim requires the verified G1
   binding to honour a `docked_igpu` config. A TV attached to the host rather
   than to the eGPU is **not** represented anywhere and must not be inferred.
4. **No public mode — no silent Unknown.** A player in Docked-iGPU is shown
   `OperatingMode.UNKNOWN` today, because `infer_operating_mode` has no
   internal-renderer/external-display case (`inference.py:104`-`113`, reason
   string at `:113`). Offering the destination without adding the mode would
   present a working TV as an unknown state, and Unknown evidence is Attention
   Required in the health aggregate. The mode vocabulary is a shared contract:
   proposed, not changed here.

## Known blockers

| Blocker | Effect | Owner |
|---|---|---|
| [#167](https://github.com/ronnierosal/Re-Gear/issues/167) — the managed `gamescope-session` drop-in still names the pre-rename plugin directory, `status()` reports `managed_dropin_modified`, and `activate()` refuses any non-empty error code | "Display switching ready" never leaves Checking on installed builds, `connection_readiness` is parked at `waiting_for_session`, and **no** display transition in this matrix can run on the affected device | hub task `egpu-dropin-rename-migration`, unclaimed — not this task |
| Connector→owning-GPU evidence absent | Cross-device Docked-iGPU cannot be verified; see required addition 1 | proposal below |
| `OperatingMode` has no Docked-iGPU | A working internal-GPU TV would read as Unknown | proposal below |
| Docked-iGPU hardware gates open ([`DOCKED_IGPU.md`](DOCKED_IGPU.md)) | "prove on hardware that a running iGPU game can be presented on the TV through the G1" is unproven; so is Docked-iGPU rollback | certification gate |
| Last supervised TV-switch attempt did not reach the TV ([`EXPERIMENTAL_TRANSITIONS.md`](EXPERIMENTAL_TRANSITIONS.md)) | The corrected candidate still needs a fresh watched idle attempt; the existing Docked-eGPU path is not hardware-passed | certification gate |

## Proposed implementation slices

Ordered, each independently reviewable. **Slice 0 is the only one done in this
task.** Slices 1-5 touch shared transition contracts and must be sequenced by
the integration owner with their current owners; they are proposals, not
decisions, and none of them may be taken as authorization to widen display
mutation authority.

| # | Slice | Touches | Feasible now? |
|---|---|---|---|
| 0 | **Done here.** Pure `display_render_modes` classifier plus planner-agreement tests: one vocabulary for display-move vs render-handoff, and the executable matrix | new pure domain module + tests | yes |
| 1 | Record the owning GPU's stable identity on `DisplayObservation` and surface it through discovery; keep `cardN` out of identity | `domain/models.py`, `adapters/steamos/discovery.py`, serialization, fixtures | yes, but shared contract |
| 2 | Add `OperatingMode.DOCKED_IGPU` and the `inference` case, plus health/UI copy | `domain/models.py`, `domain/inference.py`, payload contract tests | yes, but shared contract and player-visible |
| 3 | Split `display_handoff` into display-move and render-handoff capability axes so Docked-iGPU cannot inherit Docked-eGPU's evidence | `domain/control_plane.py`, profiles | shared contract; needs a milestone decision |
| 4 | Add `TransitionStepCode.PRESENTATION_APPLY_DOCKED_IGPU`, the planner destination, the `supervised_transition` destination, and the mechanism mapping — gated on slices 1-3 and on the #167 fix | `control_plane.py`, `manual_transition.py`, `supervised_transition.py`, `adapters/presentation_transition.py` | only after 1-3 |
| 5 | Boosted Handheld (eGPU → Ally panel, the purest form of request (a)) needs a **new** launch-config target that pairs the internal connector with the eGPU vendor/device, which the config currently rejects outright (`gamescope_wrapper.py:60`-`65`) | `gamescope_wrapper.py`, `presentation_config.py`, plus 1-4 | no; new mechanism and new hardware evidence |

Explicitly **not** proposed: a live GPU migration path, a runtime output-switch
API, removal of the running-game guard, or a frontend-supplied placement target.

## Rollback plan

Every slice above inherits the existing rollback, and no slice may ship without
it:

1. **Configuration rollback.** A failed attempt restores the configuration for
   the still-observed current placement
   (`presentation_transition.py:268` `_restore_current_config`); a failed
   restore is reported separately as `*.config_rollback_failed`.
2. **Placement rollback.** The orchestrator recovers to `plan.from_placement`
   and must verify a fresh observation before calling recovery successful
   (`transition_orchestrator.py:387`,`:513`). Docked-iGPU is already an accepted
   recovery source (`presentation_transition.py:146`).
3. **Shim-level rollback.** Stale or ambiguous evidence selects the internal
   panel and clears the eGPU selector, so a bad configuration degrades to the
   Ally screen rather than to no picture.
4. **Durable journal.** Interrupted attempts terminalize as Action Required and
   are never resumed automatically; a terminal result must be acknowledged
   before another attempt.
5. **Feature rollback.** Slices 2 and 4 are player-visible; each must be
   revertible on its own commit, and slice 4 must remain behind the existing
   Experimental permit so disabling the capability removes the destination
   without touching observation.
6. **Docked-iGPU rollback is itself an open gate** ([`DOCKED_IGPU.md`](DOCKED_IGPU.md)
   "verify Docked-iGPU rollback before enabling any automatic trigger"). No
   automatic trigger for any destination in this matrix.

## Test plan

**Software verification and supervised hardware validation are separate, and
neither substitutes for the other.** A passing local suite is not installed
proof, and an installed build is not hardware proof.

### Software verification (local, deterministic)

| Area | Check | State |
|---|---|---|
| Matrix vocabulary | `tests/test_display_render_modes.py` — every placement described, axes match `infer_placement`, public mode matches `infer_operating_mode`, launch targets match `GamescopeLaunchConfig`, Boosted Handheld unrepresentable | **Added, passing** |
| Planner agreement | The described `planner_target` flag equals the real planner's `placement.target_unsupported` behaviour, for all four placements | **Added, passing** |
| Game-close rule | Every non-no-op change reports `game_close_required`; no-op reports none | **Added, passing** |
| Fail-closed | Unknown/Degraded source and Unknown target refuse; unknown game state refuses | **Added, passing** |
| Slice 1 | Fixtures where the external connector is owned by the internal GPU vs the eGPU produce different evidence, and a missing owner refuses | proposed |
| Slice 2 | Payload contract test: a Docked-iGPU snapshot reports the new mode and not `UNKNOWN` | proposed |
| Slice 4 | Planner/facade/mechanism round trip for a Docked-iGPU destination, including permit binding, step-code mapping, and failure-injected rollback to the source | proposed |
| Regression | No change weakens `game.running`, `game.state_unknown`, identity or capability refusals | required for every slice |

### Supervised hardware validation (separate, gated)

Not performed by this task, and not authorized by it. For the record, a
Docked-iGPU destination would need, on a supported profile, with redacted
before/attempt/after evidence and a watched idle session:

1. #167 resolved on the installed build, so "Display switching ready" actually
   becomes ready.
2. Proof that the TV's connector is owned by the eGPU and that the internal GPU
   can scan out through it at all — the open gate in
   [`DOCKED_IGPU.md`](DOCKED_IGPU.md).
3. A Support Preview DRM engine-activity comparison showing internal activity
   and no eGPU activity for the game in that placement, with either Unknown
   result treated as incomplete.
4. Verified rollback from a failed Docked-iGPU attempt to the observed source.
5. Re-verification that the existing Docked-eGPU path still passes, since both
   share one mechanism.

Hardware gates #147, #161 and #201 remain open and are untouched by this record.

## Cross-document corrections to route, not to make

- [`PRODUCT.md`](PRODUCT.md) describes Docked-iGPU as "the current game remains
  on the internal GPU while its presentation is verified on the external
  display". That is accurate about the end state and easy to misread as a live
  handoff of a running game. Suggested clarification: the game remains on the
  internal GPU **across the relaunch**; entering the placement still restarts
  Gamescope. `PRODUCT.md` is product-scope authority, so this is a proposal for
  its owner.
- `TV Docked` in the executable label set corresponds only to Docked-eGPU
  ([`PRODUCT.md`](PRODUCT.md)); a Docked-iGPU destination must not reuse it.

Documentation impact: Wiki
