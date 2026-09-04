# Offline Readiness source review boundary

Status: **Implemented (review contract, candidate Steam overview projection,
and guarded request service); live reader and selected-game wiring required**

Active workstream and continuation: [Offline Readiness handoff](OFFLINE_READINESS_HANDOFF.md).

Before a future Offline Readiness source can reach the existing collection
admission gate, it must supply an identity-free declaration: local Steam or
local launcher metadata, read-only behavior, no network, no persistence,
identity minimization, and a bounded unique set of categorical evidence fields.
The declaration contains no command, path, title, AppID, account, or collected
value.

The review accepts only a local/read-only/non-networked/non-persistent/minimized
declaration. Its approval then composes with the existing reviewed, benchmarked,
bounded-cost, freshness, and game-aware collection admission policy. Rejection
is categorical and fail-closed.

This is not a Steam or launcher collector. It opens no files, calls no process,
stores no data, schedules no work, and creates no UI or launch authority. A
future source still needs separate implementation review and measurement.

## Source investigation — 2026-09-03

**FACT:** Valve's [Offline Mode instructions](https://help.steampowered.com/en/faqs/view/0E18-319B-E34B-B2C8)
require preparation while online, completed updates, and an initial game launch.
Installation alone is insufficient. The [ISteamApps reference](https://partner.steamgames.com/doc/api/ISteamApps#BIsAppInstalled)
also distinguishes installation from ownership. The
[cloud settings API](https://partner.steamgames.com/doc/api/ISteamRemoteStorage#IsCloudEnabledForApp)
reports whether cloud functionality is enabled, not whether saves are current.

| Primary source | Useful evidence | Decision / limits |
| --- | --- | --- |
| [Decky community Steam App types, pinned revision](https://github.com/SteamDeckHomebrew/decky-frontend-lib/blob/247eb635ea7acdc3e7807d5f99722daf854aaa70/src/globals/steam-client/App.ts) | Local overview is separate from selected/most-available remote clients. Explicit installed, display-status, and cloud-status fields are available in the declared shape. | First candidate. These are community types, not a Valve stability promise. A future reader must prove the live schema and freshness. No upstream implementation or dependency is imported. |
| [Protontricks Steam parser](https://github.com/Matoking/protontricks/blob/master/src/protontricks/steam.py) | Library/manifest discovery and handling of absent, malformed, and unreadable metadata. | Secondary reference only. A discovered manifest cannot establish complete content, current cloud state, or authorization. Avoid a whole-library scan in this milestone. |
| [Valve Steam Cloud](https://partner.steamgames.com/doc/features/cloud) | Describes synchronization around launch/exit and diagnostic cloud logs. | Historical log success is not current sync evidence. Do not read save content or account-bearing logs as the default source. |
| [Ludusavi manifest](https://github.com/mtkennerly/ludusavi-manifest/blob/master/README.md) | Save-location and game metadata for backup discovery. | Does not witness current Steam cloud synchronization. No backup or cloud tooling is added. Review data licensing separately before any future reuse. |

**INFERENCE / DESIGN DECISION:** prefer one player-selected game's already-local
Steam state over disk scanning or adding a backup service. A source named
`Get...` or `Register...` is not automatically proven network-free; reader
behavior must be inspected before admission. No Steam SDK ownership workaround,
cloud query, or launcher invocation is justified by this research.

## Implemented candidate projection

### Bazzite review — 2026-09-04

Inspected Bazzite `09cca86e0476c8b58aa58bdfffc744e7b02cddd7` (Apache-2.0).
Its [Steam launcher](https://github.com/ublue-os/bazzite/blob/09cca86e0476c8b58aa58bdfffc744e7b02cddd7/system_files/desktop/shared/usr/bin/bazzite-steam)
bootstraps the client for first startup; it does not assess individual games.
Its [updater integration](https://github.com/ublue-os/bazzite/blob/09cca86e0476c8b58aa58bdfffc744e7b02cddd7/system_files/desktop/shared/usr/libexec/uupd-update)
operates an OS update service. Adjacent uupd
[`updateCheck.go`](https://github.com/ublue-os/uupd/blob/fd09b47a1e56ba93cb84feffec8ceaa202462fdc/cmd/updateCheck.go)
at `fd09b47a1e56ba93cb84feffec8ceaa202462fdc` (Apache-2.0) checks system updates,
not Steam game content or cloud saves. No direct reader was found in the inspected
Bazzite tracked files and uupd cmd/drv/pkg/checks trees. This is a scoped finding,
not a claim about all dependencies. No code from these projects was imported.

### One-shot native details evidence — 2026-09-04

The maintainer authorized completing development remotely without player presence.
A disposable request used the adapted Storage Cleaner helper in the existing
Steam context. Installed diagnostics confirmed Idle before and after. One native
registration and one removal completed, with callback elapsed time 28.2 ms and
stable exact app reference. No files/settings/game actions were performed.

The native callback supplied an installation-folder index, display status 19
(UpdateQueued), cloud status 1 (Disabled), cloud availability false, account
cloud enabled true, app cloud enabled false, and third-party updater false.
`offline_steam_details.py` projects these into categorical evidence: update
attention, no positive installation-completeness or cloud-sync claim. The
corresponding redacted fixture is covered by tests. Account/title/AppID values
are not retained. Callback receipt is a current report from the local client;
it does not prove remote-server freshness, license validity, or offline launch.

### Reused plugin code — 2026-09-04

At the maintainer's request, inspected and adapted Storage Cleaner's
[single-game details helper](https://github.com/mcarlucci/decky-storage-cleaner/blob/932e6876dbf94b6feb4b033401139b193f9cc79a/src/utils.ts)
into `src/steam-app-details-request.ts`. It uses one subscription with a bounded
timeout and cleanup. Re-Gear adds abort handling, immediate-callback safety,
late/duplicate reply suppression, and strict private AppID validation. Six focused
tests and TypeScript checking passed. Attribution/license details are in
`THIRD_PARTY_NOTICES.md`.

The plugin's README also identifies the local overview cloud field, corroborating
our selected cache source. Its helper does not prove cache freshness or native
subscription cost/network behavior. This async candidate has no production caller
and must not be inserted into the synchronous local-memory service. Native source
review and a separate asynchronous request boundary remain required. No storage
cleanup or backup/sync code was imported or run.

`backend/hdm/adapters/steamos/offline_steam_overview.py` consumes one supplied
plain decoded overview with a private expected AppID. It accepts only a bound
base game and the local client branch, with affirmative platform availability.
It does not select a game, open a file, subscribe, call Steam, or send an RPC.
Raw identity and unrelated metadata are discarded from its result.

- Explicit install booleans become installed/not-installed; absent is Unknown.
- Explicit unfinished download/update states become attention evidence.
- Cloud synchronized, pending, and conflict values remain distinct. Disabled,
  failed, unknown, malformed, or future states remain Unknown.
- ReadyToLaunch does not prove download currency. No entitlement, DRM,
  first-launch, or offline-success claim is inferred. This source alone cannot
  produce **Ready to try offline**.

The numeric schema is pinned in the module and verified with synthetic fixtures.
Those tests do not validate the installed Steam version or authorize collection.
The existing source declaration, cost, game-state, and freshness gates remain
mandatory for any future application caller.

## Production gates and next slice

### Client implementation inspection — 2026-09-03

**OBSERVATION (upstream extracted client, not installed Steam):** inspected
[SteamTracking's extracted client chunk at adfe27cf](https://github.com/SteamTracking/SteamTracking/blob/adfe27cfeb32a1ad09314039a4657e4dd4a5955c/ClientExtracted/steamui/chunk~2dcc5aaf7.js).
`GetAppOverviewByAppID` reads its map without a network operation in that method.
The local-client getter selects client ID `"0"`. The overview callback updates
the map from native messages. The lookup does not supply an observation time.

**DECISION:** the exact lookup is a promising bounded reader; native callback
registration and freshness remain unreviewed runtime boundaries. Do not call
store initialization, enumerate all games, or replace Steam's callback. Since
the local branch is a getter, serialize only explicitly extracted fields;
serializing the whole object is neither privacy-minimized nor reliable.

Downloaded research artifact SHA-256:
`26ac253942bfaa80a48cc7b3176b2fcbef56c7c0eda3d5845562c68b0ed0b94d`.
It remains in ignored `out/offline-source-research/steam-client-chunk.js`; no
upstream code is bundled or copied into the implementation. This artifact is
source-inspection evidence only, not a freshness or supported-profile benchmark.

**NEXT EVIDENCE:** obtain the maintainer's current Ally host as required by
`OPERATOR_HANDOFF.md`. Inspect installed client provenance/static reader behavior
read-only, then determine whether an already available observation boundary can
provide a trustworthy timestamp and exact selected-game/session binding. Do not
enable remote debugging, deploy a plugin, install an observer, or trigger a
Steam refresh to obtain evidence under this workstream's current authority.

### Installed static-source verification — 2026-09-04

**REMOTELY OBSERVED:** read-only SSH succeeded using the maintainer-supplied
current host and documented key/account with strict host-key checking. No
credentials or destination address are retained in this record.

Inspected four installed Steam UI JavaScript files, bounded to 32 MiB total.
Installed `chunk~2dcc5aaf7.js` is 14,382,865 bytes, SHA-256
`4a62cebec339c3e24e5394efcb507c9e7bddc3de7cec4dc2f891c699ca389bd6`.
Its exact-AppID method only performs map membership/lookup. Its local-client
getter selects client ID `"0"`, and the native overview registration symbol is
present. These methods agree with the inspected upstream behavior; the artifact
hash differs, so this is not whole-build equivalence.

No remote file was created, no runtime JavaScript was evaluated, no listener was
opened, and no service/install/device action ran. This closes the installed
static-reader inspection gap only. Cache values, callback freshness, selected
game binding, and reader cost have not been observed or benchmarked. Next:
identify an already available read-only runtime observation surface without
enabling debugging or installing an observer.

### Request boundary

**REMOTELY OBSERVED sample, 2026-09-04:** a bounded cache inspection (at most 16
entries and 16 client records per entry) found a locally installed base game in
the first entry. Local platform availability was true, streaming false, display
status 19 (UpdateQueued), and cloud status unavailable. Identity was not exported.
The normal observable-map iteration was rejected by side-effect checking; direct
inspection of native backing values passed with that checking still enabled.
This verifies a real cache shape and preserves missing-cloud uncertainty. It
does not prove source age or offline play. MobX internals are an inspection
technique only, not an approved production integration surface.

**REMOTELY OBSERVED, 2026-09-04:** existing Steam loopback debugging access was
already enabled (protocol 1.3). A bounded side-effect-checked runtime read in
`SharedJSContext` confirmed appStore exists, is initialized, and has the exact
lookup method. No native getter was invoked and no game/account data returned.
This establishes an available inspection surface, not production collector
approval or evidence freshness. No selected-game route was observed; the player
was asked to select a game before per-game inspection. No listener, subscription,
observer, or plugin was installed, and the probe sockets were closed.

The application service in `backend/hdm/application/offline_readiness.py` now
implements one request's admission/revalidation/freshness boundary over an
injected bounded local-memory reader. It does not manufacture source approval
or benchmark evidence. It reads no source when unreviewed, unbenchmarked,
running, unknown, or without a selected context. It rejects a changed private
generation, stale/future evidence, exceptions, and elapsed time beyond the
declared measured ceiling. The source timestamp is preserved.

This synchronous local-memory port cannot preempt a blocking callback. It must
not be adapted to filesystem, subprocess, network, or subscription work without
separate lifecycle and timeout review. No production implementation is admitted
or constructed. Generation counters must change on every selection, session,
or game-state transition, including changing away and back.

1. Identify a bounded, local-only reader and a private exact game/session
   binding. Inspect its implementation; do not trust a cached overview merely
   because it was retrieved now. Reading a cache does not renew evidence age.
2. Validate a redacted local schema on the supported Steam client, including
   remote-install, cloud-disabled/conflict, and unfinished-update cases.
3. Measure actual reader cost and define timeout/cancellation/unsubscribe,
   size limits, and source/session invalidation. Synthetic projection timing is
   not a Steam collector benchmark.
4. Route one explicit request through source review and game admission, then
   revalidate selection/session/game state and freshness before public delivery.
   Never expose frontend-supplied paths, commands, or identities as authority.
5. Deliver categorical reasons and a player-language next step through the
   existing UI contract in coordination with the UI owner. No polling loop,
   auto-launch, automatic Offline Mode, credential access, or save mutation.

Remaining product gap: the current categorical UI has no game-selection
context. Do not show an unidentified game's result as whole-device readiness.
This needs a narrow selection/context contract before production presentation.
