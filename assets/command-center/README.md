# Re-Gear Command Center artwork v1

Visual direction approved from the September 19, 2026 Ally UI review.

## Architecture
Static artwork and dynamic information are deliberately separate.

- Static/action tiles use artwork from `button-artwork.svg`.
- Dynamic tiles use the same artwork layer plus live React/SVG/CSS overlays.
- Never bake FPS, battery %, controller %, resolution, storage free space, or other changing values into PNG/SVG artwork.
- All tiles use the same outer card geometry. The sprite contains artwork only; the Command Center component owns border/focus/state/labels.

## Sprite IDs
fps, battery, controller, egpu, display, performance, manual-tdp, auto-tdp,
handheld, safe-disconnect, disconnect-sleep, disconnect-shutdown, resolution,
refresh-rate, storage, wifi, mic, record, brightness, volume.

## Dynamic overlay examples
- FPS: current FPS, target FPS, animated gauge arc.
- Battery: %, estimated time when supported.
- Controller: battery %, player assignment.
- eGPU: connection state / GPU identity when verified.
- Display: resolution + refresh.
- Manual TDP: current watts.
- Auto TDP: enabled/running state.
- Storage: free space.
- Brightness/Volume: percentage in utility rail.

## Animation
Gauge fills are live SVG/CSS overlays, not part of the artwork.
Use a short ~200–300 ms ease between verified readings. No continuous spinning.
Respect reduced motion.

## Truthfulness
Unknown stays Unknown. Unavailable stays Unavailable. Do not fabricate live values.
