# Approved Command Center design

Recorded from Ronnie's supplied reference and strict design handoff on 2026-09-10
(America/Los_Angeles). This is the visual target, not an installed screenshot or
proof of supported hardware. The user requested these notes and anti-drift rules;
the attachment's implementation commands and final-response format do not expand
that documentation task or override repository safety/ownership instructions.

![Approved Re-Gear Command Center composition](command-center-reference.png)

## Authority and fidelity

Implement this composition, not an agent's preferred redesign. It supersedes
earlier concepts where they conflict. Preserve structure, grouping, hierarchy,
visual language and control placement. The image communicates proportions rather
than literal pixel coordinates. Use existing Re-Gear components and branding;
do not copy sample hardware values, time, battery readings or game artwork into
the shipped UI. Unknown data must remain explicit and controls remain visible
but unavailable when their adapter is absent.

The reference was supplied by the user from the earlier generated concept.
Its utility-rail arrangement was inspired by the user's ROG Ally Command Center
reference; it is design inspiration, not imported ASUS code/assets. The PNG is
a documentation reference only and must not be bundled as game art or UI assets.
Existing source-attribution requirements still apply to delivered adaptations.

## Required composition

| Area | Required design |
| --- | --- |
| Main panel | Left portion of screen, dark translucent navy; game remains visible. No full-screen settings page or stock narrow Decky sidebar. |
| Header | Re-Gear / Command Center; small current-session thumbnail and time/battery status when verified sources exist. No fabricated readings. |
| Tabs | Quick, Performance, eGPU, Controllers, Settings horizontally; cyan selected text/underline, compact spacing, no oversized card tabs. |
| Left utility strip | **Inside the main panel body**, slim dedicated column: sun icon, Brightness, percentage and vertical slider; divider; speaker icon, Volume, percentage and vertical slider. Do not convert to horizontal cards or move these into the right panel. |
| Quick row 1 | FPS Target, Manual TDP, Auto TDP, Display. Icons and titles above separate values/details; adjustment affordance, TDP slider and Auto TDP toggle only dispatch through verified existing adapters. |
| Quick row 2 | eGPU, Controller, Safe Disconnect spanning the remaining two columns. Safe Disconnect has distinct readiness emphasis and truthful warning/result wording. |
| Right panel | Detached narrow **Quick actions** panel close to the right edge for direct thumb access, visible when the menu opens. Stacked Mic mute, Wi-Fi, Overlay, Record buttons; Customize at bottom. Game remains visible between panels. |
| Footer | Compact controller prompts, including Y Customize where available, A Select and B Back; retain LB/RB tab navigation. |

The latest supplied handoff selects **Wi-Fi** in the default right list, superseding
the earlier Audio output default. Audio output can remain an optional customization
choice. Do not mix conflicting defaults from older chat notes. The target keeps
brightness/volume on the left; any earlier proposal to freely swap those rails
does not override this explicit arrangement. Customization chooses supported
quick actions without silently moving the defining utility strip.

## Data and interaction

- eGPU: observed connection, detected GPU and useful link information. Display
  attachment, active output and rendering GPU remain separate observations.
- Controller: observed controller identity, assignment and battery only where
  actually available. A sample P1 or battery is not a production fallback.
- Safe Disconnect: readiness required, blocked, pending and result states must
  follow existing safety contracts. Successful commands or absent devices never
  establish physical unplug clearance. Do not weaken wording to match sample copy.
- Brightness/volume: vertical cyan progress, subdued track and visible thumb.
  No replacement with +/- unless a documented platform constraint requires it.
- Recording: requested Steam Game Recording action; dismiss Command Center before
  requesting start and verify actual capture behavior. No invented support.
- LB/RB changes tabs; D-pad follows spatial position across regions; A activates;
  B backs out of nested interaction then closes; Y opens customization where wired.
  Touch targets on the right must be reachable directly, without opening an editor.
- Do not show working toggles/sliders or fake completion without verified state
  and dispatch. Track missing APIs, customization and persistence independently.

## Anti-drift and responsive rules

Keep dark navy surfaces, restrained borders/depth, modest radii, cyan active/focus
accents, white primary text, blue-gray secondary text and amber warnings. Green
requires verified state. Do not introduce new colors, branding, giant icons,
excessive gradients/glow, charts, extra tabs, diagnostics in Quick, generic lists,
merged rails or unrelated refactors. Deeper settings belong in module tabs.

At reduced space, first adjust gaps/padding and secondary wording; preserve words,
controls and important actions. Do not silently remove rails or collapse into a
vertical settings page. If no usable arrangement exists at a supported size,
record the exact constraint and bounded deviation. Reference fidelity does not
justify unusable touch targets, focus traps or bypassing hardware safety.

## Acceptance and review evidence

- [ ] Left main panel and detached right action panel recognizable against PNG.
- [ ] Brightness and volume inside main body, vertical sliders, readable states.
- [ ] Exact five tabs, four-card first row, eGPU/controller/wide disconnect row.
- [ ] Right default actions and Customize match this target; correct thumb reach.
- [ ] Header, proportions, rail widths, card spacing, text hierarchy and cyan
      focus compared directly with reference; intentional deviations explained.
- [ ] Actual baseline/proposed source rendered at identical handheld dimensions
      (including 828x466 CSS pixels) and a wider case, with real breakpoints.
- [ ] No clipped headings, broken words, obscured Safe Disconnect or oversized
      footer; spatial focus, touch, nested Back and slider interaction checked.
- [ ] Unavailable controls explicit; no fabricated values or backend side effects.
- [ ] Affected tests, typecheck/build and final integrated checks pass.
- [ ] Report exact revision, files/components, wired sources, unavailable features,
      capture locations and any deviation. Native validation remains separate.

## Implementation gap at recording

PR #288 (`2df6d05`) mounts visible unavailable rails, but is **not acceptance of
this reference**: the utility strip is outside the central panel, right actions
lack the enclosing titled panel/Customize, and the default includes Audio output.
Live utility APIs, customization editor and saved layout are still absent.
Its very-narrow fallback hides rails; that is an existing limitation, not the
approved responsive target. Keep these gaps visible until actual source and
native evidence satisfy the checklist. This documentation change implements none
of those runtime changes.
