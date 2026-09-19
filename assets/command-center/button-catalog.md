# Re-Gear Command Center button catalog v1

All production buttons use artwork from `button-artwork.svg`. Live values are overlays, never baked into artwork.

| ID | Domain | Type | Presentation | Native tab | Quick Access | Right rail | Live overlay |
|---|---|---|---|---|---|---|---|
| fps | performance | widget | dynamic | Performance | yes | no | FPS, target, gauge |
| performance | performance | navigation/status | dynamic | Performance | yes | no | profile |
| manual-tdp | performance | slider/status | dynamic | Performance | yes | no | watts |
| auto-tdp | performance | toggle/status | dynamic | Performance | yes | no | state |
| resolution | display | navigation/status | dynamic | Performance/eGPU context | yes | no | resolution |
| refresh-rate | display | navigation/status | dynamic | Performance | yes | no | Hz |
| battery | battery | widget | dynamic | Quick Access | yes | no | %, estimate, charging |
| controller | controller | widget/status | dynamic | Controllers | yes | no | battery, P# |
| egpu | egpu | widget/status | dynamic | eGPU | yes | no | connection, GPU |
| display | display | widget/status | dynamic | eGPU/Quick Access | yes | no | target, resolution, Hz |
| handheld | egpu | action | static | eGPU | yes | no | availability only |
| safe-disconnect | egpu | action | static | eGPU | yes | no | readiness only |
| disconnect-sleep | egpu/power | action | static | eGPU | yes | no | availability only |
| disconnect-shutdown | egpu/power | action | static | eGPU | yes | no | availability only |
| storage | storage | widget | dynamic | Quick Access | yes | no | free space |
| wifi | network | toggle/status | dynamic | Quick Access | yes | yes | state |
| mic | system | toggle | static/dynamic | Quick Access | yes | yes | muted state |
| record | system | action/status | static/dynamic | Quick Access | yes | yes | recording state |
| brightness | display | slider | utility | Quick Access rail | no | no | % |
| volume | system | slider | utility | Quick Access rail | no | no | % |

## Tile rules

- One geometry for every grid tile; no 2-cell-wide exceptions.
- Preferred grid is 5 columns when the actual viewport supports readable labels.
- Static actions emphasize artwork + short label. Direct actions do not show chevrons.
- Dynamic tiles use artwork + primary live value + optional secondary value.
- Unknown and Unavailable are legitimate states.
- Dynamic gauges are SVG/CSS overlays. 200–300 ms easing; reduced-motion disables interpolation.
- No continuous decorative animation during gameplay.
- Quick Access replacement picker groups by domain.
