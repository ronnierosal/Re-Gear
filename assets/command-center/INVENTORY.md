# Re-Gear artwork inventory

Production SVG sprite: `button-artwork.svg`

## Core controls
- fps
- battery
- controller
- egpu
- display
- performance
- manual-tdp
- auto-tdp
- handheld
- safe-disconnect
- disconnect-sleep
- disconnect-shutdown
- resolution
- refresh-rate
- storage
- wifi
- mic
- record
- brightness
- volume

## Extended widgets / controls
- offline-ready
- charging
- temperature
- fan
- network
- game-ready
- player-order
- audio-output
- gpu-load
- power-draw
- frametime
- memory
- clock
- quick-access
- settings
- about
- more

## Usage
Render an individual symbol with:

```tsx
<svg viewBox="0 0 64 64" aria-hidden="true">
  <use href="/assets/command-center/button-artwork.svg#fps" />
</svg>
```

If the Decky bundler does not support external `<use>` references, import/inject the sprite once and reference local fragment IDs. Do not convert the sprite to raster unless the runtime forces it.

## Dynamic vs static
Dynamic widgets: fps, battery, controller, egpu, display, performance, manual-tdp, auto-tdp, resolution, refresh-rate, storage, wifi, offline-ready, charging, temperature, fan, network, game-ready, player-order, audio-output, gpu-load, power-draw, frametime, memory, clock.

Static/direct actions: handheld, safe-disconnect, disconnect-sleep, disconnect-shutdown, mic, record, quick-access, settings, about, more.

Brightness and volume are utility-rail artwork and retain live percentage overlays.

## Design rule
The sprite is the artwork layer only. Card chrome, labels, live values, focus, jiggle, gauges, availability, and animations are rendered by the UI.
