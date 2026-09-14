# Decky landing and Command Center migration

Assignment: ui-decky-landing-command-center-migration / 614727b708954426bd044e2c049bc900. Base: ff60cdf67db2510be1ebfa760ee2198957b23a59 (0.3.106). UI primary accepted plan; root shared-file sequence: 834ec20061714df0a1e1496ac47b664e.

## Observed failure and ownership

Installed 0.3.106 reports a null current menu snapshot while the expanded menu is open. The plugin registry retains Content with alwaysRender=true, but scans of current Steam Big Picture, QuickAccess_uid2 and SharedJSContext React trees find no mounted Content publisher. Four unfinished adapters are deliberately unavailable; Safe Disconnect still has its callback and is distinct from those disabled actions.

The existing Content component owns snapshot polling, freshness, controller/performance handles, diagnostic visibility and action callbacks. It will move once to the public Decky routerHook global-component lifecycle, returning null. The native loader's registered global-component wrapper renders through SP_JSX independently of QAM tabs. No extra React renderer or snapshot poller is introduced. Existing connection monitor, preflight and offline focus services remain plugin-owned as before.

The new landing contains shortcut configuration, brief usage and About/credits only. Shared shortcut storage/reset/error semantics stay in the existing native adapter. Runtime visibility comes from the existing expanded-menu visibility source; it does not call a QAM-context hook outside its provider.

## Destination map

| Existing control or section | Command Center destination |
| --- | --- |
| Old Command Center grid / Open expanded demo / Modules launcher | Superseded by the existing expanded shell and tabs; no duplicate launcher on landing |
| Manual power / Auto TDP configuration and stop | Existing Performance and Quick Access power details, existing owner handle |
| Controller and peripheral facts | Existing Controllers / controller-status details |
| eGPU connection, GPU/render/display facts | eGPU Status details, existing EgpuModule and observations |
| Automatic TV docking preference and status | eGPU Status → configuration, existing guarded toggle |
| Display picker / supervised handheld or TV switch | Existing display details and supported Handheld route, same approval/request callback |
| Connection progress / disconnect status | Existing eGPU snapshot details and canonical WholeDock progress/result. Retired redundant legacy Disconnect status launcher and its separate snapshot poller |
| Legacy disconnect and shutdown launchers | Legacy launchers retired. Normal disconnect uses canonical 0.3.106 one-press Safe Disconnect; shutdown is a different operation and its power composition remains separately tracked/unavailable |
| Sleep journal and prior display acknowledgements | eGPU configuration / diagnostics, existing explicit acknowledgement callbacks |
| Journey status/details, sleep protection and warning preference | Settings → Diagnostics, same observations/preferences |
| Eligible process close, force review, result acknowledgement | Settings → Diagnostics, same confirmation and approval callbacks |
| Support preview/review/copy/save | Settings → Diagnostics, existing preview/approval gates |
| Hardware details, deferred optional diagnostics, Docked-iGPU watcher acknowledgement | Settings → Diagnostics |
| Verbose diagnostic duration/enable/disable, supervised presentation preparation | Settings → Diagnostics, existing guards and confirmation |
| Shortcut preference | Canonical Decky landing control retains the existing binding store; no duplicate Command Center card |
| About and credits | Canonical Decky landing; version and license from package metadata, maintained credits index linked to existing notices |
| Resolution, sleep composition, persistent/once authorization without adapters | Remain explicitly unavailable; no invented support |

## Verification and stop condition

Test one registration/runtime owner, cold shortcut before landing mount, landing hide/unmount without runtime disposal, visibility-driven cadence, late read completion after plugin stop, freshness invalidation, live detail callback/readback, current-source identity and unchanged canonical disconnect. Inspect actual-source landing and details at Ally sizes; run focused/full checks and independent exact-head review. Packaging and physical validation remain separate. No device mutations in this implementation task.


## Accepted follow-up presentation and source decisions

