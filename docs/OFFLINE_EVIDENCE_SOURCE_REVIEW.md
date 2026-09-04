# Offline Readiness source review boundary

Status: **Implemented (pure review contract and candidate Steam overview
projection); live source validation and delivery required**

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
