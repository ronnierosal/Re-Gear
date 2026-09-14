# Offline Readiness completion goal

Goal: a player can tell, at a glance in their library, whether a game needs
attention before they leave Wi-Fi — and the result is honest about everything it
cannot know.

Verified against `da60e21` on 2026-09-13. Detailed behavior is owned by the
[UI contract](OFFLINE_READINESS_UI.md) and the
[source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md); state and evidence live in
the [handoff](OFFLINE_READINESS_HANDOFF.md).

## Working mode

Authorized 2026-09-04 and still in force: complete the software remotely —
development, research, setup and automated verification — without requiring the
maintainer to be at the handheld. Reserve player involvement for the final
acceptance session, and do not ask the maintainer to select a development sample
or perform routine manual installation steps. Suitable licensed upstream code may
be used with attribution.

Scope is Offline Readiness. The separate handheld/eGPU lifecycle remains owned by
its driver: do not restart its services, replace its installed runtime, or run
display, GPU or sleep transitions. Assignment and integration go through the
`primary-offline-game-mode` primary.

## What the result must never do

The result identifies its scope, reports uncertainty honestly, expires, and is
discarded on context changes. It never promises an offline launch, changes saves
or settings, launches a game, disconnects networking, or turns Steam Offline Mode
on. An installed game, a favourable display status, a Steam Cloud setting or a
positive folder index is never converted into proof of offline readiness.

## Tasks and current status

1. **Live source access — complete.** Existing read-only SSH and Steam inspection
   work without enabling debugging. The installed exact-lookup source and the
   real cache shape were inspected and hashed.
2. **Reader and field projection — complete for the admitted fields.** Seven
   scalar callback fields reach the backend projector; four more plus the exact
   overview's installed flag and cached single-player category stay in frontend
   memory. Regression coverage exists for both. What remains is schema validation
   on a supported installed client for the remote-install, cloud-disabled,
   cloud-conflict and unfinished-update cases.
3. **Evidence age — open.** Nothing in the live path supplies a trustworthy
   observation time. Receipt time is not cloud-server freshness, and reading a
   cache does not renew its age. The 1 000 ms request lease bounds our handling
   only.
4. **Overhead — open.** Recorded samples are 0.6 ms for the picker, 28.2 ms for
   one details request, 48.0/54.2/53.0 ms for three, and 5.9 ms for one idle
   read. These are single observations, not a benchmark or a game-impact proof,
   and they all measure the *frontend* Steam callback. The backend side has never
   been timed at all, and it is not obviously cheap: each RPC takes a full
   diagnostics snapshot — discovery, mode inference, workflow and peripheral
   observation, health assessment — purely to read the game state
   (`main.py:691`, `backend/regear/application/snapshot.py:50-75`). With a
   60-second cadence per focused tile, that is the number worth measuring first.
   A bounded repeated sample is still owed, and the dormant admission gate's cost
   contract has no measured input.
5. **Player delivery — delivered.** The automatic focused-tile check is mounted
   with the plugin, binds to one focused game, cancels on selection, session and
   game-state changes, rejects stale responses, and sends only categorical
   evidence to the existing Python classifier. No competing classifier was added.
6. **Integration — complete for the mounted path.** The delivery is merged and
   present on `main`. Three delivered pieces remain unreachable in production —
   the manual Quick Access panel, the attestation write path, and the
   admission-gated synchronous evidence service with its overview adapter — and a
   fourth, the Quick Access journey row, is mounted with no backend source.
   Deciding their fate is assigned work, not an implicit next step.
7. **Explanation surface — authorized, pending implementation.** Removing the
   manual panel in 0.3.35-offline.1 (`docs/CURRENT_STATE.md:409-415`) was
   deliberate and left the automatic badge without a place to show its reasons or
   accept a "Tested offline" attestation. Ronnie authorized an Offline Readiness
   tab on 2026-09-13 — with a configurable sync schedule and a force-sync action,
   where sync refreshes readiness *and* requests available preparation content.
   The UI owner builds the visual tab; this workstream supplies its headless
   wiring model and the native preparation adapter. None of it ships yet, and the
   existing passive focused-tile behaviour stays the baseline until a player
   turns a schedule on.
8. **Final player acceptance — last, and open.** One short controller-driven
   check of selection, wording, responsiveness and the displayed result, tracked
   by [issue 21](https://github.com/ronnierosal/Re-Gear/issues/21) together with
   refresh and retry recovery in Home and Library. An actual offline launch is a
   separate player action, never an unattended developer test. Software passes do
   not satisfy this gate and must not close that issue.

## Related documents

[Handoff](OFFLINE_READINESS_HANDOFF.md),
[source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md),
[UI contract](OFFLINE_READINESS_UI.md),
[third-party notices](../THIRD_PARTY_NOTICES.md).

---

## Historical record

Retained for provenance; not current instructions.

### Milestone close — 2026-09-04

The original bounded research and read-only delivery milestone completed on
2026-09-04: the native reader, Python classification RPC and one-game panel were
implemented and locally verified. A new goal then tracked end-to-end integration,
remote preparation and final acceptance. That authorization also superseded
earlier workstream assumptions that every metadata probe needed a player-selected
game page, or that a disposable read subscription was forbidden.

### Library-tile refinement — 2026-09-04

The maintainer asked for a compact per-game library-tile offline badge, inspired
by a supplied Steam controller/checkmark reference, as the glanceable entry
point, with the one-game check providing explanations. Panel and passive tile
rendering were implemented locally with the supplied assets; installed rendering
and controller checks remained. The badge later became the mounted delivery and
the panel became dormant — see [UI contract](OFFLINE_READINESS_UI.md).

### Checkpoint — 2026-09-04

The one-game panel and `classify_offline_details` RPC were wired locally, with
seven scalar callback fields crossing the RPC and game titles and IDs staying in
the view. The backend read diagnostics directly and invoked the existing Python
policy rather than the plugin snapshot endpoint that starts lifecycle work. The
picker enumerated at most 256 cache entries on explicit request. Delivery expired
after one second; displayed guidance was explicitly a historical Steam report,
expired after 30 seconds, and cleared on selection, view, game, source or
overview changes observed during existing panel refreshes. No verified native
session event hook or new polling loop was claimed.

Review found and fixed stale source-result retention and failed-picker
old-choice retention. Full backend gate at that time: 834 tests, 5 skipped;
frontend 92 passing; typecheck, architecture, compileall, build, package and
whitespace checks passed. The feature had not been installed or
controller-validated. Shared main was still at base `75f441f` with unrelated
dirty research and docs, and the G1 driver reported 0.3.2 installed from
`codex/g1-lifecycle-logging` (tip `412b9dc` when inspected) while that branch
inherited 0.2.0, so deploying over that runtime was explicitly ruled out. Work
lived on branch `codex/offline-readiness-delivery` in an isolated worktree. No
installation or G1 lifecycle action occurred in this workstream.