- Ten initial Quick Access positions; explicit empty tokens preserve removed slots and moves. The existing 64-entry input bound remains; larger saved layouts use the shell's internal scroll. Missing provider keys remain recoverable and are not converted to deliberate removals.
- Four right-rail positions remain even when removed. Position IDs are independent of utility IDs, so Y can repopulate a focusable blank. Brightness/volume are never offered there.
- Y picker is three columns at measured main-card dimensions; unavailable choices may be placed, focused and removed, but cannot dispatch. Hold Y and A/B behavior retained.
- Menu shortcut, help and About/credits are canonical on the minimal Decky landing. Command Center Settings exposes Diagnostics and a real Reset Layout confirmation. No invented widget or overlay preferences.
- Offline Readiness is a sixth top-level tab under offline-primary sequence57ecd08. No accepted native preparation adapter exists in this build: game/readiness Unknown, schedule Unavailable, controls unavailable, no synthetic times/progress. Existing passive offline focus service unchanged.
- Root f7046c/eac91ce rejects relocating legacy DisconnectResultNotice as a present canonical result. Its legacy default status is not whole_dock_trial_status. Canonical WholeDockControl progress/result remains intact; no new reader and no fabricated equivalence. Existing correlated display/journal/process acknowledgements remain reachable in configuration/diagnostics.
- Native installed106 bounded tab-only geometry: panel midpoint233.193px, right group233.190px, all four buttons41.999px. Restored Performance after reading; no action/slider/backend mutation. Current centering preserved instead of an arbitrary offset. This is geometry evidence, not validation of the new candidate.

Software evidence: actual React plugin fixture runs real Content and publishers against simulated RPC/Decky ports, confirms cold snapshot reaches native menu before landing mounts, one registration across landing/open/close/reopen, late read after disposal cannot republish, and stopped services issue no more fixture reads. Browser captures are simulated; native candidate lifecycle/controller acceptance remains hardware work. No new ZIP/version allocated until exact combined review.


## Requested 0.3.107 UI trial baseline

Root decisions 2f516e9b43a6478c8e7ea6357280741d and 6d75bb35b47b4f2a827b6062472b8f0f explicitly preserve installed106/ff60cdf runtime for Ronnie's requested UI test artifact. Do not import315,316,binding or new authorization simply to satisfy current-main ancestry. The four version-only declarations may advance to the next unused ledger version after exact source review. Prior archives remain immutable.

Current origin/main has newer runtime source. The unchanged integration preflight will report not-current-main for this intentional test branch; record that limitation, never report PASS or main merge readiness. Ready-ref ancestry and applicable software/golden/package/exact-head review gates still apply. Main integration is a later separately reviewed reconciliation. No hardware validation is inferred from packaging/staging.

## eGPU button admission verification

The actual mounted-plugin fixture now exercises native Handheld activation through Content, the current detail publisher, `activateDisplay`, the existing shortcut request and confirmation, and simulated portable approval/execution RPCs. It checks portable/unknown/stale refusal, busy and duplicate admission, cancellation, pending approval, exact portable direction and token, backend blockers and rejected results. It also mounts the actual eGPU status view and confirms it performs no mutation. Existing cold-menu and disposal checks remain. This is simulated software evidence, not a device transition; no production runtime change was needed. The 46 focused runtime/WholeDock tests and TypeScript checks pass.

UI-primary review request 5cc07c80fc5246aaa92990e7a9c6daa8 sent 2026-09-14 05:21 UTC; the primary independently reran the mounted fixture and accepted this bounded test improvement at 05:22 UTC. The separate power composition on current main is not included in this 106-baseline trial. The Offline mapper edit grant remains unresolved after its 05:07:27 UTC deadline; preserve its owner's files and the dirty candidate.

## Separate current-runtime power popup mount plan

Inspected consumer `4c75b6ad43037a944dc830867059d1876b1419ab`, based on `54779b9` (main `9421c6f` plus unchanged binding `881baae`). This is a later current-runtime composition, never an import into the 106-only trial. Reconcile the approved UI migration as committed source into an isolated current-runtime integration branch first; do not absorb another checkout's dirty work. The binding owner's stale fixture correction and exact combined review remain prerequisites to packaging.

