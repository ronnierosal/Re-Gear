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
returns `QUEUED_NEXT_LAUNCH` with a `NextLaunchRequest` — the request, not a
precomputed plan, so it is resolved afresh against the context at next launch.
Persisting that request is not yet implemented.

## Not in this slice

Real game mappings or evidence; persistence of profiles, preferences and
queued requests; mode, run-state or game-version wiring (all supplied by the
caller); reading the Steam build ID (supplied); UI; LSFG or any provider.

Documentation impact: none (internal, fixture-only).
