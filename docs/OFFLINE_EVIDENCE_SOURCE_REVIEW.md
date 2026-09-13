# Offline Readiness source review boundary

Status: **One reviewed local Steam source is implemented and reaching production
through the automatic focused-tile path. The separate admission-gated collection
port remains dormant. No source here can establish that a game launches offline.**

Verified against `da60e21` on 2026-09-13. Where this file and the code disagree,
the code is authoritative. Presentation is owned by
[Offline Readiness UI](OFFLINE_READINESS_UI.md); workstream state is in the
[handoff](OFFLINE_READINESS_HANDOFF.md).

## The one live evidence path

```text
focused library tile (AppID)
  -> RegisterForAppDetails one-shot callback        src/steam-app-details-request.ts
  -> private lease + field minimization             src/offline-details-session.ts
  -> classify_offline_details RPC                   main.py:688
  -> project_steam_app_details                      backend/regear/adapters/steamos/offline_steam_details.py:19
  -> classify_offline_readiness                     backend/regear/domain/offline_readiness.py:265
  -> public categorical status + reason codes
```

Alongside the RPC, the frontend keeps a second, private projection of the same
callback for confidence (`src/offline-confidence.ts:35-52`). It never crosses the
RPC boundary.

### What crosses each boundary

Exactly seven scalar fields reach the backend: `iInstallFolder`,
`eDisplayStatus`, `eCloudStatus`, `bCloudAvailable`, `bCloudEnabledForAccount`,
`bCloudEnabledForApp`, `bIsThirdPartyUpdater`
(`src/offline-details-session.ts:9-15`, mirrored in
`backend/regear/application/offline_details.py:14-18`). The backend rejects a
non-dict, more than seven keys, any unknown key, a non-integer in an integer
field, a non-boolean in a boolean field, or an integer outside `-1 .. 2**31-1`,
returning `unknown` with `offline_evidence_unavailable`
(`backend/regear/application/offline_details.py:36-46`). It also short-circuits
to `offline_evidence_game_active` or `offline_evidence_game_unknown` when the
snapshot's game state is not idle (`:33-35`).

Four more fields stay in frontend memory only — `nBuildID`,
`bHasAnyLocalContent`, `bIsSubscribedTo` and the two
`deckDerivedProperties` internet flags — together with
`local_per_client_data.installed` from the exact overview and
`BHasStoreCategory(2)` for the cached single-player category
(`src/offline-confidence.ts:35-52`, `src/offline-confidence-session.ts:22-25`).
The account name is read privately from `loginStore` for scope comparison only
and is never displayed, persisted or sent
(`src/offline-confidence-session.ts:7-12`). No title, AppID, account, path,
timestamp or collector command is serialized. Nothing is written to files, logs,
or the network, and `main.py:688-697` deliberately does not log exceptions or raw
Steam data across the boundary.

### Categorical classification, and what it can conclude

`project_steam_app_details` maps the pinned numeric Steam schema conservatively
(`backend/regear/adapters/steamos/offline_steam_details.py:19-58`):

- `iInstallFolder == -1` means not installed. A nonnegative folder proves
  nothing and stays Unknown.
- Display `9`/`10` (ReadyToInstall/ReadyToPreload) mean not installed only when
  the folder is absent or `-1`; an existing folder contradicts that inference.
- Display `26`/`27` (LicensePending/LicenseExpired) require Steam authorization.
- Display `6,18,19,20,21,39` are a pending update; `3,7,22,23,24,25,38` are a
  pending download.
- Cloud `8` failed, `9` conflict, `4,5,6,7,10` pending, and `3` counts as synced
  only when availability and both enablement flags are explicitly true.
- Display `34`/`35` (CloudError/CloudOutOfDate) add cloud attention only when the
  cloud field has not already decided the category.
- `bIsThirdPartyUpdater` adds a third-party launcher online check.

`classify_offline_readiness` then fails closed: attention reasons win, then
online-check requirements, then unknown reasons, and only fully positive evidence
returns `ready_to_try_offline`
(`backend/regear/domain/offline_readiness.py:265-287`).

