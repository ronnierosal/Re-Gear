# Ally last-mile Command Center contract

This document captures the final on-device interaction rules for the current Command Center integration. Runtime wiring should satisfy these rules without restyling the UI.

## Safe Disconnect

Safe Disconnect is a **single-press action** from the card/button surface.

- A single `A` press starts the existing guarded Safe Disconnect workflow.
- Do not open a generic details page first.
- Do not require a second confirmation press merely to begin the workflow.
- The runtime may still block/refuse/abort if verified safety preconditions fail.
- Progress, blockers and completion belong in the centered operation popup.
- Never claim physical unplug clearance unless the runtime explicitly establishes it.

Normal card copy should stay terse: `Safe Disconnect`, plus at most a short state such as `Ready`, `Checking`, `Blocked`, or `Unknown`. Long safety explanations belong in the progress/details surface, not the card.

## Brightness and volume

The left rail is icon-first. Do not add the words `Brightness` and `Volume` back into the visible rail; retain them as accessible labels.

Controller behavior:

- D-pad can move focus into the left utility rail.
- Up/Down selects Brightness or Volume when traversing the rail.
- Once a range input owns focus, its native directional adjustment is preserved.
- A directional move back toward the main grid returns focus to the nearest first-column card.

The runtime should feed current 0–100 readings into the existing `UtilityRail` seam and use its request callback. Do not replace the rail or slider components.

## Card sizing and copy

All top-level cards in Quick Access, Performance, eGPU, Controllers and Settings use the same one-cell size. No two-cell-wide special card is allowed. Long descriptions clamp instead of increasing card height.

Top-level helper/status banners under the grids are removed. The selected tab already provides context.

Quick Access and Settings do not repeat their tab name with a large page title/subtitle above the content.

## Right quick-action rail

The right rail remains four compact slots and must not scroll. Default slots are Mic Mute, Wi-Fi, Overlay and Record. Unsupported actions remain visible/disabled so geometry does not change.

## Popups

Operation popups remain centered and viewport-safe. Fast eGPU/Auto-TV flow should emphasize the current lifecycle step and avoid long diagnostic copy unless Details is opened.
