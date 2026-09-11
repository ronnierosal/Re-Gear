# Expanded Command Center presentation

## Current design preservation contract

Follow [UI design preservation](UI_DESIGN_CONTRACT.md). The compact correction
merged through PR #274 supersedes the September 9 sizing and density described
below: the central panel is 53vw/82vh, with compact tabs/footer and icon plus label
above value and secondary text. Four columns begin at 400 measured content pixels,
three at 300, two at 280 and one below 280. Safe Disconnect spans two columns in
four-column mode. Do not treat generated utility mockups as replacement styling.
See [validation evidence and native limits](COMMAND_CENTER_VALIDATION.md).

## Historical September 9 polish

The approved September 9 polish is now implemented in the shared expanded
presentation and its browser fixture. The panel remains a **sample-data demo**;
hardware tiles have no action authority. The native menu shortcut preference
retains its existing Steam-client-local persistence.

### Superseded presentation checkpoint

- Supplied Re-Gear emblem and wordmark, with a compact demo status block.
- The CommandCenterIcon component from the icon pack merged in PR #237 supplies
  larger currentColor icons; selected tabs and focused controls remain distinct.
- Layered navy cards emphasize values, labels and readable reasons. Cyan focus
  outlines/glow add no layout shift. Unavailable cards remain focusable for details.
- Safe Disconnect is a wide amber-accented card. It retains readiness checks and
  explicit **no unplug clearance**; the summary strip cannot authorize hardware.
- Four columns at 640 or more content pixels; three at 430–639. Very narrow
  browser viewports use two at 280–429, then one, rather than shrinking card text.
  This approval supersedes the earlier 390-pixel four-column threshold below.
- Settings uses invisible section anchors and focus-driven scrolling. Page Up/Down
  jump sections in the browser; Home/End restore first/last controls outside the
  dropdown. Native dropdown navigation remains owned by Decky.
- Open Re-Gear uses Decky's Dropdown in the native adapter and a temporary HTML
  select in the browser. Only a successful preference save updates the selected
  binding and resets the shortcut; failure keeps the previous selection and error.
- Performance has one short introduction. Footer hints retain Switch Tab on the
  left and Select beside Close on the right; the user requested Navigate omitted.

## Validation and limits

`frontend-tests/expanded-command-center.test.mjs` covers grid reachability, spanning
cards, tab restoration, runtime isolation, native modal lifecycle and failed/successful
shortcut saves. `scripts/expanded_visual_preview.mjs --playwright <module>` exercises
all five tabs with normal and long reasons at 1920x1080, 1280x720, 854x480,
828x466, 640x720 and 390x700; it also checks nested Back, tab focus memory,
selected-vs-focused state, icon state colors, dropdown selection, section return,
close/reopen and the three-column comparison. Screenshots and report.json go to
its output directory. The browser harness refuses native/API imports.

These checks are **synthetic**, including the native adapter fixtures. The new
layout, dropdown, controller focus/scrolling and performance still require native
Steam/Decky validation. This PR does not build a player release or deploy to a device.
Existing shortcut callback and lifecycle behavior outside Settings is unchanged.

## Previous implementation and device evidence

The following dated notes are retained as history; current styling and grid
thresholds are defined above. Prior hardware observations do not validate this polish.

# Expanded Command Center prototype

This is a sample-data design with a native Decky test launcher. The compact
Quick Access panel offers **Open expanded demo**. The expanded hardware tiles
remain synthetic and cannot execute hardware operations; the launcher shortcut
preference is real. In the browser harness the game backdrop is a CSS illustration.

## Menu shortcut and native adapter

The default menu chord is **View / Back + Y**. Settings > Open Re-Gear offers
that chord, **L3 + R3**, or Disabled. Preferences remain client-local under
`regear.menu-shortcut.v1`. Legacy Start+Select/LB+RB settings migrate to the
new default; Disabled remains disabled. The Ally physical capture emits35+3 for View/Back+Y and25+41 for L3+R3.
The separate VIEW9 action remains accepted for other providers. Capturing those
events does not by itself prove the menu opening lifecycle.

The previous View+Y display shortcut is disabled at plugin composition so one
chord cannot open both menus. Explicit display actions retain approval and
confirmation. Future PR173 integration must preserve this reservation.

The 0.3.68 native trial showed controller navigation leaking to Steam. The
0.3.69 trial confirms navigation now works, but shows concatenated tile text,
oversized native dialog buttons and a non-working opening shortcut.

The current polish uses Decky's base Button with Focusable containers, explicit
icon/label heading and separate value/detail rows. DialogButton layout classes
are no longer applied. The footer is non-focusable controller hints, and focus
keeps the tile dark with a cyan outline. Raw input remains launcher-only.

