# Re-Gear Command Center V3 — APPROVED VISUAL SOURCE OF TRUTH

Status: APPROVED by project owner on 2026-09-21.

This supersedes the rejected V2 experiment from PR #362.

## Canonical visual reference

[`APPROVED-BUTTON-ASSETS-V3.jpg`](APPROVED-BUTTON-ASSETS-V3.jpg) is the exact
project-owner-supplied V3 review sheet. Its SHA-256 is
`7a8c0c5fea0bccd5d4207e9741c76d25eaf1b2a0bf9d0e5774fba866da2326a4`.

Treat that image as immutable visual acceptance evidence. Do not redraw,
reinterpret, simplify, substitute, recolor, or add another veil over its tile
artwork. The individual production assets must visibly match the corresponding
numbered tile in this sheet at the Ally viewport.

The older files under `tiles/` are implementation candidates, not proof of a
visual match. Several use symbols from the lightweight `button-artwork.svg`
fallback set.

The 37 numbered, self-contained SVGs under `production/` were visually approved
by the project owner on 2026-09-22 (tiles 10, 11 and 12 re-approved after a
sheet-matching redraw on 2026-09-24; tiles 02–09 and 13–37 refitted to the
sheet on the owner's request the same day). They are the production artwork family for
subsequent UI integration. Installed Ally acceptance remains a separate gate.

## Locked presentation

- 240×144 landscape tile composition.
- Dark navy / glass / cyan Re-Gear visual language.
- Five-column Command Center target.
- Left side of each tile is reserved for React-rendered label and live values.
- Right side contains the feature illustration.
- Static artwork must never bake in changing values or states.
- Dynamic FPS, watts, battery %, controller %, resolution, refresh, storage, temperature, fan, power, readiness, etc. are rendered by React/SVG/CSS above the artwork.
- Rich illustrations should visually match the approved V3 review sheet, not the simple V2 line-icon treatment.
- All top-level tiles share the same outer geometry.
- Direct action tiles and dynamic widget tiles use the same card footprint.

## Approved 37 asset IDs

fps
battery
controller
egpu
display
performance
manual-tdp
auto-tdp
handheld
safe-disconnect
disconnect-sleep
disconnect-shutdown
resolution
refresh-rate
storage
wifi
mic
record
brightness
volume
offline-ready
charging
temperature
fan
network
game-ready
player-order
audio-output
gpu-load
power-draw
frametime
memory
clock
quick-access
settings
about
more

## Implementation rule

Do not use PR #362 assets as the production presentation.

The checked-in approved V3 review sheet is the visual reference. Production artwork should be exported as clean per-tile assets (no sample text/value baked in), then wired through the control registry.

Codex should implement one representative dynamic tile (FPS) and one direct action (Safe Disconnect) first, validate on Ally, then roll the component across the remaining registry.
