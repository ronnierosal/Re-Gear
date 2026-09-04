# Maintainer and agent handoff

## Offline Readiness isolated checkpoint — 2026-09-03

- Change: source research and candidate local Steam overview projection on
  `codex/offline-readiness-delivery`, based on `75f441f`; not integrated into main.
- Follow-up: guarded one-request service and allowlisted player-language reason
  delivery implemented locally. Observation-type false-positive regression fixed.
- Verification: 825 backend tests (5 skipped), 80 frontend tests, architecture,
  compilation, TypeScript, build, package, and whitespace checks passed. Bundle
  regenerated; no live source/RPC wiring or hardware lifecycle change.
- Hardware evidence: none; no deployment or device actions.
- Blockers: live source/schema/freshness validation, reader benchmark, private
  selection binding, and UI context precede production delivery.
- Next safe task and exact worktree: [Offline Readiness handoff](OFFLINE_READINESS_HANDOFF.md).
  Ally/G1 lifecycle ownership remains with its separate driver.

## Re-Gear repository checkpoint — 2026-09-03

- Change: local merge `9aeb841` combines journey timing diagnostics with the
  existing Re-Gear UI. GitHub repository renamed to `ronnierosal/Re-Gear` and
  origin updated. Public copy, links, and current-state branding notes updated.
- Verification: architecture, 805 backend tests (5 skipped), compilation,
  TypeScript, 72 frontend tests, build, and package check passed. Two legacy
  UI-copy assertions now expect Re-Gear. Generated bundle remained unchanged.
- Hardware evidence: none; no deployment or transitions performed.
- Boundaries: runtime identities and checkout directory retain their names.
  Existing uncommitted research, index, and preview work remains separate.
- Next safe task: review and authorize pushing the integrated local commits;
  publishing Wiki source is a separate action. Device installation remains
  subject to the supervised deployment gate.

This is the operational runbook and checkpoint history. The short mutable
repository/build/deployment snapshot is [Current state](CURRENT_STATE.md).
Historical entries here are evidence in their original context, not proof of a
current installed build or certified hardware behavior. Always re-check live
state before making a hardware claim.

## Repository and current snapshot

- Repository: the root of this checkout (`git rev-parse --show-toplevel`)
- Branch, HEAD, divergence, worktree, version, and active ownership:
  [Current state](CURRENT_STATE.md). Re-run `git rev-parse HEAD` and
  `git status --short --branch` before relying on that snapshot.
- Last verified installed HDM build on the Ally: `0.2.0`, revision `0d66127cd0c2`
- Last verified loader state: `plugin_loader.service` active.
- **Historical held-local lifecycle-fix candidate (2026-09-01):**
  `HandheldDockMode-0.2.0.zip` was rebuilt from clean
  `49c826c5e7d896287abefdbb2a657ae1b2da516f` and has SHA-256
  `029ca3f2b5887ae0199845b8f21e0c8f5a35f408aa0627e7602bbfad1cea39a1`.
  Its semantic version, embedded build revision, package structure, and
  release-candidate manifest were verified locally. The currently installed
  `fd2d38f` candidate is a provenance/runtime observation only; the new package
  must be installed through Decky's native lifecycle during a player-present,
  G1-disconnected session before D2 can advance. The exact pre-install
  baseline rollback archive remains `e73d249db5687f564043fe4b6f9f2fa04c2042ec`
  / SHA-256 `f9faae446cd8e61616bc0f3b3afa21961fb1b9f3fe4e87b858e1d8a9935ec519`;
  its artifact verifier passed. This supersedes prior `84219fc`, `484df70`,
  `cb1696c`, and installed `fd2d38f` candidates, was not installed or hardware-validated,
  and must remain local
  while the G1 is attached. Install is permitted only in the next
  player-present, G1-disconnected baseline session after a safe shutdown; do
  not live-unplug, replace the plugin, or restart Decky/Gamescope. The exact
  D2/D2a/D3 scope and stop conditions are in
  [the supervised session record](SUPERVISED_SESSION_2026-09-01.md).

The staged candidate, installed version, and local checkout have changed since
that checkpoint. Confirm each independently; do not deploy the historical ZIP
because it appears near the top of this runbook.

## Checkpoint and worker-integration policy

The ordered bounded queue and required check-in template are in
[Worker queue](WORK_QUEUE.md). It enables continuation only when a worker is
triggered; it is not an autonomous scheduler.

For every meaningful verified checkpoint, update the appropriate tracked
continuity, product, or roadmap note with the current goal, completed change,
exact verification, evidence status (**Implemented**, **Simulated**, or
**Hardware Validated**), blocker, and next safe task. Keep this concise and
exclude secrets, raw device identities, and transient logs.