- Plugin owner in `index.tsx` creates one `createEgpuPowerButtonSource`, passing the agreed production execute/status port and a getter for fresh observed attachment evidence. Only plugin unload calls `dispose`. Missing evidence stays unavailable; an empty token requires an explicitly verified ordinary/already-down route, never a fallback from missing fields.
- `native.tsx` receives this lifetime-owned source. The existing Disconnect + Sleep and Disconnect + Shutdown positions call capture-only `beginSleep` or `beginShutdown`; they show the shared centered popup. Normal Safe Disconnect keeps its existing one-press workflow and does not enter this adapter.
- A separate presentation component uses `read` and `subscribe`, with an initial read on every mount. Only `view.choice` supplies confirmation/cancel handlers; retain its exact ticket callbacks. After dispatch, render `view.power` and hide/reopen the same operation. Closing a popup only unsubscribes; it does not dispose, reset, replay or cancel a dispatched request.
- Keep `requested`, `pending`, `uncertain`, `refused` and `sleep_observed` distinct. Accepted submission is not completed shutdown; an observed sleep cycle is not a healthy wake or unplug-clearance claim. Never render Ready from capability presence or `live_readiness: not_assessed`.
- Status refresh is read-only through `source.refresh`, integrated into the existing visible owner cadence or an explicit refresh control. Do not add a modal snapshot poller. If no accepted trial-evidence publisher exists, leave activation unavailable until a bounded owner read supplies it; do not guess topology from GPU absence.
- Scope here is the two explicit disconnect-before-power cards. This consumer intentionally exposes no keep-connected sleep choice, so it cannot implement the general Sleep chooser without a separately agreed adapter.

Mount acceptance must exercise actual tile activation, fresh/missing/stale capture, confirmation identity, double activation, changed evidence, pending close/reopen, refusal/uncertain correlation, read-only refresh and unload with a late reply. Preserve approved geometry, focus, normal Safe Disconnect and display switching. No native Steam interception or hardware power action is part of software verification.


## Control taxonomy revision checkpoint

Ronnie's latest taxonomy request is assigned as `ui-control-taxonomy-customization-revision`. One explicit registry defines stable identities, source aliases, domain, actual interaction type, labels/icons, feature ownership and separate native/default placement. It drives native membership, picker filters, utility labels/defaults and canonical action presentation. Unknown saved keys stay recoverable and nonreplaceable. Known duplicate aliases become stable empty slots instead of shifting positions; choosing an existing control swaps placement.

Domain chips and a Widgets filter keep the three-column picker compact. A single initial eGPU-link widget copies the existing publisher's exact value/detail/tone through a generic registry projection. Missing/stale data renders Unknown in the same saved slot; A does nothing, while Y replacement and Move still work. No model identity, FPS, storage, battery, timestamp or confidence is invented. Brightness/Volume remain fixed on the left; utility definitions can be placed on Quick with the same pending/unavailable admission rules.

Reproduced slider failure rollback and cancelled-hold repeat admission before fixing them. Failed requested values remain visible until a new valid nonpending provider observation; same-object rerenders do not clear the error. Requests remain optimistic and latest-wins, including pending provider updates. Native and keyboard repeats cannot rearm a cancelled hold, while a fresh 550ms hold still enters Move before release. Footer hints follow the focused context and direct/read-only controls have no false detail chevron.

The real mounted React fixture covers cold Content publication/lifecycle, Handheld confirmation and portable token dispatch, stale/unknown/busy/double activation, cancellation and backend rejection, eGPU status without mutation, slider failure/recovery/rapid queue, and Quick utility pending/error recovery. All RPC writes in that fixture are simulated. Independent primary browser inspection passed six viewport widths and native picker/action navigation; this does not validate the new build on hardware.

Review checkpoint only: frontend 919 tests, 916 pass and three failures in the unchanged Offline source seam. The independently reviewed proposed Offline patch is not applied without its owner's grant. TypeScript and plugin build pass. Runtime remains a descendant of 106/ff60cdf, separate from current-main power composition. Do not reserve a version, package or deploy this checkpoint. Backend: 3512 tests pass with 291 platform skips; 49 golden tests across eight contracts pass; architecture and compileall pass. Actual mounted React checks pass. The source head is recorded with the hub handoff.

Documentation impact: Wiki.


## Authorized Offline continuation

Ronnie authorized the prepared Offline source fix through primary message `efded071cf834e2b820813a79bc21e5f`. The shared mapper now returns the existing unavailable Offline tiles. Both source test graphs and the owned live composition graph include that module; the controller lifetime composition graph also includes the actual dependency under recorded primary sequencing. No controller assertion, backend adapter or action behavior changed.

The resulting full frontend suite passes 920/920 tests. TypeScript and the plugin build pass. Backend 3512 tests (291 platform skips), 49 golden tests and architecture/compile evidence from the unchanged runtime baseline remain valid. The earlier three-test blocker is resolved. Prepare the next unused version only after ledger verification, then obtain exact-head review and CI before immutable packaging. This remains the intentional 106-runtime test branch, not current-main integration or hardware validation.
