# Command Center

**Audience:** players and UI contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** approved design; rebuild in development, not a completed new interface

The Command Center brings common controls and status into one controller-friendly
page. Modules hold deeper configuration. The repository
[UI contract](https://github.com/ronnierosal/Re-Gear/blob/main/docs/UI_SPEC.md)
owns implemented interaction rules; [PR #144](https://github.com/ronnierosal/Re-Gear/pull/144)
contains the separate design asset proposal. Design approval does not establish
implementation or hardware readiness.

## How the interface is organized

- **Quick controls:** the approved layout includes FPS, TDP, Auto TDP, display target, and a prepared Safe Disconnect tile.
- **Status links:** eGPU and controller rows open read-only details. Opening status does not request a hardware change.
- **Modules:** deeper eGPU, performance, and controller settings share the same underlying state and guarded actions as the quick controls.
- **Troubleshooting:** explanations and technical evidence stay available without filling the main page.

FPS and display settings depend on real provider capabilities; a design tile is
not an implemented setting. Safe Disconnect remains informative and unavailable
until a reviewed backend path and its validation gates exist. It cannot infer
unplug permission from a selected display or an empty client list.

## What is implemented

The existing section chooser and unavailable-section navigation were integrated
in [PR #129](https://github.com/ronnierosal/Re-Gear/pull/129). The new module registry
and routing foundation are under review in [PR #153](https://github.com/ronnierosal/Re-Gear/pull/153).
The complete Command Center shell and module pages are still being built.

The intended controller flow uses directional navigation, activation, Back, and
focus restoration. Native Decky/controller testing must verify those behaviors;
keyboard interaction with a prototype is a different level of evidence.

## Screenshots and validation

Real Command Center screenshots will be added to this guide and the README once
the implemented interface has been reviewed in Decky. Captures should identify
the build and view and avoid private game/account or diagnostic details. Design
mockups, when shown in design work, remain explicitly labelled concepts.

**Priority:** active usability work alongside eGPU reliability. Remaining gates
include shell integration, capability-driven controls, focus/navigation checks,
and screenshots of the actual interface. See [Current State](Current-State).