Commit only small coherent verified slices. Before integrating completed worker
work, inspect its diff and relevant tests, confirm clean ancestry and no
unrelated changes, then fast-forward or make the smallest safe merge promptly.
Resolve conflicts deliberately. Record the integration and verification here;
do not leave a growing queue of completed worktree commits unintegrated.

## Continuity status

- **Automatic TV success and guarded audio follow-up (2026-09-02):** installed
  `0d66127cd0c2` completed the watched automatic attach on the exact Ally X + GPD
  G1 profile. The TV became the only active display, Gamescope selected the RX
  7600M XT, Steam was visibly present on the TV, and the presentation journal
  committed. Audio initially remained on the Ally. Live PipeWire evidence showed
  the exact G1 HDMI function had one SteamOS loopback sink while the internal
  loopback was default. A reversible supervised default change was verified by
  PipeWire and the player confirmed TV sound. The current worktree adds a guarded
  audio child: record the current Portable default before attach, freshly derive
  the G1 audio function from the exact topology, resolve rather than persist its
  ephemeral PipeWire node ID, select and verify it after the Gamescope restart is
  durably queued, and
  restore the recorded Portable sink on rollback/return. Missing rollback or
  ambiguous evidence fails before display mutation. Backend tests and architecture
  checks pass, but the new automatic audio path is **Implemented/Simulated, not
  installed**. Do not install while attached. Shut down fully, disconnect the G1,
  install the clean candidate, verify Portable, then perform one watched attach.

- **Automatic TV launch binding failure and local correction (2026-09-02):**
  with installed `7227e739300f`, one watched attach first exposed only an
  authorized G1 USB4 bridge and correctly remained fail-closed. SteamOS then
  enumerated Titan Ridge, RX 7600M XT `1002:7480`, G1 audio `1002:ab30`, one
  EDID-ready TV, and an observed-Up link; HDM resolved the exact
  `gpd-g1-rx7600mxt-titan-ridge` profile and automatically requested the shared
  TV transition. Gamescope restarted, the handheld screen went dark, and the TV
  reported a signal but remained black. The new session selected the internal
  GPU/panel, so the 15-second verifier timed out and HDM recorded verified
  Portable recovery. Code inspection found that `PresentationConfigStore`
  hashed the raw boot ID with the exact G1 stable identity, while the launch shim
  hashed an already-hashed boot ID with that identity. The hashes could never
  match, forcing the shim's safe internal-panel fallback. The local correction
  now carries the raw boot ID only in memory for binding revalidation and uses
  its SHA-256 separately for the serialized boot field. A writer-to-shim
  regression test and the complete local matrix pass: architecture, 776 Python
  tests with 5 expected Windows symlink skips, compileall, TypeScript typecheck,
  64 frontend tests, Rollup, package check, and `git diff --check`. This is
  **Hardware-Diagnosed and Implemented/Simulated**, not yet hardware validated.
  Candidate `22e19446e904` installed cleanly and a second watched attach again
  restarted Gamescope but selected the internal panel. The installed shim was
  current and its unprivileged exact G1 revalidation succeeded. The remaining
  failure was the config file itself: the root plugin wrote
  `presentation.json` as root-owned mode `0600`, so the `deck`-owned Gamescope
  shim could not read it and treated the config as absent. The follow-up writes
  the bounded identity-free config as root-owned mode `0644`; raw boot and G1
  identities remain absent, and launch-time exact hardware revalidation remains
  mandatory. Targeted writer/wrapper, architecture, compile, and diff checks
  pass; the full matrix and clean candidate build remain required. This second
  correction is **Hardware-Diagnosed and Implemented/Simulated**, not hardware
  validated. Do not install while the G1 is attached. Shut down, disconnect,
  install the clean candidate, verify Portable baseline, then perform one watched
  reconnect.

- **Live shared-journal blocker and local owner-aware correction (2026-09-02):**
  after the installed `898d9c8322e5` build observed the exact Ally X/G1/TV
  topology and automatic docking was enabled, it stopped before mutation with
  `journal.acknowledgement_required`. Direct bounded Decky status calls showed
  `transition.foreign_journal` and `process_release.foreign_journal`, proving
  that neither visible owner could supply the acknowledgement button. No
  journal was deleted or bypassed. The local correction adds categorical shared
  ownership, a strict exact-terminal sleep acknowledgement, legacy
  presentation-journal recognition, honest foreign-workflow labeling, and
  automatic-dock re-arming after the owning acknowledgement. It was installed as
  `7227e739300f`; the live presentation journal was identified, acknowledged by
  its exact owner, and the automatic coordinator re-armed. This is
  **Hardware Validated** for owner routing and re-arming only, not for TV success.

