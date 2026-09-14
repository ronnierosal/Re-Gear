# Offline Readiness delivery workstream

Continuation record for Offline Readiness. Read this with the
[UI contract](OFFLINE_READINESS_UI.md), the
[source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md) and the
[completion plan](OFFLINE_COMPLETION_PLAN.md). Code and tests define executable
behavior; this file records state, evidence and remaining gates.

Verified against `da60e21` on 2026-09-13.

## Mission and ownership

Help a player understand whether a game needs attention before leaving Wi-Fi.
This workstream owns Offline Readiness evidence research, narrow read-only
adapters, tests and delivery guidance.

- Assignment, sequencing and integration go through the `primary-offline-game-mode`
  hub stream; see [agent coordination](AGENT_COORDINATION.md).
- The Ally/G1 driver retains connection, disconnect, sleep, recovery, deployment
  and hardware transitions.
- The UI driver retains broad Quick Access design; see
  [UI design contract](UI_DESIGN_CONTRACT.md).

Standing prohibitions for this workstream: no whole-library scan, no network or
account queries, no credential reads, no game launches, no cache deletion, and no
automatic Offline Mode. **No writes to Steam, account or game configuration** —
that is the boundary, not writing as such. Re-Gear may persist its own sync
preferences, because a schedule the player turned on has to survive. An installed
game is not proof of entitlement, cloud sync, or offline launch. No live source
can self-declare a benchmark from synthetic test timing.

**Authorized 2026-09-13, pending implementation.** Ronnie has since authorized an
Offline Readiness tab in Quick Access with a force-sync action and a
player-configured sync schedule, where sync both refreshes readiness and requests
available preparation content (game updates, and shader content where Steam
exposes it). Downloads are therefore authorized by **either** an explicit
"Sync now" for a chosen game **or** a schedule the player has enabled — always
for one explicitly chosen game, never library-wide. Everything else above still
stands, and none of it is built yet: the existing passive 60-second focused-tile
behaviour remains the baseline until a schedule is configured, and a longer
interval must never keep a stale positive badge alive until the next scheduled
check.

## Where the work stands

**Delivered and mounted.** The automatic focused-tile check is created with the
plugin at `src/index.tsx:2378` and stopped at `src/index.tsx:2405`. Focusing a
library, home or search tile settles for 450 ms, then reads one bounded Steam
app-details callback, classifies it through the `classify_offline_details` RPC,
and shows a badge on that one tile for 65 seconds, refreshing every 60 seconds
while the tile stays focused and retrying twice at 5 seconds after a failure.
Exact timings, cancellation rules and the categorical-versus-confidence split are
in the [UI contract](OFFLINE_READINESS_UI.md).

**Delivered but not reachable in production.** Three pieces exist, are tested,
and have no production caller: the manual Quick Access panel
(`src/offline-readiness-panel.tsx`), the player attestation write path that would
produce "Tested offline", and the admission-gated synchronous evidence service
(`backend/regear/application/offline_readiness.py`) with its overview adapter.
The manual surface was removed deliberately in 0.3.35-offline.1, revision
`c0590e5` (`docs/CURRENT_STATE.md:409-415`), leaving the source dormant and
tree-shaken from the build. What that left was a **deferred explanation
surface**: a player sees a badge and its label but cannot read the preparation
reasons or record an attestation.

That question is now answered. Ronnie authorized an Offline Readiness tab on
2026-09-13, and the UI owner is building the visual tab; this workstream supplies
its headless wiring model. The deferral above is therefore historical. It remains
no licence to restore the old panel layout, and nothing here is implemented yet.

**Mounted but unwired.** The Quick Access "Offline readiness" journey row renders
from `payload.journey`, and the backend snapshot emits no `journey` key, so it
always reads "Not connected". The fail-closed wording is correct; the row is not
a working status surface.

**Not established.** No source in the live path supplies a trustworthy
observation age. The backend `ready_to_try_offline` status is structurally
unreachable from the Steam-report projection, because entitlement is never set.
Nothing here is evidence that a game launches offline.

## Verification evidence

