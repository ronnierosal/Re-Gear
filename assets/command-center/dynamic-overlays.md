# Dynamic overlay specification

## FPS
Artwork: `#fps`
Primary: current FPS
Secondary: target FPS
Gauge: clamp(current / target, 0..1) when target is known; otherwise optional normalized live meter only if runtime provides a meaningful scale.
Unknown: primary "—", dim gauge.

## Battery
Artwork: `#battery`
Primary: battery %
Secondary: estimated remaining time only when supported by a trustworthy runtime estimate.
Gauge: battery percent.
Charging state may add a small charging glyph; do not replace the artwork.

## Controller
Artwork: `#controller`
Primary: battery %
Secondary: P1/P2/etc when actually known.
Unknown player assignment must not be inferred.

## eGPU
Artwork: `#egpu`
Primary: Connected / Detecting / Unknown / Unavailable
Secondary: verified GPU short name when available.
No fake model name.

## Display / Resolution / Refresh
Artwork: `#display`, `#resolution`, `#refresh-rate`
Primary/secondary: current verified resolution and refresh rate.
Display target may show Handheld / TV / Both / Unknown.

## Performance / TDP
Artwork: `#performance`, `#manual-tdp`, `#auto-tdp`
Primary: profile / watts / Auto TDP state.
Secondary only when it materially helps.

## Storage
Artwork: `#storage`
Primary: free space.
Secondary: optional total/used value.
Gauge may represent used capacity.

## Wi-Fi / Mic / Record
Artwork: `#wifi`, `#mic`, `#record`
Use short state overlays only: Connected, Muted, Recording, etc.

## Action buttons
`#handheld`, `#safe-disconnect`, `#disconnect-sleep`, `#disconnect-shutdown`
No live gauge. Use artwork + short action label. Optional tiny readiness state only.
