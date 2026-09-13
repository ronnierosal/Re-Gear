# Command Center Ally test integration

Status: resumed as a narrowed golden-runtime UI test build, 2026-09-13.
Ronnie explicitly requested starting a build for visual tuning; the Ally is offline.
Historical stop conditions below explain why experimental power/auth remain unmounted.
Driver: Primary UI wiring. Runtime acceptance: Primary eGPU.

## Pinned inputs

- Main: `da60e21` after a successful origin fetch.
- Authoritative presentation: PR 306,
  `4380cf80c34215f2690d34a090ec5f8677bb5efd`.
- Latest hardware-validated runtime confirmed by its owner: PR 304,
  `f6059fad8c213a059aa77cbba15524ef2d9149ae`, version 0.3.98,
  tag `checkpoint/0.3.98-egpu-cycle`.
- Live tile candidate: PR 276,
  `13649ac54365f210c6546d63f2e812514465470a`; accepted broad wiring
  candidate `87b6b56dde6cc208bdb8fbf9a9fcc7f179a91291` is not the current
  hardware runtime baseline.
- Completed local utility wiring:
  `74b560adaa1c55869d3f17c3a9d855b2a8ac8250`. Its 826 frontend test passes
  belong to that candidate, not to an integrated Ally build.
- PR 315 power backend `5ad4fb46d70c05b164ac23431db5b0a18ebeb04f`
  and PR 316 coordinator `5705fc91ab2a74c1742585b46faf95416a3f65c4`
  are source-reviewed/offline-tested, not installed or hardware-validated.
- PR 317 authorization `b3365d797b81e284861b58d814e4712998499d7d`
  is not accepted for production.

## Stop conditions encountered

The requested functional sleep choices do not map to the validated runtime.
At f6059fa, `main.py` rejects `whole_dock_sleep` before teardown with
`dock_power.sleep_unverified`. `dock_power_service.py` also describes sleep
as unavailable. The runtime owner confirms that the observed sleep attempt
was blocked by inhibitors; no completed sleep/wake trial supports promotion.
Importing PR 315 to fulfill the UI requirement would introduce the experimental
runtime behavior explicitly excluded by the mission.

The requested one-time Authorize popup has no complete production target.
At PR 317's pinned head, `BoltDeviceAuthorizationRunner.argv` still constructs
`boltctl enroll --policy auto`; there is no actual one-time authorize runner.
The runtime owner also confirms that the retained intentional-disconnect
producer/restart handling and thin RPC integration are missing. Enrollment
must not be substituted for the requested one-time authorization.

The user explicitly requires stopping on a semantic UI/runtime action mismatch.
No runtime or presentation changes have been made in this integration worktree.
No combined candidate, new version, ZIP, installation, or device test is claimed.

## Preserved evidence and next decision

The prior golden ZIP remains the rollback artifact:
`Re-Gear-0.3.98.zip`, 976983 bytes, SHA-256
`aa14dcab885492368ee86e26523a8da7cd156d7483d097ba86f6814ebbf413da`.
The owner last verified 0.3.98 installed; current reachability and mode remain
unknown. No SSH or hardware operation was attempted in this pass.

Resume with either an explicitly narrowed golden-runtime visual build where
unsupported sleep/authorization actions remain visible and unavailable, or
after the runtime owner delivers accepted contracts and the separately
supervised validation needed for those actions. Preserve PR 306 presentation,
the single live publisher, and golden `disconnect_only` behavior in either case.
Do not treat this checkpoint as approval for an experimental power trial.

## Resumed test candidate

Normal merges: authoritative PR306 4380cf8, live publisher and utilities74b560a,
goldenf6059fa, and reviewed mainffd6c7a. Main maintenance changes controller bitmap
parsing and Auto TDP suspend-aware timing. eGPU runtime logic is preserved.
Version declarations advance together to0.3.99.

Obsolete wide flags and shell spans are removed to honor approved one-cell cards.
All855 frontend and49 golden tests pass. Browser source comparisons at828x466 and
1280x720 retain exact panel geometry; slider arrows adjust. Backend run:3512 tests,
291 platform skips, sole failure a stale version declaration; fixed and all13
version-contract tests pass. Final full backend verification follows.

Included: live cards, brightness/volume, existing TDP controls, shortcut settings
and golden Safe Disconnect. Unfinished: X/Y customization/move mounting, right-rail
action providers, and new sleep/auth flows. No experimental flow activated.
Preserve0.3.98 rollback; verify installed provenance when Ally is online.
# PR330 test build continuation — 2026-09-13

Ronnie explicitly resolved the prior semantic stop: unfinished sleep and authorization
must remain unavailable and do not block this UI test build. PR330 `2198b735e948d349d205ce59630d9c12608f4eef`
is authoritative for presentation. Integration starts from installed predecessor
`ae66baec12ed36f0d0b5ea117e3774f02125e990`; no old PR306 branch is reintroduced.
The validated runtime baseline remains **0.3.98 / f6059fad8c213a059aa77cbba15524ef2d9149ae**.
Version **0.3.100 is a test build**, never promoted by installation alone.

Current bounded changes:

- Exact PR330 styling, equal 88px cards (74px at short viewports), icon-only left rail,
  four non-scrolling right slots, hidden redundant headings/help strip.
- Fix zero-basis rail collapse observed at 828x466: sliders use intrinsic flex basis;
  approved width, icon, input and typography dimensions retained.
- Native Decky direction enum injected at adapter boundary. LEFT from first column
  selects Brightness; UP/DOWN selects wrappers; A enters range; range UP/DOWN adjusts;
  RIGHT returns to grid; B exits range editing. Latest queued value wins.
- Normal Safe Disconnect activation opens centered progress and consumes one explicit
  start request. Existing fresh status/action/attachment checks, persistent correlation,
  duplicate guard, result polling and default callers' confirmation remain intact.
  Closing hides progress, never claims to cancel backend teardown or clear pending state.
- Six eGPU cards remain visible. Sleep, shutdown, display switching and resolution
  lack mounted verified adapters here and stay disabled with short pending reasons.
  eGPU Status uses the existing published readings; no second snapshot poller.
- Current sleep, authorization and Auto-TV runtime remain unchanged. No authorize-once
  option or speculative authorization popup is introduced. Right-rail actions without
  providers stay unavailable. X/Y customization remains outside this narrowed build.

Validation before final packaging: 868 frontend tests; TypeScript/build/package checks;
3512 backend tests passed with 291 platform skips; 49 golden tests/all 8 contracts;
architecture and compilation. Browser source fixture at 828x466 and1280x720 confirms
equal heights across five tabs, viewport fit and keyboard rail entry/return. Native
event behavior is simulated in tests; actual Decky/controller behavior remains Ronnie's
hardware test. Final commit, CI, archive hash and installation evidence follow in hub/PR.

Integration driver: codex-01a08c09-afcf-7c50-998d-760c7634fb01, own `cc-ally-330`,
branch `codex/integration-ally-pr330`. Existing UI/eGPU primaries review the same final
head. Control/test ownership explicitly released by previous owner in hub
`fc20889cae7b4f2583d9e5cdbb090dfe`; backend/model unchanged. Preserve immutable0.3.98
and0.3.99 rollback artifacts. After installation stop development for screenshots.

---