**This path can never return `ready_to_try_offline`.** The projection never sets
`steam_entitlement`, so `_unknown_reasons` always contributes
`steam_entitlement_unknown` whenever no attention or online-check reason applies
(`backend/regear/domain/offline_readiness.py:413-425`). The positive status is
reachable only from richer evidence that no admitted source currently produces.

Checked exhaustively at `da60e21` by driving
`classify_minimized_steam_details` with `GameState.IDLE` over every subset of the
seven admitted keys and every value in `iInstallFolder ∈ {-1,0,1,7}`,
`eDisplayStatus ∈ [-1,44]`, `eCloudStatus ∈ [-1,13]` and both booleans for each
flag — 304,560 reports. Results: 212,682 `needs_attention`, 34,514
`online_check_needed`, 57,364 `unknown`, and zero `ready_to_try_offline`. Every
`unknown` result used one of only two reason sets, both entirely inside the
badge's incomplete-evidence allowlist
(`src/offline-badge-state.ts:15`), so a valid idle report always reaches the
player as "Unverified" rather than being silently suppressed.

### Frontend confidence is a separate, weaker judgement

`assessOfflineConfidence` (`src/offline-confidence.ts:54-105`) is a documented
heuristic over the private fields, not a second classifier of record:

- Any blocker — missing install or local content, display `9`/`10`, pending
  download/update, `bIsSubscribedTo === false`, display `26`/`27`, cloud
  error/conflict/failure, either explicit internet flag true, or a third-party
  updater — returns "Needs preparation".
- "Likely offline-ready" requires every local preparation gate to pass *and*
  explicit positives: a positive build ID, local content, subscription, display
  `11` (ReadyToLaunch), a decided cloud state, the cached single-player category,
  `bIsThirdPartyUpdater === false`, and both internet flags explicitly false.
  Missing booleans are unknown, never false.
- "Tested offline" additionally requires a matching player attestation.
- Everything else is "Unverified".

A categorical `needs_attention` or `online_check_needed` report forces "Needs
preparation" and forgets any attestation
(`src/offline-confidence-session.ts:27-30`), so confidence can never present a
game more favourably than the backend does.

What "Likely offline-ready" still does not establish: file integrity, storage
health, DRM or publisher-launcher authorization, entitlement validity offline,
or that saves are current. ReadyToLaunch means only that Steam reported no
pending download at check time. Cloud disabled means there is no cloud gate, not
that saves are current. Subscription is not offline entitlement.

### Player attestations

`OfflineTestMemory` (`src/offline-test-memory.ts`) holds at most 32 records in
memory, each bound to AppID, build ID, private account scope, the store object
and the overview object, expiring after 24 hours and cleared on plugin unload
(`src/offline-focus-checks.tsx:116`). There is no persistence, no RPC, no log.
Any build or account change, missing preparation, a known blocker, or an explicit
Forget invalidates the record; a later account return cannot resurrect it.
Reinstalling the same build without an intervening observation may be
indistinguishable, so confirmations are session-only historical evidence, never
continuing certification.

The mounted path calls `offlineConfidenceForGame` without a confirmation binding
(`src/offline-focus-checks.tsx:73`), so nothing currently writes to this memory
in production. The mechanism is implemented and tested, not reachable.

### The admission-gated collection port is dormant

`backend/regear/application/offline_readiness.py` implements the source
declaration review, bounded-cost admission, generation/freshness revalidation and
`MAX_EVIDENCE_AGE_MS` staleness rules over an injected synchronous local-memory
reader. It is imported only by `tests/test_offline_readiness_service.py`; no
production code constructs it. It is not the path a badge uses.

Its companion adapter `backend/regear/adapters/steamos/offline_steam_overview.py`
is dormant for the same reason: only `tests/test_offline_steam_overview.py` and
`tests/test_offline_readiness_service.py` import it. It projects one supplied
plain decoded overview bound to a private expected AppID, accepting only a base
game on the local client branch with affirmative platform availability, and
discarding raw identity and unrelated metadata. It selects no game, opens no
file, subscribes to nothing, calls no Steam API and sends no RPC. Its rules
mirror the live projection: explicit install booleans decide installed or not
installed and absent stays Unknown; explicit unfinished download or update states
become attention evidence; synchronized, pending and conflict cloud values stay
distinct while disabled, failed, unknown, malformed and future states stay
Unknown; and ReadyToLaunch does not prove download currency. Its numeric schema
is pinned in the module and verified with synthetic fixtures, which validate
neither the installed Steam version nor collection authorization.