- **Automatic G1-to-TV docking implementation (2026-09-02):** the proven
  eGPUBridge behavior was reduced to its required mechanism—write the exact TV
  output and `1002:7480` render selector, restart
  `gamescope-session.target`, then verify live state—and connected to HDM's
  existing durable transition engine. HDM now offers an off-by-default,
  persistent player opt-in and a visible manual fallback. The backend watches
  only while opted in, accepts a partial USB4-to-exact-profile settling
  sequence, requires a later fresh sample with exact Ally X/G1 identity, one
  EDID-ready TV, observed-Up link, verified Gamescope, and Idle game state, and
  submits at most one request per attachment. USB4 presence alone, changed
  evidence, a running/unknown game, missing integration, or a pending journal
  cannot request the restart. Local verification passed architecture checks,
  765 Python tests with 5 expected Windows symlink skips, compileall, TypeScript
  typecheck, all 64 frontend tests, Rollup build, and the constrained package
  check. This is **Implemented and Simulated**, not hardware tested. The Ally
  still has the prior `f7d0bf2` build installed, and its current hot-connect
  exposes an authorized USB4 device without the G1 PCI/DRM functions; do not
  call that a detected eGPU or install/replace the plugin while attached. The
  next safe hardware gate is a clean candidate install with the G1 disconnected,
  followed by player opt-in and one watched attach. Physical live removal
  remains unsupported; shut down before disconnecting.

- **Shutdown follow-up — watcher admission (2026-09-01):** the watched native
  installation of `fd2d38f` still required Decky's five-second SIGKILL, so
  default-executor shutdown alone is not a sufficient explanation or fix.
  The last HDM log before that timeout lacked the later sleep-guard-release
  record. Local isolation shows that the Docked-iGPU watcher was started even
  in the portable/Idle, G1-disconnected baseline; cancellation of its owned
  task can await its read-only lifecycle close path. `49c826c` now starts that
  watcher only for the exact Running Docked-iGPU placement, leaving the D2
  baseline dormant. Deterministic tests cover the admission rule and the
  existing executor-drain guard; the complete local matrix passed (architecture,
  750 Python tests with 5 skips, compile, frontend typecheck/tests/build,
  package, and candidate manifest). This is **Implemented** locally with
  strong but not definitive causal confidence; it is **Hardware Validation
  Required**. The next safe hardware step is one player-present,
  G1-disconnected native install of `49c826c`, followed by one watched
  unload/reload. Stop if Decky again needs SIGKILL; do not begin D2a or attach
  the G1 first.
- **D2 native candidate installation and post-install observation (2026-09-01):**
  after a fresh bounded preflight confirmed an absent eGPU, Idle game, one
  active internal display, and healthy Steam/Gamescope/plugin-loader processes,
  the player installed the staged Decky ZIP through Decky's native installer.
  One bounded read-only capture then confirmed HDM `0.2.0` / public revision
  `cb1696c1b622`, matching the then-held-local candidate; no capture errors
  occurred and the current plugin process reported Portable/Idle/certified with
  no blockers. Decky logged the frontend import event and remained active with
  zero service restarts. This is **Remotely Observed** candidate provenance and
  baseline runtime only: render GPU remains unreadable at unprivileged
  privilege, and neither controller/input nor a real HDM RPC request was
  exercised. Crucially, Decky's native replacement stopped the old HDM process
  only after its five-second timeout and SIGKILL. Therefore D2 unload/reload
  return-to-baseline is **not validated**; preserve this lifecycle finding and
  do not proceed to D2a or attach the G1 until it is diagnosed in a separately
  approved local slice.
- **Fail-closed Connection label correction (2026-09-01):** local review found
  that the Quick Access `Ready to dock` branch inferred eGPU readiness from a
  required sleep guard plus display facts, without requiring the public exact
  G1 profile result. The read-only D3 captures therefore expose a stale/partial
  evidence mismatch, not a detected G1. The local UI now requires one exact G1
  profile, one verified present external GPU, observed Up link, one verified
  connected/EDID/active-result external display, and verified Gamescope before
  `Ready to dock`; absence or unknown evidence is explicit instead. This is an
  uninstalled local UI correction, not a hardware result or transition change.
- **D2 read-only post-install capture (2026-09-01):** fresh unprivileged,
  no-write capture recorded one Steam, Gamescope, and plugin-loader process;
  HDM was present at `0.2.0` / public revision `e73d249db568`; game state was
  Idle; one internal display was active; and no external display/GPU was
  observed. The capture had no collector errors or events. It mismatched the
  current `c8f670b` candidate provenance, so the requested candidate install
  is not established and D2 remains incomplete. Gamescope render selection and
  the Decky-owned sleep lease remain unavailable to unprivileged capture. Stop
  before D3; do not infer a candidate match from the player-visible panel.
