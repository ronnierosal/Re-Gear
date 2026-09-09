# Expanded Command Center prototype

This is a sample-data design with a native Decky test launcher. The compact
Quick Access panel offers **Open expanded demo**. The expanded hardware tiles
remain synthetic and cannot execute hardware operations; the launcher shortcut
preference is real. In the browser harness the game backdrop is a CSS illustration.

## Menu shortcut and native adapter

The default menu chord is Start + Select. Settings > Open Re-Gear offers that
chord, LB + RB, or Disabled. The preference is stored on this Steam client under
`regear.menu-shortcut.v1`; failed saves retain the active setting. Opening is
immediate when the exact pair is down on one controller, once per full release.
Controller changes, invalid events, settings changes and unload reset the listener.
The offered chords do not overlap the current View+Y display shortcut or PR173's
View+X alternative. Any future expansion of either binding catalog must recheck
cross-listener conflicts.

The default recognizes either MENU/VIEW (8/9) or START/SELECT (36/35), independently.
These are community declaration codes, not confirmed physical Ally delivery.
The native adapter maps shoulder buttons to tabs, D-pad to movement, A to select,
and B to Back/Close while the demo is open. The Steam input subscription is
non-exclusive: it does not promise to suppress a game's pause/back response.
Touch and the compact-panel launch button remain available for testing.

The modal uses only scoped Re-Gear classes and closes subscriptions on dismissal
or plugin unload. It does not resize Steam's built-in Quick Access UI. Placement,
focus, mappings and input isolation still require the native checks below.

The approved direction uses a large left-side panel, approximately 53% of screen
width and 82% of screen height at a spacious landscape resolution, with icon
tabs, cyan selection, dark navy surfaces and a fixed controller-hint footer.
Smaller viewports prioritize legibility and scrolling over exact proportions.

## Run the browser preview

Use an isolated runtime containing React, React DOM and esbuild. No package
installation into the production repository is necessary.

```powershell
node scripts/expanded_visual_preview.mjs --runtime C:/Users/SLDD/AppData/Local/Temp/regear-qa-preview-runtime/node_modules --output out/expanded-preview --port 4184 --serve
```

Open `http://127.0.0.1:4184`. In this browser prototype, Q/E represent LB/RB;
arrow keys navigate, Enter/Space select, and Escape represents Back/Close.
The prototype accepts `?tab=performance` (also `quick`, `egpu`, `controllers`,
`settings`) and `&long=1` to stress unavailable-reason wrapping.

To capture all five tabs at 1920×1080, 1280×720, 960×600 and a narrow 320×720
fallback, add these options:

```powershell
--playwright C:/Users/SLDD/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright --channel msedge
```

The harness creates normal and long-reason PNG screenshots and `report.json`, checking browser errors,
horizontal overflow, panel/footer viewport bounds, text clipping, tab focus
return, nested-page focus restoration, unavailable-slot retention and
closing/reopening. Failures set a nonzero process exit code.
These checks validate the synthetic browser only; they are not Steam/Decky proof.

The initial browser run passed all 20 viewport/tab cases with long reasons,
plus nested return and tab return to a non-default Auto TDP tile, unavailable-slot
retention and close/reopen. DOM keyboard checks also verify Quick Access's
four-column Display → Safe Disconnect movement and Performance's two-column
Manual TDP → FPS movement. Forty screenshots include normal and stress variants.
After the compact-height spacing adjustment, visual inspection confirms both
normal Quick Access rows and the status summary fit at 1280×720 with the footer
visible. Long-reason cases still scroll internally. The 320px safety fallback
wraps some tab labels across lines.

## Native implementation and validation gates

All items below remain **UNVERIFIED** until captured on the actual installed
SteamOS/Decky candidate. Do not describe the prototype as native-ready.

1. Open a custom expanded view from Re-Gear without resizing Steam's global
   Quick Access panel. Confirm positioning and scaling at the handheld's actual
   UI scale, on its internal display and a supported external display.
2. Confirm visibility over a running game, appropriate dimming, and game-input
   isolation while open. Closing must return focus to the correct Steam/game view.
3. Map physical LB/RB to tab changes only while this view is active. Prevent
   duplicate handlers and clean them up on close/unmount.
4. Verify D-pad movement across four-column rows, spanning controls and scroll
   boundaries; focus must remain visible. Verify A activation and B nested-back
   behavior, followed by B closing at the top level.
5. Restore the last valid control for each tab and the originating control after
   nested pages. Check disabled/unavailable controls retain stable positions and
   expose their reason accessibly.
6. Verify footer visibility, readable text and touch targets at the actual
   handheld scale, including long reasons and changing backend state.
7. Only after shell navigation passes, connect existing reviewed controllers and
   guarded actions. Do not add parallel hardware orchestration or invent provider
   support. Keep unknown state explicit, Auto TDP configuration explicit, and
   Safe Disconnect distinct from display switching and cable-clearance claims.

No display switch, power write or eGPU operation is connected to the expanded
demo. A separately prepared and supervised candidate is required for installation.

Documentation impact: Wiki (native test launcher and configurable menu shortcut;
installed and hardware-validated status must be reported separately).