Its rules still bind any *future* source: a reviewed declaration must be local,
read-only, non-networked, non-persistent and identity-minimized, with a bounded
unique set of categorical evidence fields and no command, path, title, AppID,
account or collected value; rejection is categorical and fail-closed; and
`measured_collection_cost_ms * 10 > interval_ms` rejects on cost
(`backend/regear/domain/offline_readiness.py:289-330`). This synchronous port
cannot preempt a blocking callback and must not be adapted to filesystem,
subprocess, network or subscription work without separate lifecycle and timeout
review. Generation counters must change on every selection, session or
game-state transition, including changing away and back.

## What the sources fundamentally cannot prove

**FACT:** Valve's [Offline Mode instructions](https://help.steampowered.com/en/faqs/view/0E18-319B-E34B-B2C8)
require preparation while online, completed updates, and an initial game launch.
Installation alone is insufficient. The
[ISteamApps reference](https://partner.steamgames.com/doc/api/ISteamApps#BIsAppInstalled)
distinguishes installation from ownership, and the
[cloud settings API](https://partner.steamgames.com/doc/api/ISteamRemoteStorage#IsCloudEnabledForApp)
reports whether cloud functionality is enabled, not whether saves are current.

Callback receipt is a current report from the local client. It does not prove
remote-server freshness, license validity, or offline launch. Reading a cache
does not renew evidence age, and a source named `Get...` or `Register...` is not
automatically network-free. No Steam SDK ownership workaround, cloud query or
launcher invocation is justified by this research.

Only a player actually reaching playable content while disconnected is evidence
of offline play, and even that is bounded: a launched process or menu alone is
not successful play, and Steam Offline Mode alone does not establish that a
publisher launcher had no network access. Re-Gear must not disconnect
networking, launch games, or terminate them for testing.

## Remaining source gaps

1. Validate the redacted local schema against a supported installed Steam client
   for the remote-install, cloud-disabled, cloud-conflict and unfinished-update
   cases. Pinned-schema agreement is source evidence, not per-enum device
   validation.
2. Establish a trustworthy observation age. Nothing in the live path supplies
   one; the 1 000 ms request lease bounds *our* handling, not the cache's age.
3. Re-measure reader cost as a bounded repeated sample. The recorded figures are
   single observations, not a benchmark, and the dormant admission gate's cost
   contract has no measured input.
4. Reach a positive categorical status honestly, or decide the backend
   `ready_to_try_offline` state stays unreachable from Steam reports alone and
   belongs only to attested evidence.
5. Validate native rendering and refresh recovery on a device:
   [issue 21](https://github.com/ronnierosal/Re-Gear/issues/21).

Not proposed here: an Offline Mode, automatic confirmation, a whole-library scan,
background polling, network or account queries, credential reads, save or
configuration writes, or game launches.

## Pinned references and attribution

- [Decky community Steam App types](https://github.com/SteamDeckHomebrew/decky-frontend-lib/blob/247eb635ea7acdc3e7807d5f99722daf854aaa70/src/globals/steam-client/App.ts)
  at `247eb635ea7acdc3e7807d5f99722daf854aaa70` — the pinned numeric schema for
  installed, display-status and cloud-status fields. Community types, not a Valve
  stability promise; no upstream implementation or dependency is imported.
- [Protontricks Steam parser](https://github.com/Matoking/protontricks/blob/master/src/protontricks/steam.py)
  — secondary reference for library/manifest discovery and absent, malformed or
  unreadable metadata. A discovered manifest cannot establish complete content,
  current cloud state or authorization.
- [Valve Steam Cloud](https://partner.steamgames.com/doc/features/cloud) —
  historical log success is not current sync evidence; save content and
  account-bearing logs are not a source.
- [Ludusavi manifest](https://github.com/mtkennerly/ludusavi-manifest/blob/master/README.md)
  — does not witness current Steam cloud synchronization. Review data licensing
  separately before any future reuse.
- Storage Cleaner's
  [single-game details helper](https://github.com/mcarlucci/decky-storage-cleaner/blob/932e6876dbf94b6feb4b033401139b193f9cc79a/src/utils.ts)
  was adapted into `src/steam-app-details-request.ts`; Re-Gear added abort
  handling, immediate-callback safety, late/duplicate reply suppression and
  strict private AppID validation. Attribution and license terms are in
  `THIRD_PARTY_NOTICES.md`.
- Research artifact downloaded during the 2026-09-03 inspection to the ignored
  path `out/offline-source-research/steam-client-chunk.js`, SHA-256
  `26ac253942bfaa80a48cc7b3176b2fcbef56c7c0eda3d5845562c68b0ed0b94d`. It is not
  tracked and is absent from a fresh clone. Source-inspection evidence only; no
  upstream code is bundled or copied.

---

## Historical evidence

Retained for provenance. These entries are accurate for their dates and are
**not** current instructions; where they disagree with the contract above, the
contract above is correct. In particular, the repeated "no production caller",
"live reader required" and "the categorical UI has no game-selection context"
statements were true when written and are now resolved by the mounted automatic
focused-tile path.

### Source investigation — 2026-09-03

**INFERENCE / DESIGN DECISION:** prefer one player-selected game's already-local
Steam state over disk scanning or adding a backup service. The pinned references
above record the evidence and limits that led to choosing the local overview as
the first candidate and rejecting a whole-library scan for this milestone.

### Client implementation inspection — 2026-09-03

**OBSERVATION (upstream extracted client, not installed Steam):** inspected
[SteamTracking's extracted client chunk at adfe27cf](https://github.com/SteamTracking/SteamTracking/blob/adfe27cfeb32a1ad09314039a4657e4dd4a5955c/ClientExtracted/steamui/chunk~2dcc5aaf7.js).
`GetAppOverviewByAppID` reads its map without a network operation in that method.
The local-client getter selects client ID `"0"`. The overview callback updates
the map from native messages. The lookup does not supply an observation time.

**DECISION:** the exact lookup is a promising bounded reader; native callback
registration and freshness remained unreviewed runtime boundaries. Do not call
store initialization, enumerate all games, or replace Steam's callback. Since the
local branch is a getter, serialize only explicitly extracted fields; serializing
the whole object is neither privacy-minimized nor reliable.

### Bazzite review — 2026-09-04

Inspected Bazzite `09cca86e0476c8b58aa58bdfffc744e7b02cddd7` (Apache-2.0). Its
[Steam launcher](https://github.com/ublue-os/bazzite/blob/09cca86e0476c8b58aa58bdfffc744e7b02cddd7/system_files/desktop/shared/usr/bin/bazzite-steam)
bootstraps the client for first startup; it does not assess individual games. Its
[updater integration](https://github.com/ublue-os/bazzite/blob/09cca86e0476c8b58aa58bdfffc744e7b02cddd7/system_files/desktop/shared/usr/libexec/uupd-update)
operates an OS update service. Adjacent uupd
[`updateCheck.go`](https://github.com/ublue-os/uupd/blob/fd09b47a1e56ba93cb84feffec8ceaa202462fdc/cmd/updateCheck.go)
at `fd09b47a1e56ba93cb84feffec8ceaa202462fdc` (Apache-2.0) checks system updates,
not Steam game content or cloud saves. No direct reader was found in the
inspected Bazzite tracked files and uupd cmd/drv/pkg/checks trees. This is a
scoped finding, not a claim about all dependencies. No code was imported.

### Installed static-source verification — 2026-09-04

**REMOTELY OBSERVED:** read-only SSH succeeded using the maintainer-supplied
current host and documented key/account with strict host-key checking. No
credentials or destination address are retained in this record. This resolved the
earlier missing-host blocker.

Inspected four installed Steam UI JavaScript files, bounded to 32 MiB total.
Installed `chunk~2dcc5aaf7.js` is 14,382,865 bytes, SHA-256
`4a62cebec339c3e24e5394efcb507c9e7bddc3de7cec4dc2f891c699ca389bd6`. Its
exact-AppID method only performs map membership/lookup, its local-client getter
selects client ID `"0"`, and the native overview registration symbol is present.
These methods agree with the inspected upstream behavior; the artifact hash
differs, so this is not whole-build equivalence. No remote file was created, no
runtime JavaScript was evaluated, no listener was opened, and no
service/install/device action ran.

### Runtime inspection samples — 2026-09-04

**REMOTELY OBSERVED:** existing Steam loopback debugging access was already
enabled (protocol 1.3). A bounded side-effect-checked runtime read in
`SharedJSContext` confirmed `appStore` exists, is initialized, and has the exact
lookup method. No native getter was invoked and no game/account data returned.

A bounded cache inspection (at most 16 entries and 16 client records per entry)
found a locally installed base game in the first entry: local platform
availability true, streaming false, display status 19 (UpdateQueued), cloud
status unavailable. Identity was not exported. The normal observable-map
iteration was rejected by `throwOnSideEffect`; direct inspection of native
backing values passed with that checking still enabled. MobX internals are an
inspection technique only, never an approved production integration surface.

### One-shot native details evidence — 2026-09-04

A disposable request used the adapted Storage Cleaner helper in the existing
Steam context, with installed diagnostics confirming Idle before and after. One
native registration and one removal completed, callback elapsed time 28.2 ms,
stable exact app reference. The callback supplied an installation-folder index,
display status 19 (UpdateQueued), cloud status 1 (Disabled), cloud availability
false, account cloud enabled true, app cloud enabled false, and third-party
updater false. Account, title and AppID values were not retained.

Later the same day, with the actual compiled code: picker 0.6 ms; three details
requests 48.0/54.2/53.0 ms, with three registrations and three releases, a stable
overview reference, and Idle before and after. These are small-sample
observations, not a general overhead or game-impact benchmark.

### Additional negative evidence — 2026-09-04

The same seven admitted fields were extended to recognize ReadyToInstall (9) and
ReadyToPreload (10), LicensePending (26) and LicenseExpired (27), SyncFailed
(cloud 8), and CloudError (display 34) / CloudOutOfDate (35), adding the public
reasons `cloud_save_failed` and `steam_authorization_required` with no account
identity and no new RPC fields. These are negative evidence, not positive offline
authorization; unknown or future values and a favourable display status still
cannot prove Ready. The current mapping is recorded in the live-path section
above.

### Stronger readiness proposal — 2026-09-04

Because the callback cannot establish installed completeness, up-to-date content
and offline authorization together, most otherwise normal games show unverified.
The recorded decision was **not** to solve this by converting ReadyToLaunch, a
positive folder index, subscription or playtime into offline-ready evidence, but
to separate local preparation from player-tested offline: offer a check guide,
then let the player confirm reaching playable content while actually
disconnected, labelled "Tested offline" with a date and never a guarantee of
future authorization. The 2026-09-05 entry below implements that proposal; this
paragraph records why.

### Confidence source extension — 2026-09-05

The user authorized implementing evidence-based "Likely offline-ready" and
explicit player-tested offline confidence, superseding the earlier
proposal-only restriction. It did not redefine the backend's stronger
`ready_to_try_offline` classifier or its entitlement contract.

Read-only live inspection verified that `BHasStoreCategory` only reads
`m_setStoreCategories.has`; no fetch occurs. One bounded idle read for a
previously selected game returned the new scalar facts in 5.9 ms, with a positive
build ID, content and subscription true, explicit internet flags false, local
installation true and single-player true. One schema and cost observation, not a
gameplay-performance claim.

Settled highlight changes re-read evidence rather than restoring an earlier
five-minute badge cache, so positive confidence cannot be reused for an old
build. Work stayed event-driven and limited to one highlighted game after a
450 ms settle, with cancellation and no polling or library scan. The badge
lifetime quoted in that entry was the panel's 30 seconds; the mounted automatic
path now passes 65 seconds and neutralises rather than removes the badge at
expiry — see [Offline Readiness UI](OFFLINE_READINESS_UI.md).