- **D3 read-only attach observation (2026-09-01):** after the player reported
  the G1 physically attached, one bounded no-write capture instead resolved
  only the exact Ally X host and an absent/unknown eGPU profile: no external
  GPU, display, or link was observed. It saw HDM `0.2.0` / `e73d249db568`, one
  Steam/Gamescope/plugin-loader process, Idle game state, one active internal
  display, complete zero-client disconnect scan, no collector errors/events,
  and a 14.155 ms snapshot. This conflicts with the physical report and is
  therefore ambiguous, not an attach result or safe-undock finding. Render GPU
  and the Decky lease were unavailable at unprivileged privilege. Stop D3 here;
  no retry, transition, or hardware action is authorized from this capture.
- **D3 one-time read-only recheck (2026-09-01):** after the player confirmed
  G1 power and cable seating, the explicitly authorized single additional
  capture was unchanged: no PCI/USB4/eGPU identity, link, external GPU, or
  external display enumerated; no collector errors appeared. PCI/USB4 probe
  timings changed only from 4.529/0.257 ms to 4.308/0.208 ms and do not imply a
  topology change. Stop all remote checks. The smallest next operator check is
  to visually confirm the cable uses the G1 upstream host USB4 port rather than
  a display-only or auxiliary port; do not reset or otherwise mutate the Ally.
- **Cross-reference read-only topology comparison (2026-09-01):** the frozen
  eGPUBridge `ef04f65f` snapshot and a fresh HDM capture now agree on the exact
  G1 profile: RX 7600M XT `1002:7480`, HDMI audio `1002:ab30`, Titan Ridge
  bridges `8086:15ef`, xHCI `8086:15f0`, and a verified present external GPU
  with connected HDMI-A-2/EDID. Live Gamescope still used `-O *,eDP-1`, so the
  internal panel was active and the connected HDMI output was not active. The
  current idle capture had no active Steam scope; eGPUBridge's reference parser
  covers the current `app-steam-app<appid>-<instance>.scope` form. Journal
  evidence showed prior link-down/card-absent records then a fresh Link Up and
  enumeration, plus earlier AMD/bridge recovery noise; it is not a clean-link
  certification. HDM's public capture remained Gamescope-observed/render-unknown
  with link unavailable, so its current state is not dock-ready. No reference
  code, deployment, or hardware mutation was used.
