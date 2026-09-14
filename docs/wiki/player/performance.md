# Performance

The Performance section is where Re-Gear groups controls that affect how a game feels and how the handheld uses its available performance.

> ### 🖼️ UI MOCKUP — Performance menu
> **TEMPORARY IMAGE PLACEHOLDER**
>
> Show the Performance tab at a typical handheld screen size, including the important controls without technical diagnostic information.
>
> Suggested asset: `assets/wiki/mockups/performance-menu.png`

## For players — no technical background needed

> **Interface preview:** this page describes design intent and developing UI.
> Mockups and proposed labels are not proof of your installed controls.
> Follow the available labels in your build; see [current evidence](../technical/current-state.md).

## What belongs here

Depending on the Re-Gear build and supported hardware, this area may include controls or status related to frame targets, refresh/display choices, performance profiles, and Auto TDP.

The goal is to present useful choices in player language. You should not need to understand the underlying Linux interfaces to choose how you want a game to run.

## Quick Access vs Performance

Use **Quick Access** for a setting you change frequently while playing. Use the **Performance** page for deeper configuration and personalization.

> **Feature availability:** Re-Gear is under active development. Controls shown in mockups can appear, move, or change as features become validated and ready for players.

## Technical details — for advanced users and contributors

See the [owning contract/evidence](../../TDP_CONTROL.md) and [current state](../technical/current-state.md). UI PR329 is a separate test candidate; this page does not establish native or hardware acceptance.
