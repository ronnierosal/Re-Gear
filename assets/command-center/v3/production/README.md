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

The remaining tiles (02–09, 13–37) were refitted to the review sheet on
2026-09-24 at the owner's request: dark halo and circuit traces replace the
flat colour orb, each illustration is re-centred and scaled to sit fully
inside the artwork zone (no right-edge clipping), and a soft bloom in the
tile's own colour is added. Controller, temperature, frametime and more were
also redrawn where their drawing differed from the sheet. `01_fps.svg` keeps
its approved master composition.

The immutable review reference remains
[`../APPROVED-BUTTON-ASSETS-V3.jpg`](../APPROVED-BUTTON-ASSETS-V3.jpg).