The launcher now normalizes the documented batch callback
`ControllerInputMessage[]` (`nC`, `nA`, `bS`) before chord handling; the old
three-positional-argument assumption rejected native batches. The whole bounded
batch is validated before processing. [Provider API declarations](https://jsr.io/@steamclienthomebrew/millennium/doc)
establish the shape, but do not prove physical button codes or native delivery.
The opening chord remains non-exclusive; actual opening needs device retest.

Latest design choice: four columns at 390 or more measured content pixels,
three at 300–389, two at 220–299, and one below 220 for the extreme fallback.
Safe Disconnect spans two columns in four-column mode and the full row otherwise.
Short tile copy retains an explicit no-unplug-clearance statement. No hardware
wiring or semantics changed. This supersedes the intermediate two-column-first
polish and pinned Safe Disconnect experiment.

The same-size synthetic comparison uses a 1280×720 viewport and a measured
678.39×590.39 panel. Both four and three columns show all controls without
scrolling or text clipping; four is the preferred design. Native acceptance is
still pending. The preview pass made no package or deployment. The user subsequently authorized
a combined UI/shortcut test package; 0.3.71 is being prepared separately.

## Run the browser preview

Use an isolated runtime containing React, React DOM and esbuild. No package
installation into the production repository is necessary.

```powershell
node scripts/expanded_visual_preview.mjs --runtime C:/Users/SLDD/AppData/Local/Temp/regear-qa-preview-runtime/node_modules --output out/expanded-preview --port 4184 --serve
```

Open `http://127.0.0.1:4184`. In this browser prototype, Q/E represent LB/RB;
arrow keys navigate, Enter/Space select, and Escape represents Back/Close.
The prototype accepts `?tab=performance` (also `quick`, `egpu`, `controllers`,
`settings`), `&long=1` to stress unavailable-reason wrapping, and synthetic-only
`?columns=4` / `?columns=3` for identical-dimension density comparison.

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

The user reports basic controller navigation working on 0.3.69. The complete
checks below, including this revised styling and opening shortcut, remain open
until captured on the actual new SteamOS/Decky candidate.

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

## Latest verification evidence

`out/density-preview/report.json` records 25 viewport/tab cases, 50 standard and
stress screenshots plus two identical-dimension comparison screenshots, no
failures. Checks include separate tile rows, dark focus, a footer below 52px
without buttons, responsive columns, clipping and keyboard navigation. The
comparison files are `comparison-4-columns.png` and `comparison-3-columns.png`.
These are browser previews, not after-deployment screenshots. The user's 0.3.69
photo remains the native before evidence. Native after evidence is outstanding.

## 0.3.71 test candidate

Includes the denser native UI polish and batch-form Steam input callback repair.
Default opening shortcut remains View / Back + Y; L3 + R3 is selectable in
Settings > Open Re-Gear. Test opening after releasing both buttons completely,
then LB/RB tabs, D-pad, A and B. Inspect dark focus, label separation, the Settings
label and footer at native scale. Physical shortcut mapping and revised native
appearance remain unverified until that trial. Expanded hardware tiles remain
sample-only. The one-time identity rename is not included.

## 0.3.72 native-scale correction

Installed0.3.71 readback matched45ffdfc. Using the existing Steam CEF debugger
through SSH (without enabling debugging or changing services), measured the
actual main UI at828×466 CSS pixels, DPR2.32, and the panel at438.85×382.43.
The previous600/420 breakpoints selected two columns at that scale.

The new narrow-container typography/padding fits four cards at this measured
width. A temporary application of the actual stylesheet to the installed native
DOM showed four roughly100px columns with no clipped button/span text. Native
before and temporary style-preview screenshots are in
`out/native-validation/native-071-before.png` and
`out/native-validation/native-072-live-style-preview.png`. This is live CSS
preview evidence, not a new installed package or complete navigation acceptance.

The user's physical capture recorded `[0,35,true]`, `[0,3,true]` and corresponding
releases; L3/R3 recorded25/41. The installed Steam client exposes input messages
but neither optional controller-list nor active-controller callback. The prior
launcher therefore returned unavailable without subscribing. Input-only clients
are now accepted; incomplete chords expire after1.5 seconds of inactivity,
while matched chords stay latched until full release. Both batched messages and
three-to-five positional arguments are accepted; only controller/button/pressed
participate. The installed Steam UI handler declares five parameters, while the
actual captured digital events contain three. Regression tests cover both.

No display/power/eGPU action, identity migration, service restart or settings
migration is part of this correction. Physical opening is checked separately
with a temporary nonpersistent listener and again after candidate installation.
Temporary native shortcut verification succeeded: user closed with B and reopened
with physical View/Back + Y. The retained installed menu handler was invoked by
the candidate listener twice; captured events were Y3/SELECT35 with full releases,
with two matches and no handler errors. This validates the temporary listener and
existing menu together; installation of the packaged correction is still separate.
The first temporary trial was invalid because it looked up a launcher button after
the Decky page had closed. No permanent device changes were made by either trial.

## Visible utility rails (presentation only)

Quick Access includes left brightness/volume controls and right-edge mic mute,
recording, performance-overlay and audio-output controls. All are disabled and
marked **Unavailable / Support unverified** until supported application adapters
are connected. Live APIs, the customization editor and persisted layouts are not
implemented by this presentation slice. Hiding the rails outside Quick Access
has no effect on hardware behavior.

The central compact contract above is unchanged at the tested handheld and wider
sizes (828x466 and 1280x720 CSS pixels). At viewports at or below 600px wide, a
contained fallback reserves space for both rails; the center narrows and its
existing content scrolls. Below 481px the unsupported side rails are hidden, preserving the original
full-width central menu rather than crushing its tabs. Narrow fallback checks
at 600x466 and 360x640 verify
non-overlap, not native fit or guaranteed simultaneous visibility of every tile.
Source browser checks cover pointer navigation, keyboard containment and nested
Back focus. Native controller behavior and device readability remain unverified.
