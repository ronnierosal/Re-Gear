# Re-Gear Command Center Assets v1

Individual transparent SVG assets for the proposed SteamOS/Decky Command Center and module pages.

## Status

**Candidate — visual approval pending.** These files are intentionally isolated from production assets. Do not replace `src/assets/*` or wire them into production UI until Ronnie approves the visual direction.

## Included

- `regear-mark.svg` — established Re-Gear identity mark
- `regear-wordmark.svg` — established Re-Gear lettering/header treatment
- `module-egpu.svg` — eGPU module
- `module-auto-tdp.svg` — Auto TDP module
- `module-controller.svg` — Controller module
- `mode-portable.svg` — Portable
- `mode-boosted-handheld.svg` — Boosted Handheld
- `mode-tv-docked.svg` — TV Docked / eGPU-to-TV
- `mode-docked-igpu.svg` — docked iGPU-to-display distinction
- `action-restore-portable.svg` — optional custom Restore Portable action

## Rendering

Module/action icons target 22–24 px. Mode illustrations target 32–56 px. Most new vectors use `currentColor`, allowing Decky/SteamOS to own cyan, near-white, muted and disabled tint states. No asset includes a full-canvas background rectangle, baked-in card, focus state, label, drop shadow or safe-to-unplug symbol.

The SVGs are transparent by construction and contain only foreground vector geometry. Preserve each file's viewBox/aspect ratio when rendering.

## Native/reused UI decisions

Use native Decky treatments for Modules, Back, chevrons, Stop, power, Troubleshoot and Ready/Recovering/Degraded/Attention indicators. No redundant copies are shipped here. A safe-to-unplug icon is intentionally excluded while disconnect/shutdown reliability remains under active hardening.

## Integration rule

Codex and Claude Code should consume the exact approved revision from this folder, preserve proportions, and avoid redrawing or substituting the approved assets. Approval metadata and SHA-256 values live in `ASSET_MANIFEST.json`.
