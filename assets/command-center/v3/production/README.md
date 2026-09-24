# Re-Gear Command Center V3 production artwork

Status: **APPROVED** by the project owner on 2026-09-22.

The 37 numbered SVG files in this directory are the approved production visual
family. `01_fps.svg` is the master shell for the shared surface, rim, glow,
angular HUD geometry, lighting, artwork zone, and quiet live-data zone.

Each SVG is a self-contained 240×144 static layer. React owns labels, values,
live progress, focus, and availability. Do not bake live text into these files,
replace them with the older lightweight fallback symbols, or add another visual
veil over the artwork.

`10_safe-disconnect.svg`, `11_disconnect-sleep.svg` and
`12_disconnect-shutdown.svg` were redrawn to match the review sheet more
closely (dark halo, braided USB-C plug, glowing crescent and power glyph) and
approved by the project owner on 2026-09-24. See
[`docs/design/command-center/proposals/disconnect-sleep-mockup.png`](../../../../docs/design/command-center/proposals/disconnect-sleep-mockup.png)
for the before/after comparison.

The immutable review reference remains
[`../APPROVED-BUTTON-ASSETS-V3.jpg`](../APPROVED-BUTTON-ASSETS-V3.jpg).
