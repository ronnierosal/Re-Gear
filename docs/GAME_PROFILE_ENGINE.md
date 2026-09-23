# Game Profile Engine

Status: implementation slice on top of the accepted graphics-profile foundation
([architecture](GRAPHICS_PROFILES_ARCHITECTURE.md), PR #375 at `9d48d61`).
Fixture-only: no real game is supported, and nothing is wired to a caller.
Coordination record: issue #374.

## What it does

The player picks an experience; the engine turns it into game settings.

    Steam game  +  Re-Gear mode  +  preference (and, later, a performance plan)
        ->  validated game configuration, or honest advice

The player never chooses shadows, textures or render scale. A profile says
what the player gets in words; a per-game mapping says how that game spells it.

## Architecture

```
                 supplied by owners                    Codex's resolver (future)
   ┌────────────────────────────────────┐         ┌──────────────────────────┐
   │ AppID · OperatingMode · run state  │         │ PerformancePlan          │
   │ observed game version · preference │         │ display/base FPS, res,   │
   └─────────────────┬──────────────────┘         │ upscaling, FG ref (opaque)│
                     │                            └────────────┬─────────────┘
                     ▼                                         │ apply_to()
   ┌──────────────────────────────────────────────────────────▼──────────────┐
   │ GAME PROFILE ENGINE  delivery/game_profile_engine.py                   │
   │                                                                        │
   │  ProfileRegistry ── GameProfileDocument ── SemanticProfile (per mode × │
   │                     │  metadata: profile/adapter    preference)        │
   │                     │  version, tested game version, validation        │
   │                     ▼                                                  │
   │  decide_support() ── GameMapping (per game, versioned) ── translate()  │
   │     │                   "textures=high" -> sg.TextureQuality=2         │
   │     ├── Level 0 UNKNOWN  → nothing                                     │
   │     ├── Level 1 ADVISOR  → plain-language recommendations              │
   │     └── Level 2 MANAGED  → GraphicsProfile (exact keys)                │
   └─────────────────────────────────────┬──────────────────────────────────┘
                                         ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ACCEPTED FOUNDATION (unchanged)                                        │
   │ ConfigLocator → schema check → provenance → backup → atomic write →    │
   │ verify → Restore My Settings / Stop Managing                           │
   └────────────────────────────────────────────────────────────────────────┘
```

## Three concepts kept apart

| Concept | Owner | Knows |
| --- | --- | --- |
| Player intent | the player | an experience: mode + preference, later an FPS target |
| Game Profile Engine | this slice | which game settings deliver that, for this game |
| Performance providers | Codex (#379, #381) | how frames are produced: native, upscaled, generated |

The engine imports nothing from the provider side. A `PerformancePlan`
(`domain/performance_plan.py`) is the whole handover, and it names frame
generation only as an opaque `FrameGenerationRef` that the engine passes
through untouched. From a plan the engine takes resolution, upscaling, and one
number that matters most: the **base FPS target, which becomes the game's own
frame cap**. With 2x frame generation to 60, the game is capped at 30 real
frames; the provider, not the engine, produces the rest.

## Format versus game mapping

* **Format** (`graphics_config_format`, foundation) — how a file is parsed and
  rendered, byte-exact.
* **Mapping** (`GameMapping`) — how *one game* at *one adapter version* spells
  each setting. Two Unreal games share a format and can disagree on every key
  and value; a game patch can keep the file and change the meaning. So
  mappings are per game and versioned, never "all Unreal games".

## Support levels

| Level | When | Result |
| --- | --- | --- |
| 0 Unknown | no profile for this game or this mode/preference | nothing |
| 1 Advisor | a profile exists, but anything below fails | recommendations, nothing written |
| 2 Managed | every check passes | the foundation applies it |

Managed requires **all** of: a mapping for the game; matching adapter
version; the mapping can express **every** setting in the profile; the
installed game version equals the tested one; validation status VALIDATED
(FIXTURE only with an explicit test opt-in); and, at apply time, the file
still matches its schema and is not read-only. Every failing reason is
reported, not just the first. A game update or schema change therefore
falls back from Managed to Advisor on its own — the engine never guesses.

## Player overrides, backup and restore

Inherited unchanged from the foundation. The foundation records the digest of
exactly what Re-Gear last wrote; if the file no longer matches, the player
changed it and the result is `CONFLICT`, never an overwrite. The first write
pins the original; Restore My Settings returns it byte-for-byte and reports
whether that is provably the enrolled original. Stop Managing ends authorship
without touching the file.

Read-only configurations are respected at the engine level: an atomic replace
would succeed anyway, but players lock files precisely to stop changes, so a
locked file gets advice instead.

## Running games

A running or ambiguous game is never reconfigured. A mode change during play
returns `QUEUED_NEXT_LAUNCH` with a `NextLaunchRequest`: the request, not a
precomputed plan. Automatic optimization (below) keeps no copy of that
request. Its lifecycle is per game and mode, so the next launch uses the
freshly observed mode's own lane. A replayed request would be stale by
construction.

## Automatic optimization

Status: fixture-only, with no runtime caller. The design direction is the
[automatic game optimization architecture](https://github.com/ronnierosal/Re-Gear/pull/388),
which is still a proposal.

| Piece | Module | What it holds |
| --- | --- | --- |
| Intent | `domain/game_optimization_preferences.py` | Global master switch (default **off**); per game `inherit` / `automatic` / `manual` and preference |
| Lifecycle | `domain/game_optimization_state.py` | Per game × mode: `BASELINE → LEARNING → TESTING_PROFILE → VALIDATING → OPTIMIZED_LOCKED`, with `NEEDS_REVALIDATION`, `USER_OVERRIDE`, `OPTIMIZATION_DISABLED`, `ADVISOR_ONLY` and `UNSUPPORTED` |
| Store | `delivery/game_optimization_store.py` | Atomic, revisioned, bounded records; absent, untrusted and loaded kept distinct |
| Catalog | `delivery/game_profile_catalog.py` | Data-only profile entries with provenance, pointing at reviewed in-code mappings |
| Service | `delivery/game_optimization_service.py` | `prepare_launch` and the inputs that feed the lifecycle |

The service adds no writer. Every file operation goes through the engine and
the foundation above, including backups, the player-edit conflict check and
Restore My Settings. The service decides only whether this launch asks the
engine for anything, and for what: the staged candidate, the accepted plan,
or the player's original.

**Rules the tests hold it to**

- **Opt-in.** Nothing stored means off. Global off cancels pending work in
  every lane at once, and writes and restores nothing. Per-game `manual` does
  the same for one game.
- **Between launches only.** A candidate is staged, then written at the next
  idle launch. A running game defers it. Nothing is written during play.
- **Uncertain is never success.** Unqualified or inconclusive windows move
  nothing toward acceptance. Running out of validation windows counts as
  rejection. A rejected candidate is replaced by the original at the next
  launch, byte for byte.
- **Bounded.** There is a fixed number of learning windows, validation
  windows and attempts per context, plus a bounded history. When the attempt
  budget is spent, the lifecycle stops proposing.
- **The player wins.** While validating or locked, each launch checks the
  plan through the engine. A player edit is a `CONFLICT`: the lifecycle moves
  to `USER_OVERRIDE`, the edit stays, and nothing is written until the player
  hands the game back. Even then the engine's conflict rule still decides.
- **Context.** A change to the game version, profile version, adapter
  version, schema or preference invalidates the evidence. The accepted plan
  is kept as history and reapplied only in the context it was accepted under.
- **Crashes.** A write is durably marked in flight before it starts. If that
  mark cannot be saved, nothing is written. A lane reopened with the mark
  still set records the attempt as uncertain and never replays it.
- **Corruption.** An untrusted preferences file or lifecycle record withholds
  automatic management. It never falls back to a default. Only an explicit
  reset moves it aside, and nothing is deleted outright.

**Catalog admission.** A catalog entry carries no paths, keys or commands, and
unknown fields are refused. A `validated` claim is admitted only when all of
these hold:

- the source is local or Re-Gear-reviewed;
- it names its evidence;
- the evidence covers the requested mode.

Otherwise the claim is lowered to unvalidated, which means Advisor. Community
entries are candidates, never authority.

**Boundaries.** Window verdicts (`meets_target`, `below_target`,
`inconclusive`, and whether a window is qualified) and candidate plans arrive
from outside. This slice has no collector, resolver policy, Auto TDP control,
launch hook or UI. `LearningPolicy` values are unreviewed placeholders
(`policy_version` 0). The resolver owner sets the real ones. The
`PerformancePlan` contract is unchanged (v1). A proposal separating internal
render, game output and display resolution, and requested from selected FPS,
is with the primary, and nothing here depends on it.

## Not in this slice

Real game mappings or evidence; mode, run-state or game-version wiring (all
supplied by the caller); reading the Steam build ID (supplied); a telemetry
collector, launch hook or runtime caller for automatic optimization; UI; LSFG
or any provider.

Documentation impact: none (internal, fixture-only).