| Scope | Result | Revision | Source |
| --- | --- | --- | --- |
| `python -m unittest discover -s tests -p 'test_offline*.py'` | 45 passed | `da60e21`, 2026-09-13 | this workstream |
| `node --test frontend-tests/offline*.test.mjs frontend-tests/steam-app-details-request.test.mjs` | 68 passed, 0 failed or skipped | `da60e21`, 2026-09-13 | independent baseline review |
| `pnpm typecheck` | passed | `da60e21`, 2026-09-13 | independent baseline review |

The frontend figures come from an independent read-only baseline review of this
head, held as a local agent-coordination record rather than a repository
artifact. That review also notes their limit: the focus harness transpiles the
real module but mocks the details
session, native source, classification, confidence and badge attachment, so the
68 passes exercise modules rather than the combined production journey. There is
no React panel-mount test. Coverage gaps that review identified, none of them
validated defects: native immediate account and session events,
navigation-window replacement and cleanup, startup against a partially
initialized native DOM, and real callback or RPC latency.

Read those green suites carefully. `frontend-tests/offline-confidence-session.test.mjs:17`
and `frontend-tests/offline-confidence.test.mjs:66` both assert the
`tested_offline` status and both pass, while no production code can reach that
status — the only caller supplying a confirmation binding is the unmounted
panel. A passing suite here proves the module works when called, not that
anything calls it.

PR 25 merged as `ebde3d06faeb0182f8f364d44b45c25c685bc334` and is an ancestor of
`da60e21`, so the refresh and retry recovery it delivered is present in the
reviewed head.

No golden behavior ID names Offline Readiness, so
`scripts/check_golden_behaviors.py` does not currently gate this feature.

Hardware evidence: none. Passing software checks are not evidence of native
rendering, controller behavior, or offline launch.

## Remaining gates

