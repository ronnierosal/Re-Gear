# Re-Gear Command Center module menus

Status: approved UI workstream, 2026-09-12.

This document defines the visual/content hierarchy for the five Command Center tabs. It is a UI contract, not evidence that a platform adapter or hardware feature is already implemented. Runtime owners must replace synthetic values with observed state and keep unavailable/unknown explicit.

## Shared shell

All tabs use the same Re-Gear shell: dark navy translucent panel, five horizontal tabs, compact modular cards, restrained cyan focus/active treatment, consistent card radius/spacing, controller-first focus, and the same footer behavior. The layout must remain responsive across the Ally's known compact CSS viewport and wider 720p/1080p-style cases.

Quick Access is the only tab with the integrated left Brightness/Volume strip and detached right quick-action rail. Deeper module tabs do not duplicate those rails.

Do not add a second page title above Quick Access cards. Other tabs may keep one concise title/context line because they are deeper configuration/status surfaces.

## Quick Access

Purpose: immediate in-game controls and high-value live status.

Approved cards:
- FPS Target
- Manual TDP
- Auto TDP
- Display Target
- eGPU Status
- Controller Status
- Safe Disconnect (wide, distinct readiness treatment)

Left strip:
- Brightness
- Volume

Right rail:
- Mic mute
- Wi-Fi
- Overlay
- Record

The Quick page must remain concise. Diagnostics and deep configuration do not belong here.

## Performance

Purpose: one coherent place for performance behavior and per-mode tuning.

Approved card order:
1. Performance Profile
2. FPS Target
3. Manual TDP
4. Auto TDP
5. Resolution
6. Refresh Rate

Visual rules:
- Use the same compact card component as Quick Access.
- Treat Performance Profile as an overview/entry point, not a giant banner.
- FPS/TDP controls may show active cyan state only when verified.
- Resolution and Refresh Rate remain separate concepts; do not merge them into one ambiguous display card on this page.
- Do not introduce graphs, live telemetry charts, or unsupported GPU tuning controls in this surface.

## eGPU

Purpose: readable lifecycle/status surface with safety actions prominent and diagnostics secondary.

Approved card order:
1. External GPU
2. Dock Mode
3. Display Output
4. Render GPU
5. Connection Link
6. Safe Disconnect (wide)

Visual rules:
- Connection, active display, render GPU, and transport/link remain separate observations.
- Safe Disconnect is the strongest action/status card on the page and keeps amber warning semantics until verified ready.
- Do not turn the primary eGPU page into a raw diagnostics/log viewer.
- Detailed PCI/USB4/DRM/Gamescope evidence belongs behind a nested details/diagnostics surface.
- Never imply physical unplug clearance from connection state or command success alone.

## Controllers

Purpose: make player assignment and docked-controller behavior easy to understand at a glance.

Approved card order:
1. Player 1
2. Controller Battery
3. Built-in Controller
4. Controller Priority
5. TV Dock Behavior
6. Controller Settings

Visual rules:
- Player 1 is the primary identity/status card.
- Battery is secondary and must show Unknown/Unavailable when there is no verified reading.
- Built-in and external controller state must remain distinct.
- Priority and TV Dock Behavior are configuration concepts, not inferred runtime truth.
- Do not add controller diagrams, oversized gamepad art, or a second visual language.

## Settings

Purpose: Re-Gear preferences and support entry points without becoming a generic system settings dump.

Approved card order:
1. Quick Actions
2. Command Center Shortcut
3. Appearance
4. Updates
5. Diagnostics
6. About Re-Gear

Visual rules:
- Quick Actions customizes supported right-rail shortcuts only. Brightness and Volume stay in the left strip.
- Command Center Shortcut owns how Re-Gear is opened.
- Appearance may expose approved Re-Gear presentation preferences only; it does not permit redesigning the layout.
- Updates must remain Unknown/Unavailable until a verified source exists.
- Diagnostics is an entry point to support/troubleshooting data, not a live log embedded in Settings.
- About contains version/license/project information.

## Navigation contract

- LB/RB: previous/next top-level tab.
- D-pad: spatial movement within the current surface.
- A: select/open.
- B: back from nested surface, then close at root.
- Y: Customize only when a real customization surface exists.

Focus must return to the launching card when leaving a nested surface. Do not create tab-specific navigation systems that behave differently without a documented accessibility reason.

## Ownership

ChatGPT UI workstream owns:
- menu composition and hierarchy
- layout and responsive rules
- visual styling
- icon/focus/status presentation
- popup visual consistency

Codex / Claude Code own:
- state producers/adapters
- action dispatch
- backend/hardware integration
- feature logic and persistence

If wiring requires a visual change, report the exact constraint to the UI workstream rather than redesigning the page in-place.
