# Re-Gear Command Center module menus

Status: approved UI workstream, 2026-09-12.

This document defines the visual/content hierarchy for the five Command Center tabs. It is a UI contract, not evidence that a platform adapter or hardware feature is already implemented. Runtime owners must replace synthetic values with observed state and keep unavailable/unknown explicit.

## Shared shell

All tabs use the same Re-Gear shell: dark navy translucent panel, five horizontal tabs, compact modular cards, restrained cyan focus/active treatment, consistent card radius/spacing, controller-first focus, and the same footer behavior. The layout must remain responsive across the Ally's known compact CSS viewport and wider 720p/1080p-style cases.

Quick Access is the only tab with the integrated left Brightness/Volume strip and detached right quick-action rail. Deeper module tabs do not duplicate those rails.

Do not add a second page title above Quick Access cards. Other tabs may keep one concise title/context line because they are deeper configuration/status surfaces.

### Shared card anatomy

Every module card follows the same visual anatomy:

1. compact icon container
2. short title
3. one primary value/state
4. one muted explanatory line
5. chevron only when the card actually opens a nested surface

Cards must not grow into banners just because a feature is important. Importance is expressed with ordering, tone, and span only where explicitly approved. Cyan means selected/active only when verified; amber means attention/readiness; muted blue-gray means unavailable/unknown. Green is reserved for verified healthy/success state.

### Nested surfaces

Selecting a card opens a focused nested surface inside the same Command Center shell rather than replacing the whole UI. Nested surfaces keep the same header/tabs footprint, show a compact Back action, and return focus to the launching card. A nested page may expose detailed controls or status, but it must not invent a second visual system.

Use short sections and rows before long paragraphs. Diagnostics/log-style material is always secondary and scrollable rather than dominating the default surface.

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

Visual priority:
- Row 1 is immediate game/performance adjustment.
- Row 2 is connected-device/status context.
- Safe Disconnect is wide because it communicates readiness and an important action, not because it is a decorative hero card.
- The utility rails must remain visually subordinate to the central tile grid.

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

Nested intent:
- Performance Profile: per-mode preset selection/summary.
- FPS Target: target selector and provider status.
- Manual TDP: wattage control plus current applied/observed state.
- Auto TDP: start/stop/configuration and target/limit controls.
- Resolution: supported target choices for the current output context.
- Refresh Rate: supported refresh choices for the current display.

Keep current state at the top of each nested surface and configuration below it. Do not bury the active value underneath explanatory copy.

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

Nested intent:
- External GPU: identity, connection state, and high-level availability.
- Dock Mode: current Re-Gear mode plus allowed mode transition entry point if runtime exposes one.
- Display Output: current output/target and display-switch status.
- Render GPU: observed rendering device only; Unknown when unverified.
- Connection Link: concise transport/link summary; detailed evidence one level deeper.
- Safe Disconnect: readiness state first, blockers second, action last. Completion remains distinct from physical unplug clearance.

The eGPU page should answer “what is connected, where am I rendering, where am I displaying, and is disconnect safe?” within a glance.

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

Nested intent:
- Player 1: current assignment and controller identity.
- Controller Battery: battery/status detail for the active controller when supported.
- Built-in Controller: enabled/disabled state and policy source.
- Controller Priority: assignment preference and fallback behavior.
- TV Dock Behavior: dock attach/detach policy and external-controller handling.
- Controller Settings: deeper controller preferences that do not belong on the overview.

Controller names may be long. Preserve the primary identity and truncate secondary metadata before shrinking the whole layout.

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

Nested intent:
- Quick Actions: supported action chooser/order without moving Brightness/Volume.
- Command Center Shortcut: launcher binding only.
- Appearance: approved presentation preferences such as supported density/accent behavior if implemented later; never arbitrary layout editing.
- Updates: installed/current version and update state when sourced from verified release logic.
- Diagnostics: support bundle/status entry point and troubleshooting summaries.
- About Re-Gear: version, license, project links, attribution.

Settings should feel like Re-Gear settings, not SteamOS Settings copied inside a plugin.

## Responsive module behavior

The same responsive priorities apply to every module tab:

1. preserve the five-tab shell and readable primary values
2. tighten gaps/padding before reducing text size
3. shorten secondary explanatory copy before changing card geometry
4. allow the central content region to scroll when necessary
5. keep cards in spatial grid order so D-pad movement remains predictable
6. never hide a primary action solely to make a screenshot fit

At compact Ally height, module cards may use the compact density rules already defined by the shared stylesheet. Do not add one-off breakpoints per module unless real on-device evidence demonstrates a specific failure.

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
