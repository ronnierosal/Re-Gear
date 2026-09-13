# Command Center runtime handoff

Status: UI-owned contract for Codex / Claude wiring, 2026-09-12.

Runtime wiring should consume the approved Command Center rather than redesign it. The UI workstream owns composition, geometry, typography, icons, focus treatment, popup styling and responsive behavior. Runtime owners provide observed values, actions, and feature-specific content.

## Shared nested UI primitives

Use `src/quick-access/expanded-command-center/detail-ui.tsx` for nested module content where possible:

- `CommandDetailSurface` — root stack for a nested module page.
- `CommandSection` — compact card/section matching the Command Center.
- `CommandStatusRow` — label/value/status row with shared tone semantics.
- `CommandNotice` — warning/success/error/neutral notice without inventing a new alert style.
- `CommandActionRow` — consistent action placement.
- `CommandValue` — prominent value + secondary label.

These primitives are presentation-only. They intentionally contain no backend, RPC, polling, or hardware logic.

## Runtime responsibilities

Runtime code may:
- supply live tile values and tones;
- inject verified nested controls through the existing detail/render boundary;
- update values while the menu remains open;
- disable actions when unavailable/pending;
- provide truthful Unknown/Unavailable/Blocked/Error states;
- route Safe Disconnect through the existing safety path.

Runtime code must not:
- resize or move the Command Center;
- change the shared header for a feature-specific state;
- add/remove/reorder approved top-level cards to match provider availability;
- replace missing cards with omission; use Unknown/Unavailable;
- restyle nested pages, confirmations, or popups independently;
- add a second navigation/focus system.

## Approved live tile identity

The live source must preserve these IDs and order even when values are unknown:

- Quick: `fps`, `manual`, `auto`, `display`, `egpu`, `controller`, `disconnect`
- Performance: `profile`, `fps`, `manual`, `auto`, `display`, `refresh`
- eGPU: `device`, `dock`, `display`, `render`, `link`, `disconnect`
- Controllers: `controller`, `battery`, `builtin`, `priority`, `tv-controller`, `controller-settings`
- Settings: `quick-actions`, `shortcut`, `appearance`, `updates`, `diagnostics`, `about`

Safe Disconnect remains wide on Quick and eGPU.

## Current integration blockers / decisions

### Live tile source (#276)
The source must emit the approved full tile identity above. Missing providers produce Unknown/Unavailable values; they do not remove cards. Resolution/refresh/player-order fields that are not available yet stay explicit rather than reverting to sample values.

### Safe Disconnect (#304)
The runtime-owned disconnect control may be injected into the nested Safe Disconnect surface. Disconnect-specific copy such as `Keep the cable connected` belongs inside that nested surface using `CommandNotice`; do not repurpose the shared Re-Gear header.

### Confirmation/popup styling
Use the project shared confirmation wrapper only if it conforms to the current Re-Gear modal design contract. Runtime owners may wire callbacks and state, but presentation changes belong to the UI workstream.

## Example composition

```tsx
<CommandDetailSurface>
  <CommandSection title="Connection">
    <CommandStatusRow label="External GPU" value={gpuName} tone={gpuKnown ? "success" : "unavailable"} />
    <CommandStatusRow label="Render GPU" value={renderGpu} tone={renderKnown ? "active" : "unavailable"} />
  </CommandSection>

  <CommandNotice tone="warning" title="Readiness check required">
    Keep the eGPU connected until the existing Safe Disconnect flow grants the next allowed action.
  </CommandNotice>

  <CommandActionRow>{/* existing verified runtime action */}</CommandActionRow>
</CommandDetailSurface>
```

The example demonstrates composition only; it does not grant unplug clearance or define runtime policy.
