# Re-Gear V3 production tiles

Status: implementation candidates pending installed visual comparison.

37 individual 240×144 SVG tile backgrounds live in this directory. The left side is intentionally clear for React live labels/values. The right side contains static feature artwork. Do not bake changing values into these files.

The exact approved review sheet is
[`../APPROVED-BUTTON-ASSETS-V3.jpg`](../APPROVED-BUTTON-ASSETS-V3.jpg). Dynamic
gauges and values remain UI overlays.

These SVGs do not independently establish visual acceptance. Several currently
reuse the lightweight `button-artwork.svg` fallback symbols and must be compared
with their corresponding rich reference tiles before broader UI rollout.
