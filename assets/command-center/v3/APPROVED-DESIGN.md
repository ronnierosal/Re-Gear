# Re-Gear Command Center V3 — APPROVED VISUAL SOURCE OF TRUTH

Status: APPROVED by project owner on 2026-09-21.

This supersedes the rejected V2 experiment from PR #362.

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

The approved V3 PNG review sheet is the visual reference. Production artwork should be exported as clean per-tile assets (no sample text/value baked in), then wired through the control registry.

Codex should implement one representative dynamic tile (FPS) and one direct action (Safe Disconnect) first, validate on Ally, then roll the component across the remaining registry.