1. **Supervised device validation — [issue 21](https://github.com/ronnierosal/Re-Gear/issues/21).**
   This is the single canonical tracker for the merged refresh and retry
   behavior, consolidating the former #22. Its remaining acceptance covers
   recording the installed version and test context, keeping a tile selected
   through a download or display-status change in Home and Library, returning
   from gameplay without refocusing, exercising a controlled transient failure,
   and verifying focus/account changes, cancellation, unload and late-response
   handling in the native UI. Software acceptance in that issue is already
   checked; do not close it on software evidence.
2. **Source gaps.** Schema validation on a supported installed client, a
   trustworthy observation age, and a bounded repeated cost sample. See
   [source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md).
3. **Decide the dormant surfaces.** Whether to mount the manual panel, wire the
   journey row to a snapshot source, reach the attestation path, or retire them.

Nothing in this workstream authorizes a release, installation or hardware action.

---

## Historical checkpoints

Retained for provenance. These entries were accurate on their dates and are
**not** current instructions. The branch, base, worktree, goal-tool and G1
baseline references below are historical; the pending-UI, no-live-reader and
missing-host statements are resolved.

### Original workspace — 2026-09-03

Branch `codex/offline-readiness-delivery`, based on `75f441f`, in an isolated
offline-readiness worktree. Older `codex/offline-readiness` at `73dc3da` was the
historical foundation and was not resumed. The original plan was: inspect
classifier, source-admission, UI and upstream evidence; record a source decision,
privacy boundaries and unsupported evidence; implement the smallest justified
source/delivery slice with synthetic failure, stale, identity-minimization and
game-admission tests; then record verification and the remaining production gate.

### Guarded request and reason delivery — 2026-09-03

Commit `03946d2` added the candidate source projection and research; `0bfbf8f`
added guarded request and categorical reason delivery. A candidate adapter
minimized one privately bound base-game overview into categorical evidence, where
explicit updates, downloads and cloud conflicts could report attention and no
favourable overview could report offline-ready. The application request service
admitted before reading and rechecked private selection/session generation, game
state, timestamp and actual cost before public serialization, with one injected
local-memory read and no scheduler, cache, retries or production reader. The UI
sanitizer preserved only known bounded reason codes with fixed next-step
guidance, cloud conflicts taking priority over updates.

Independent review found and fixed an observation-type hole that allowed
malformed evidence to appear ready; a regression covers the reproduced case.
Verification at that point: 825 backend tests passed (5 skipped), 80 frontend
tests passed, and architecture, full Python compilation, TypeScript, frontend
build, package and whitespace checks passed. Node required explicit TypeScript
import extensions, so no-emit checking and Rollup were given extension-aware
configuration. A copy regression restored the explicit
offline-play-not-guaranteed wording. Production snapshot delivery was
unconstructed at that time, so the milestone was not yet a usable live check.

### Five-task completion plan — 2026-09-04

| Task | Evidence recorded that day | Remaining acceptance recorded that day |
| --- | --- | --- |
| 1. Inspect existing live read-only access | **Verified:** loopback Steam debugging endpoint, protocol 1.3, shared context, initialized `appStore`, exact lookup function; runtime evaluation enforced `throwOnSideEffect` with no debugging activation. | Complete for identifying access; production use needed its own design. |
| 2. Validate selected-game local evidence and freshness | **In progress:** no selected-game route was present in the inspected targets. | Exact local fields, game/session binding, evidence age; categorical output only. |
| 3. Measure collection cost | Pending task 2. | Actual bounded reader timings; no claim from source parsing, SSH latency or synthetic tests. |
| 4. Wire on-demand check and invalidation | Guarded service and reason text locally tested; live transport and context unconstructed. | Selected-game request, clear status and reasons, discard on context change or expiry; no background polling. |
| 5. Test/build/review before installation | Prior local gate: 825 backend tests (5 skipped), 80 frontend tests, architecture, typecheck, build and package passed. | Re-run affected gates for final changes; review the final artifact. No deployment authorized. |

Runtime probes returned only capability booleans. CDP target IDs stayed
transient; no titles, AppIDs, account data, cache records or destination
addresses were persisted, and probe connections closed after each read. The app
rejected creating a second goal because the earlier goal was unfinished, and the
recorded decision was to continue the existing objective rather than falsely
complete it to clear that tool constraint.

### Reuse checkpoint — 2026-09-04

Added an attributed adaptation of Storage Cleaner's single-game detail request
helper as `src/steam-app-details-request.ts`, with six callback, timeout, abort
and error tests plus TypeScript passing. It used one subscription with a bounded
timeout and cleanup, and at that point was not wired to Steam. See
`THIRD_PARTY_NOTICES.md`.

### Remote source evidence — 2026-09-04

The maintainer supplied the current Ally host and read-only SSH succeeded,
resolving the earlier missing-host blocker; no installation was needed. The
one-shot details helper was executed remotely for one bounded installed-game
sample with verified Idle before and after: details received in 28.2 ms, one
registration and one removal, stable app object, installation folder known,
display status 19, cloud status 1, cloud unavailable, account cloud enabled, app
cloud disabled, third-party updater false, and no identity exported. The
corresponding conservative callback-field projector was added, with 39 focused
offline tests, architecture and compilation passing. This measured one request
only, not a general benchmark, and native metadata callback receipt is not proof
of server sync or launch authorization. Bazzite and updater research found no
direct substitute in inspected source. Artifact hashes and further detail are in
[source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md).

### Panel and RPC wiring — 2026-09-04

The native reader, private request lifecycle, one-game panel and strict Python
classification RPC were wired and verified locally: 834 backend tests (5
skipped), 92 frontend tests, typecheck, architecture, compileall, build, package
and whitespace. Live actual-code sample: picker 0.6 ms; three callback requests
48.0/54.2/53.0 ms with exactly matching registration and cleanup, Idle before and
after. No new runtime was installed. The G1 driver had 0.3.2 installed from its
lifecycle branch while this branch inherited an older baseline, so the recorded
next step was to prepare an integrated candidate before coordinating
installation, preserving the existing G1 changes.

### Badge checkpoint — 2026-09-04

Supplied SVGs rendered beside the check result and through a passive native-tile
adapter using exact native data-id, adding only owned nodes, not altering Steam
badges or styles, and clearing recycled, expired or invalid results. Only an
explicit game check started a 30-second badge lifetime, with no new periodic scan
or per-tile Steam request. Read-only Ally DOM inspection confirmed selectors and
numeric IDs, but the badge had only been visually exercised in a local browser
surrogate: 100 frontend tests, typecheck, build, package and whitespace passed,
with no installed runtime change.
