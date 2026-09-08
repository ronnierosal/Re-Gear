# Game compatibility catalog

Re-Gear records eGPU handoff and save/sleep behavior as two independent dimensions.
A game may render correctly on an eGPU while its save-on-exit behavior remains
untested, or the reverse.

## eGPU handoff statuses

- Untested
- Verified
- Verified with workaround
- Falls back to iGPU
- Known issue
- Unsupported

## Save and sleep statuses

- Untested
- Verified triggerable autosave
- Verified save on graceful exit
- Graceful exit verified
- Manual save recommended
- Manual save required
- Unsafe or unknown

## Promotion gate

Passive telemetry and simulator results cannot change catalog status. Every
non-Untested status requires a separately identified intentional hardware test,
human review, an exact handheld/eGPU profile match, Re-Gear and SteamOS versions,
an exact catalog game/AppID match, and a timestamp. A Verified eGPU result additionally requires an observed
external rendering GPU; it cannot be inferred from launch success. Save claims
must match the exact reviewed save outcome.

Evidence is single-use within each dimension; one intentional test report may
support both independent dimensions when it contains both exact outcomes. The
bounded promotion history preserves which dimension changed without storing
process details, account identity, or private paths. The schema is currently
pure policy plus a dormant fixed-path local store: it does not collect tests,
expose a Decky RPC, publish results, or modify launch behavior. The store
accepts only domain-validated records, rejects corrupt/unknown schemas and
catalog-history regression, writes atomically beneath an application-owned
state root, and never accepts a frontend-selected path or raw JSON. A
backend-only transaction service can register an untested entry or apply one
domain-approved reviewed-evidence promotion under the store lock. It neither
constructs evidence nor performs review, and is not instantiated by the
production Decky plugin.

Evidence cannot be reused across games: both the catalog record identity and
Steam AppID (when present) must match the reviewed test evidence exactly.

## Read-only game identity foundation

The SteamOS scope parser extracts a Steam AppID only from exact recognized
legacy/current Steam unit names. Duplicate scopes for the same AppID collapse to
one identity. Multiple AppIDs, a future unparsed Steam scope, query failure, or
no game keeps the active AppID unknown. The result is internal only: the public
snapshot schema and support bundle do not expose it yet.

The guarded sleep child may bind a short-lived approval to one exact AppID and
its exact scope set, then request close only through an injected narrow
mechanism after a newer matching observation. It grants no relaunch, save, or
GPU-selection authority, and no production close mechanism is wired. The
AppID/scope identity is intentionally excluded from the transition journal.

`Verified triggerable autosave` is still only a catalog capability. Runtime
save authority additionally requires a backend-owned recipe for the exact
AppID/host/eGPU tuple and a separate proof adapter capable of observing a new
verified save result. The guarded child is implemented and simulated, but the
production registry is empty and no proof or mechanism adapter is wired. See
[Verified game-save child](GAME_SAVE.md).
