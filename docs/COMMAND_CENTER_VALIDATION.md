# Command Center validation - 2026-09-09

Source integration branch: `codex/integration-qa-finish`.
Approved layout: `7cbf19e` (review02 baseline `df6a36c`); approved asset geometry
is retained under `docs/design/command-center/assets/v1` and pinned by tests.

## Implemented and checked

- Exclusive Command Center, module, status, troubleshooting and compact-picker routes.
- One shared manual/Auto TDP controller; manual enablement never indicates loop activity.
- Device-bound power choices, guarded writes, Stop preemption and stale-response rejection.
- Shared display action; both docked modes offer the guarded return to handheld.
- No inference of bus absence or cable clearance from unavailable status.
- Approved inline icons, stable two-column grid and invoking-control focus restoration.

Local integration checks: 414 frontend tests pass; 2161 backend tests pass with
41 platform skips; TypeScript, architecture, Python compilation, targeted Ruff,
Rollup build and plugin package checks pass. The PR CI is the final-head Linux
rebuild check; local success alone is not a remote CI or merge claim.

## Browser visual evidence

`scripts/qa_visual_preview.mjs` renders actual component TSX using the fixture
entry `frontend-tests/qa-render-preview.tsx`. It requires external React,
React DOM, esbuild and Playwright runtimes, without changing the project lockfile.
Run `node scripts/qa_visual_preview.mjs --runtime <node_modules> --source .
--output <evidence-directory> --playwright <playwright-directory> --channel msedge`.

33 cases cover 268/310/320px ready, attention, unavailable, long-name, modules,
TDP/display pickers and Auto TDP ready/running/unavailable/recovery views.
There was no horizontal overflow, clipped content or browser page error. Two
captures per case include initial and keyboard-focus views. Encoding and long
Safe Disconnect label fit were corrected during review.

All captures contain synthetic readings and mocked Decky controls/focus styling.
They do not prove native CSS, native D-pad navigation, transport or device behavior.

## Remaining acceptance gates

- Native Game Mode: measure viewport; exercise A/B and every D-pad direction,
  return focus from tiles/status/modules, short-panel scrolling and fresh reopen.
- Observe exact installed build and capture reviewed, privacy-safe Decky screenshots.
- Exercise disconnect through Decky's transport only within the hardware owner's
  supervised test plan. Software completion is not physical cable clearance.
- Integrate game-close/relaunch and sleep through the owner's APIs after #202/#206
  resolve current conflicts and land; do not duplicate their orchestration.
- FPS limiting remains unavailable until a verified provider contract exists.

No release ZIP was built, staged or installed by this integration. The handoff's
0.3.64/0.3.65 device records are historical, not a fresh device observation.