- **Independent D3 confirmation (2026-09-01):** a fresh read-only capture
  independently confirmed the exact certified G1 profile, present eGPU, Idle
  game, active internal display, and one connected EDID-ready but inactive
  external display. Render GPU remained Unknown because the Gamescope
  environment was unreadable; Safe Undock remained blocked by incomplete client
  scanning/protected WirePlumber; the snapshot had no errors and took 25.680 ms.
  Installed HDM is still `0.2.0` / `e73d249`, not local `200062d`; this is
  observation only. The next display proof is the separately scheduled
  player-watched [D5.1 stage](DEPLOYMENT_VALIDATION.md#d51--player-watched-idle-tv-switch-proof-separately-scheduled), never an automatic follow-on.
- **Fail-closed link presentation correction (2026-09-01):** local UI now also
  requires a current observed-Up link before `Ready to dock`; unavailable link
  evidence says `eGPU link needs verification`. Regression coverage includes
  exact-G1/display facts without a link and the stale display/sleep-guard case.
  This is a local uninstalled UI-only correction, not a transition or hardware
  validation result.
- **D2 supervised visual checkpoint (2026-09-01):** the player reported normal
  handheld screen and controls with HDM visible in Decky, no game running, and
  the G1 physically disconnected after the requested install. This is a
  player-observed baseline only. The newest saved read-only capture still
  reports the earlier `e73d249db568` build with an external GPU present, so it
  predates this checkpoint and cannot establish installed candidate provenance,
  plugin/RPC health, or current topology. A fresh bounded SSH capture remains
  required before D2 can be recorded as complete; no D3 action is authorized.
- **Release-candidate foundation (2026-09-01):** local-only script and CI step
  validate `package.json` semantic version against Python metadata and the
  built Decky ZIP, then emit a version/revision/archive-SHA manifest plus
  release-notes template. Verification is deterministic/local; no GitHub
  Release, Decky Store/channel registration, credential, deployment, or
  hardware status change occurred. Next gate is a maintainer-reviewed manual
  publication only after applicable certification evidence.
- North Star: HDM is a safety-first SteamOS handheld reliability companion, not
  only a dock-mode controller. It must prevent or soften player-visible PC
  paper cuts, explain state clearly, and use only validated, reversible recovery
  authority. Docking/eGPU work remains the initial, tightly gated domain.
- The [Ally ↔ G1 end-to-end journey](WORK_QUEUE.md#1-ally--g1-end-to-end-dock-play-sleep-and-undock-journey)
  is the current player-facing parent focus. Its stages remain independently
  gated; it does not authorize live GPU migration, unattended disruption, or a
  safe-unplug claim without fresh complete evidence.
- **Repository-health audit (2026-09-01):** `main` is clean and passed
  architecture, compile, 659 Python tests (5 skipped), 47 frontend tests,
  typecheck, build, package, and diff checks. The completed read-only-profile
  and unexpected-undock worker commits are patch-equivalent to `46e69dd` and
  `77e518f` already on main; no duplicate merge was made. The canonical-sleep
  replay worktree predates later guarded-save/journal work and must not be
  merged. The offline-readiness draft was reviewed, committed on its worker
  branch, and cleanly cherry-picked as `7db80d9`; main verification then passed.
  No hardware status changed.
- The optional workflow/peripheral health inputs are deliberately not constructed
  by the production snapshot path yet. A future owner must be authoritative and
  event-driven or measured/cached; do not add continuous peripheral scans to
  normal Quick Access refreshes.
- The latest unattended read-only capture observed the supported handheld/G1
  profile, an idle game, a usable internal display, and an inactive external
  display. Render-GPU identity remained unavailable at unprivileged privilege;
  safe undock was not ready because the client scan was incomplete and protected
  session clients remained. Standalone capture cannot observe the Decky sleep
  lease. These are observations, not transition or sleep validation.
- A fresh unprivileged, no-write capture on 2026-09-01 again observed the exact
  supported profile, idle game, one active internal panel, and one connected
  inactive external display. Render selection remained Unknown; the client scan
  was incomplete with protected session clients, so Safe Undock was not ready.
  Snapshot collection took about 25 ms. The installed 0.2.0 capture lacks the
  current link-health schema and its fixed-file provenance does not match this
  checkout. Unchanged wake aggregates remain capability observation only, not
  suspend or wake-cause proof.
- Root read-only capture currently requires a maintainer-installed noninteractive
  rule. Its absence is a diagnostic limitation, not a reason to broaden sudo.
- The two saved wake-diagnostic aggregates were unchanged. That does not identify
  a wake source or establish suspend safety.
- The local Quick Access redesign keeps the first screen to Mode, Health,
  Connection, and Game. Safety/actions remain compact and troubleshooting is
  opt-in. Returning from long troubleshooting details resets the QAM panel
  scroll and focuses the first native in-panel control, so controller focus
  does not fall through to QAM Back. The redesign is locally tested only.
- Next concrete work: review the locally built Quick Access package with the
  maintainer; before any install, obtain a maintainer-approved exact deployment
  plan with the G1 disconnected and player-visible recovery available.
- Physical power-button double-press Safe Undock is infeasible at the current
  boundary: HDM cannot observe first/second press edges without risking ordinary
  Steam Sleep behavior. Keep the button Steam-owned; the specified future
  fallback is verified **Guide + Y** hold routed to the ordinary `UNDOCK`
  request. See [physical power-button feasibility](POWER_BUTTON_SAFE_UNDOCK.md).
- Power and Link Health currently exposes only existing exact-bridge PCIe link
  state plus optional current GT/s/lane metrics in Troubleshooting. Link-change
  notices are non-blocking: one Down/Unknown instability episode and one later
  Up observation are shown, while flapping is suppressed. Power, battery, thermal, throttle,
  budget, and sustained-churn inference remain unimplemented/Unknown. No health
  display enables a transition or Safe Undock. See [Power and Link Health](POWER_LINK_HEALTH.md).
- **Stage 1.1 checkpoint (local-only):** attach readiness now withholds
  `ready_idle` unless the exact bridge reports an observed Up link; a Down or
  unavailable link is delivered as a categorical waiting state. This is neither
  TV activity nor render-GPU, bandwidth, controller/audio, or Safe Undock proof.
  It adds no event source, RPC, polling loop, deployment, or transition authority.
- **Stage 1.2 checkpoint (pure local contract):** a direct player Dock request
  during an exactly running game can be retained only with an opaque attach
  binding and bounded expiry. Cancellation, expiry, changed binding, or Unknown
  game evidence terminalize it; a fresh idle result yields only a non-authorizing
  eligibility handoff. No persistence, scheduler, Decky route, game-close action,
  or display/GPU/audio/controller transition is wired.
- **Stage 1.3 checkpoint (pure eligibility/rollback contract):** combined
  handoff can be eligible only from one fresh opaque-bound observation with
  verified Idle game, active external display/render/audio/controller, and
  verified Portable display/audio/built-in-controller rollback facts. Missing,
  stale, contradictory, inactive, or game-active facts fail closed; a partial
  future attempt is rollback-required. No mechanism, plan, permit, RPC, or
  hardware proof is added.
- **Stage 1.4 checkpoint (pure revalidation contract):** caller-supplied
  combined-eligible Idle observations can yield prepared evidence only after a
  new same-attachment/same-generation sample at least five seconds later.
  Activity, uncertainty, stale/inconsistent facts, binding/generation changes,
  or reused samples never mature. The contract has no timer, scheduler,
  persistence, action, permit, RPC, or Safe Undock authority.
- **Stage 1.5 checkpoint (pure read-only readiness):** exact attachment/topology,
  complete clear-client scan, Idle game, verified Portable display/render/audio/
  built-in-controller fallback, and inactive external display must share one
  fresh opaque observation before HDM can say only `ready_for_revalidation`.
  Protected/incomplete scans, activity, fallback gaps, contradictions, stale
  evidence, and binding changes fail closed. This never claims physical unplug
  safety and has no process/helper/device action or transition authority.
- **Stage 1.6 checkpoint (pure result presentation):** a human-facing result
  consumes only the Stage 1.5 revalidation-bound result. It can say only
  evidence-insufficient, not-ready, revalidate-required, or eligible to begin
  supervised physical validation. Missing acknowledgement or a changed/missing
  attachment binding, generation, or sample invalidates the presentation.
  Eligibility is not a safe-to-unplug claim and creates no action authority;
  rerun Stage 1.5 immediately before any later separately approved physical
  test.
- **Stage 1.7 checkpoint (pure unexpected-removal assessment):** explicit
  before/after opaque-bound observations require verified docked bridge/topology
  followed by fresh matching-binding bridge/topology absence. Only verified
  internal display, built-in input, and internal audio can add a portable
  fallback evidence result. Unknown, stale, changed, or contradictory facts
  require supervised diagnosis. Game reporting is limited to observed
  stopped/running/unknown state; this neither claims game survival nor performs
  recovery, relaunch, deployment, or device action.
- **Stage 1.8 checkpoint (pure interrupted-sleep relaunch policy):** only a
  fresh opaque-bound observation with verified handheld display/input/audio,
  an observed stopped game session, and verified-clear update/cloud/launch/
  repeat-failure risks reaches player preference handling. Unknown preference
  can prompt; explicit opt-in can label only a future flow eligible; opt-out is
  no-relaunch. Unknown/running game, risks, stale or inconsistent evidence, or
  incomplete recovery explain the block. It cannot persist preference, launch,
  save/close a game, infer a crash/survival outcome, or act on sleep/wake.
- **Journey status UI checkpoint (read-only local presentation):** Quick Access
  now shows compact deferred-dock, prepared-idle, Safe Undock, and unexpected-
  removal-recovery rows with details behind an explicit native control. Current
  snapshot delivery does not wire these local classifier results, so the UI
  intentionally shows "Not connected" rather than guessing hardware state.
  This adds no RPC, collection, timer, action, hardware claim, or deployment.
  Back-to-top collapses both detail panels and restores focus inside the panel.
- **Offline Readiness UI checkpoint (read-only presentation):** Quick Access
  can now map only the public categories Ready to try offline, Needs attention,
  Online check needed, and Unknown. It never promises offline launch/play and
  never renders raw reason codes or game/account/AppID/path/time data. Current
  snapshot delivery remains unwired, so it deliberately says “Not connected.”
  Source review, privacy/cost/freshness admission, a collector, persistence,
  and launch authority remain unimplemented.
- **Performance measurement checkpoint (pure local assessment):** one supplied
  existing-work snapshot/optional-observer timing sample can be assessed only
  through the existing benchmarked shared telemetry budget and diagnostics
  consumer. Running/unknown game defers; stale, unavailable, unbenchmarked, or
  over-budget evidence fails closed. Public output is identity-free and labels
  game impact Unknown. It creates no collector, poller, persistence, UI
  delivery, Auto TDP, game/process intervention, device action, or performance
  conclusion; real supported-profile measurement remains required.
- **Link-instability checkpoint (pure two-sample evidence):** two fresh
  same-binding applicable observed Up/Down facts can report only stable or
  state-changed link evidence; Unknown, unavailable, stale, or changed-binding
  input is insufficient. Public output drops all attachment/sample identities.
  It does not diagnose cable/link quality, performance, removal, recovery, or
  certification and has no collector, scheduler, notification, or action path.
  Hardware link-quality validation remains required.
- **Link evidence UI checkpoint (read-only local presentation):** Journey status
  can map only optional public stable/changed/incomplete link evidence and never
  renders the raw code or identity. Absent or unknown delivery says “Not
  connected”; observed state is not a cable-quality, performance, recovery, or
  removal conclusion. No watcher, poller, notification path, or hardware action
  was added.
- **Controller shortcut presentation checkpoint (pure local contract):** the
  future Guide + Y hold policy can be presented only as delivery/input status or
  later request revalidation. It omits event/generation/device identity and
  never claims HDM listened to, owns, disables, or remaps a controller. A match
  is not an undock or Safe Undock result, and this adds no listener, relay
  invocation, RPC, transition, or hardware action. Input delivery and
  supervised validation remain required.
- **Recovery explanation checkpoint (pure frontend policy):** public link,
  interrupted-sleep, and portable-recovery categories now map to one calm
  explanation per kind/state episode; stable link evidence clears its episode.
  The policy drops raw codes and identity, never claims link quality, hardware
  recovery, game survival/crash, safe unplug, or relaunch, and owns no evidence
  collection or notification transport. No watcher, poller, system/game action,
  deployment, or hardware claim was added.
- **Journey delivery validation checkpoint (frontend boundary):** Quick Access
  now runtime-sanitizes optional journey delivery to known public categories and
  bounded schema-1 link/offline shapes before it enters UI state. Raw codes,
  reason lists, and unknown fields are discarded; malformed/future values remain
  “Not connected.” This validates no producer and adds no collector, RPC,
  storage, action, timer, deployment, or hardware claim.
- **Offline source-review checkpoint (pure local contract):** a future Offline
  Readiness source must first declare only local Steam/launcher metadata,
  read-only/no-network/no-persistence behavior, identity minimization, and a
  bounded categorical field set. Approval composes with existing cost,
  freshness, and game-aware admission; rejection is categorical and fail-closed.
  This opens no files and adds no collector, process call, persistence, polling,
  UI delivery, launch authority, deployment, or hardware action.
- **Performance Troubleshooting presentation checkpoint (read-only):** an
  optional public overhead report can now display only finite observed HDM cost
  plus game impact Unknown, deferred, incomplete, or unavailable. Raw codes and
  identity are not rendered, negative/non-finite cost fails closed, and current
  snapshot delivery remains unwired. This adds no collector, poller, timer,
  measurement authority, Auto TDP, action, deployment, or hardware claim.
- **Rollback artifact provenance checkpoint (local-only):** the validation
  artifact verifier can now require a prior redacted capture's 12-character
  public build label. A malformed or mismatched label fails closed before an
  artifact is considered for rollback; a match remains only prefix provenance,
  not installation, hardware, or certification evidence. It opens no SSH and
  performs no install, deployment, device, or session action.
- **D2 paired-artifact readiness checkpoint (local-only):** a bounded verifier
  now confirms candidate and recovered rollback validation artifacts together,
  binding the latter to the captured public build label. Its sole success is
  `verified_for_supervised_review`; no result proves installation, player
  presence, G1 disconnection, lifecycle health, or D2 authorization. It opens
  no SSH and makes no device/session change.
- **D2 evidence-record checkpoint (local-only):** before/after saved redacted
  captures can now be checked against the paired artifacts for read-only shape,
  build-label provenance, same hashed boot identity, and increasing uptime.
  `verified_d2_evidence_record` is record consistency only; it does not prove
  installation, player observation, G1 state, UI/lease health, or D2 success.
  It opens no SSH and makes no device/session change.
- **Health attention UI checkpoint (read-only):** Quick Access now maps only
  allowlisted public health blockers into at most three controller-readable
  attention messages. Unknown or future codes collapse to one generic review
  message; raw codes are not rendered. This reuses the existing snapshot and
  adds no polling, action, deployment, or hardware claim.
- **Compact journey UI checkpoint (read-only):** the controller-first journey
  summary now hides unwired optional sources, showing one `Not connected` row
  until delivery exists; its explicit detail view retains all source states.
  This changes no request cadence, collection, action, deployment, or hardware
  claim.
- **Journey detail navigation checkpoint (read-only):** opening Journey details
  now reveals the new section while retaining controller focus on its existing
  toggle for an immediate close. It changes no snapshot cadence, collection,
  action, deployment, or hardware claim.
- **Profile diagnostic completeness checkpoint (local-only):** runtime profile
  diagnostics now require every capability axis exactly once. Duplicate or
  missing axes fail at construction, preventing an incomplete matrix from being
  presented as complete. This adds no collector, action, deployment, or
  hardware claim.
- **Reported build presentation checkpoint (read-only):** Troubleshooting now
  maps only complete public build comparison evidence to candidate/different/
  unavailable status. It never infers installation from local source and adds
  no collector, RPC, deployment, or hardware claim.
- **Implemented (local-only contract):** interrupted docked-sleep recovery has
  a privacy-safe checkpoint projection over the existing canonical sleep
  journal plus a pure post-wake evidence classifier. It emits at most one
  controller-friendly notice per durable checkpoint in a UI process. “Handheld
  restored” requires exact G1 absence plus independently verified handheld
  display, input, and audio; game/session outcome is never inferred. There is
  no startup wiring, sleep listener, topology watcher, recovery mechanism, or
  Ally deployment. Current unattended captures cannot supply this proof.
- **Product policy, not implemented behavior:** after an interrupted docked
  sleep incident, HDM should verify usable handheld display/input/audio before
  considering the original game/session stopped. Only complete recovery
  evidence plus no known update, sync, or repeat-failure concern may permit a
  future default game relaunch. The first successful use must offer one
  non-intrusive choice to retain automatic restart or turn it off. No current
  code has wake wiring, those concerns, a relaunch adapter, or hardware proof;
  never claim a game crash or successful recovery from passive capture.
- **Implemented (pure local contract):** Offline Readiness classifies only
  supplied categorical install, download, entitlement, cloud-save, local
  blocker, and known online-check evidence as ready-to-try, attention needed,
  online check needed, or Unknown. It exposes no game/account/path/time data,
  never promises offline launch, and has no Steam collector, UI, persistence,
  or hardware evidence. A future source now requires a reviewed, local-only,
  identity-minimized, benchmarked, bounded-cost declaration before its fresh
  categorical evidence can be classified; game-active or unknown collection is
  deferred, and stale or unadmitted evidence remains Unknown. There is still no
  Steam collector, delivery integration, or collection authority. Next gate is
  a separately reviewed local Steam/launcher source design, including privacy
  handling, measured game-impact/freshness behavior, and explicit authority.

## SSH access

The development computer connects directly to the Ally; Codex is not installed
on the Ally.

```powershell
$key = Join-Path $env:USERPROFILE ".ssh\hdm_ally_deploy_v2"
ssh -i $key -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes deck@<current-ally-host>
```

Obtain the current host from the maintainer at capture time. If SSH fails, ask
again; do not scan the network or guess another account/key. The private key remains on the
development computer. Never copy it to the Ally, commit it, print it, or ask
for the maintainer's password.

Read-only deployment provenance check:

```powershell
ssh -i $key -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes deck@<current-ally-host> `
  'cat /home/deck/homebrew/plugins/HandheldDockMode/build_info.json; systemctl is-active plugin_loader.service'
```

Use `python scripts/remote_capture.py --host <current-ally-host> --identity-file $key`
for a redacted read-only capture. Read [Remote read-only validation](REMOTE_VALIDATION.md)
before using it.

## Direct deployment

The normal maintainer-operated path is:

```powershell
.\scripts\deploy_hdm_to_ally.ps1 `
  -HostName <current-ally-host> `
  -UserName deck `
  -IdentityFile $key `
  -ConfirmDeploy `
  -InteractiveSudo
```

It runs the complete local verification matrix, uploads a temporary archive,
creates a timestamped backup, atomically replaces only
`/home/deck/homebrew/plugins/HandheldDockMode`, restores the packaged shim mode,
and restarts only `plugin_loader.service`. It does not restart Gamescope or
invoke display, GPU, sleep, controller, audio, or eGPU actions. It prompts for
the maintainer's SteamOS sudo password at the final replacement step; Codex
must never request or handle that password.

An unattended signed updater is being enabled. Its fixed root-owned helper is
under `/var/lib/handheld-dock-mode/hdm-deploy-plugin` and accepts only a signed,
strictly validated HDM ZIP plus matching signature. It keeps a rollback backup
and restarts only `plugin_loader.service` after a successful replacement.

At this snapshot, the first sudoers rule used SteamOS argument globs that did
not match a valid invocation. A corrected installer is staged at:

```text
/home/deck/Downloads/install_ally_deploy_helper.sh
```

The maintainer must run the following once, interactively, before an agent may
use the signed updater without a password prompt:

```sh
sudo sh /home/deck/Downloads/install_ally_deploy_helper.sh
```

After the maintainer confirms success, verify the exact rule with `sudo -n -l`
and then invoke only the staged exact helper command. Do not broaden the
sudoers rule or add arbitrary shell authority.

## Safety and validation boundaries

- The GPD G1 and TV state must be re-observed; no current connection/display
  state should be inferred from this note.
- Deployment/restarting `plugin_loader.service` is distinct from a display or
  sleep test. It does not certify any hardware transition.
- Never run sleep, reboot, Gamescope restart, display handoff, USB4 reset,
  process signaling, or physical eGPU removal remotely without the current
  supervised-validation gate and maintainer visibility.
- The earlier watched TV-switch attempt failed closed on the internal panel;
  configuration-path repair exists in source but is not hardware-certified.
- The G1 sleep/immediate-wake issue remains unverified and must not be treated
  as fixed.

Read `AGENTS.md`, `docs/DEPLOYMENT_VALIDATION.md`, `docs/REMOTE_VALIDATION.md`,
and `docs/HARDWARE_VALIDATION_2026-08-31.md` before altering deployment or
hardware-facing behavior.

## Required local verification

Before handing off a change, run:

```text
python scripts/check_architecture.py
python -m unittest discover -s tests -v
python -m compileall -q backend tests scripts
pnpm typecheck
pnpm test:frontend
pnpm build
python scripts/check_plugin_package.py .
git diff --check
```
