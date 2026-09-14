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

All top-level cards in Quick Access, Performance, eGPU, Controllers and Settings use the same one-cell size. No two-cell-wide special card is allowed. Cards show icon, label and value only. Reasons remain in accessible names or nested details. Labels clamp to two lines and values truncate instead of increasing card height.

Top-level helper/status banners under the grids are removed. The selected tab already provides context.

All five top-level tabs omit repeated page titles and subtitles. Nested detail titles remain. Direct actions, including the one-press Safe Disconnect path, have no detail chevron.

## Right quick-action rail

The right rail remains four compact slots and must not scroll. Default visible labels are Mic, Wi-Fi, Overlay and Record; Mic retains its accessible mute label. Unsupported actions remain visible/disabled so geometry does not change.

## Popups

Operation popups remain centered and viewport-safe. Fast eGPU/Auto-TV flow should emphasize the current lifecycle step and avoid long diagnostic copy unless Details is opened.

## September 13 bounded polish

Baseline: `031a9f14f4eb6e10b72511469ee320d190d6e810` (0.3.101), including PR #330.
Ronnie's assignment `674ca0e79da74bf98302fbaa9a030ec9` supersedes baseline
height and rail spacing only: shell height is 79.2vh (82.8vh below 520px height),
10% shorter. Card heights remain 88px / 74px across all five tabs, with four
columns where content width permits. The left rail is approximately 12% narrower,
with input and thumb dimensions preserved. The four right buttons keep their size
and sit 10px from the menu. Palette, tabs, icons, popup styling and dispatch remain.

The eGPU labels are Handheld, Safe Disconnect, Resolution, eGPU Status,
Disconnect + Sleep and Disconnect + Shutdown. Unsupported actions stay disabled;
shorter labels do not enable adapters. Performance order remains Performance Profile,
FPS Target, Manual TDP, Auto TDP, Resolution, Refresh Rate. Footer retains active
LB/RB Switch Tab, A Select and B Close (B Back inside details).

`scripts/ally_polish_preview.mjs <source-root> <output-directory>` captures actual
source through production `buildTiles` and `testBuildTiles` at 828x466 and1280x720.
Its missing-data model and utility readings are simulated; it performs no device
operations. Native controller and installed appearance still need hardware review.
