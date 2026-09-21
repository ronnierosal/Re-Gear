# Re-Gear Command Center artwork v1

Visual source of truth: the approved rich FPS/widget mockup language from September 2026.

## Production assets

- `tile-artwork.svg` — **primary rich tile artwork**, one full-tile symbol per control/widget: `#tile-fps`, `#tile-battery`, `#tile-egpu`, etc. This is what the Command Center grid should use.
- `button-artwork.svg` — lightweight icon/fallback sprite for compact navigation, utility rails, and cases where full artwork is inappropriate.
- `INVENTORY.md` — asset inventory.
- `button-catalog.md` — domain/type/tab metadata.
- `dynamic-overlays.md` — live-data overlay contract.

## Architecture

Static artwork and dynamic information are deliberately separate.

The rich tile artwork contains the visual atmosphere: dark glass/HUD background, glow, facet texture, and feature illustration. It intentionally contains **no live number, state, or label**.

React/CSS/SVG renders changing information above it:
- FPS and target
- battery percentage and estimate
- controller battery/player
- eGPU state/GPU identity
- resolution/refresh
- TDP watts
- storage free space
- temperatures/fan/load/power/frame time
- focus, availability, jiggle, and animated gauges

Never bake live data into artwork.

## Tile IDs

Every inventory ID has a rich tile counterpart. Example:

```tsx
<svg viewBox="0 0 180 180" aria-hidden="true">
  <use href="/assets/command-center/tile-artwork.svg#tile-fps" />
</svg>
```

The lightweight icon counterpart is `button-artwork.svg#fps`.

## Animation

Gauge fills are live overlays, not artwork.
Use ~200–300 ms easing between readings. No continuous decorative animation.
Respect reduced motion.

## Truthfulness

Unknown stays Unknown. Unavailable stays Unavailable. Never fabricate live values.
