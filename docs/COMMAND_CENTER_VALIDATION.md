# Command Center validation

## Current expanded UI checkpoint — 2026-09-10

Verified main: `4be87ddec4560a96945da68d478383105f91caa0` (merged PR #268).
This is repository evidence, not an installed-device readback.

| Change | Evidence and limits |
| --- | --- |
| Supplied live readings | PR #268 keeps detail state by tile ID and resolves the latest supplied reading each render. Missing readings show Unknown rather than retaining an old value. Omitted tabs still have an explicit preview contract; the native bridge must supply unavailable/empty readings for all live tabs. |
| Return from removed reading | Reviewed source `dc6fdf35cfb5eeba22151b5b06bc6e4ef2afaf0a` falls back to the active tab when no content controls remain. Owner reports a real-TSX DOM check at 828×466; native Decky behavior remains separate. |
| Application detail controls | PR #274 remains open at `f0f51d13492c0c322985ec7120ba7933979bb63c` at this checkpoint. Source review resolved editor-withdrawal and tabindex-wrapper findings. All four GitHub checks pass. This is not yet a merged or installed capability. |
| Stable editor focus | The #274 owner reports 605 frontend tests plus browser checks for retained caret, pending/failure/cancel, and null/removed detail recovery before pressing Back. The reviewer inspected the corrections but did not independently rerun that browser capture. |
| Live bridge | `command-center-data-source` is owned by Claude `claude-a224c5ea-bc89-4cb3-9bd2-93893d3c48f8`, covering index.tsx/native.tsx. Combined bridge plus detail controls require a fresh exact-commit check. |

The previous device session measured 828×466 CSS pixels at DPR approximately
2.32. Current column selection uses measured content width: four columns at 640px or
more, three at 430–639px, two at 280–429px, and one below 280px. Viewport and
outer panel width are not content width. The earlier approximately 438.85px
panel therefore does not establish four-column behavior under current thresholds.
The historical temporary four-column native stylesheet trial, with Safe Disconnect
spanning two columns, showed no clipped text; it is not current-layout proof. A temporary corrected View/Back + Y listener opened the
menu twice; that evidence does not establish installation of later UI/bridge work.

## Next combined and native checks

1. Record the exact merged bridge/control commits and installed build separately.
2. Ensure every native tab uses actual readings or explicit Unknown/unavailable
   states. Verify that the modal shares application observation updates rather
   than starting a second snapshot poller.
3. Navigate with D-pad, A/B and LB/RB. Test tab changes, nested Back, empty-grid
   return, reopening, settings dropdown and focus restoration to the launcher.
4. While an editor is focused, refresh readings and preserve caret/selection.
   Withdraw its tile or return no detail content: focus must recover to Back.
   If focus already moved to a surviving tab or Back, it must stay there.
5. Verify unavailable, pending, failure, retry and cancellation presentation with
   the application's action guards. Rendering or status refresh must not dispatch
   actions. Hardware-affecting execution stays within its supervised plan.
6. Inspect responsive column fit, Settings label, compact footer, dark cyan focus and
   scrolling at the measured native scale; capture privacy-safe before/after images.
7. Verify configured menu shortcuts after full release, including close/reopen.
   Non-exclusive shortcut observation does not guarantee suppression of Steam or
   game input.

Source review and browser fixtures do not prove Decky gamepad routing, transport,
physical disconnect readiness or installed behavior. No device operation or new
release was performed for this checkpoint. FPS capability remains unavailable
unless the application supplies a verified provider contract.

## Historical compact UI evidence — 2026-09-09

The earlier `codex/integration-qa-finish` integration used approved layout
`7cbf19e` and asset geometry under `docs/design/command-center/assets/v1`.
It reported 414 frontend tests and 2161 backend tests (41 platform skips), plus
typecheck, architecture, compilation, build and package checks. Its 33 browser
cases covered compact 268/310/320px layouts, module routes and power/display
pickers. Those synthetic two-column captures describe the compact predecessor,
not the current expanded handheld layout.

The former note that #202/#206 awaited conflict resolution is obsolete: those
PRs merged. Game-close integration must be judged by current production call
sites and tests, not by reapplying the historical patch artifact. No historical
0.3.64/0.3.65 or 0.3.72 record is a fresh device observation.

Documentation impact: Wiki.
