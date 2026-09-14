# Offline Game Mode tab: UI port

Status: **Headless model implemented and tested. Not mounted, not wired to
native Steam, and not scheduled — those belong to other owners.**

This document owns the seam between the Offline Game Mode tab and the rest of
the feature. The model is `src/offline-game-mode-model.ts`; its contract is
below. Verified against `847ba13` on 2026-09-14.

## What this is, and what it deliberately is not

The tab has three parties:

| Party | Owns | Not this |
| --- | --- | --- |
| **UI owner** | The visual tab, layout, icons, focus and navigation | Any state logic |
| **This model** | The typed state the tab renders, and the three actions it offers | Scheduling, persistence, native calls, view code |
| `offline-sync-workflow` | Real scheduling, persistence and native composition; pushes observations in | The shape the UI consumes |

The model contains no scheduler, no persistence, no native binding, no React and
no icon assets. It does not touch the existing automatic focused-tile checks,
which keep working exactly as they do today
([UI contract](OFFLINE_READINESS_UI.md)).

The offline centre state stays separate from the Auto TDP performance gear. This
model never produces a performance assessment and must not be fed one.

## Two rules the model exists to enforce

**Reads never act.** `getSnapshot()` and `subscribe()` cannot reach a port.
Rendering the tab, re-rendering it, or attaching a listener can never queue a
download. Only `syncNow()` and `setSyncSchedule()` call out, once per player
action.

**A command's return is never an outcome.** `ports.startSync()` returning
normally means the request was handed over — nothing more. Preparation state
moves only when an observation is pushed back in. A download that completes
still never proves the game launches offline.

## Snapshot

```ts
{
  loading: boolean          // true until applyInitialState resolves; never guessed
  available: boolean
  unavailableReason: string | null
  generation: number        // bumps on every selection change
  game: { appId, name } | null
  readiness: {
    status: "needs_preparation" | "likely_offline_ready" | "tested_offline" | "unverified" | null
    label: string | null
    reasons: readonly string[]
    checkedAt: number | null
    expiresAt: number | null
    expired: boolean        // computed from ports.now() at read time
  }
  schedule: { enabled: boolean, intervalMinutes: number | null }
  preparation: {
    state: "idle" | "requested" | "queued" | "active" | "completed" | "error" | "unconfirmed"
    content: readonly { type, hasUpdate, completed, bytesDownloaded, bytesTotal }[]
    errorCode: number | null
    inFlight: boolean
  }
  capabilities: { canSelectGame, canSyncNow, canSetSchedule }
}
```

Snapshots are **frozen and value-stable**: an unchanged model returns the very
same object, so a UI can compare by identity. An older snapshot is never mutated
in place.

`expired` is computed at read time rather than stored, so a tab left open goes
stale on its own without needing a timer.

## Preparation states

| State | Means |
| --- | --- |
| `idle` | Nothing requested for this selection |
| `requested` | The port was called. **Not** acceptance — Steam's download mutators return `void` |
| `queued` / `active` | Observed in Steam's download list |
| `completed` | Observed complete, and attributable to this request |
| `error` | Observed failure; `errorCode` is numeric, never Steam's unlocalized string |
| `unconfirmed` | The request produced no observable change in a bounded window. **Not an error** — a game with nothing to update lands here |

Per-content entries report `content`, `shader` and `workshop` separately. A
missing or unrecognised entry is `null`, meaning *unknown* — never a confident
"no update". There is no per-game shader download command in Steam's API, so
shader state is **observed**, never requested; see
[source review](OFFLINE_EVIDENCE_SOURCE_REVIEW.md).

## Events and results

| Call | Result | Port effect |
| --- | --- | --- |
| `getSnapshot()` | frozen snapshot | none |
| `subscribe(fn)` | unsubscribe function | none |
| `selectGame(game \| null)` | — | none; resets readiness and preparation, bumps generation |
| `syncNow()` | `true` if dispatched | `startSync(appId, generation)` exactly once |
| `setSyncSchedule(s)` | `true` if accepted | `persistSchedule(s)` once |
| `applyInitialState(s)` | — | none |
| `applyReadiness(o)` | `true` if accepted | none |
| `applyPreparation(o)` | `true` if accepted | none |
| `setAvailability(a)` | — | none |
| `dispose()` | — | none |

**Staleness.** `applyReadiness` and `applyPreparation` carry a `generation` and
an `appId`, and are dropped unless both match the current selection. Changing
game, or disposing, invalidates everything in flight.

**Duplicate suppression.** `syncNow()` while `inFlight` returns `false` without
calling the port. The suppression lifts on any terminal state, so a retry is
never permanently blocked.

**Expiry.** Only `applyReadiness` renews it. `applyPreparation` deliberately does
not: a finished download is not fresh evidence, and a longer sync interval must
never keep a stale positive badge alive until the next check.

**Honesty.** `loading` stays true until `applyInitialState` resolves, and an
injected schedule is reported exactly as given. The model never fabricates
readiness and never enables a schedule by itself.

## UI example

```tsx
const model = createOfflineGameModeModel(ports, { initial });

function OfflineGameModeTab() {
  const snap = useSyncExternalStore(model.subscribe, model.getSnapshot);

  if (snap.loading) return <Spinner />;
  if (!snap.available) return <Notice>{snap.unavailableReason}</Notice>;

  const { readiness: r, preparation: p } = snap;
  return (
    <>
      <StatusRow
        label={r.expired ? "Check again" : r.label ?? "Not checked"}
        tone={r.expired ? "neutral" : toneFor(r.status)}
      />
      {!r.expired && r.reasons.map((reason) => <Reason key={reason}>{reason}</Reason>)}

      <Button disabled={!snap.capabilities.canSyncNow} onClick={() => model.syncNow()}>
        {p.inFlight ? "Syncing…" : "Sync now"}
      </Button>

      {p.state !== "idle" && <PreparationRow state={p.state} content={p.content} />}
      {p.state === "unconfirmed" && <Hint>Steam reported nothing to do.</Hint>}

      <ScheduleControl
        value={snap.schedule}
        disabled={!snap.capabilities.canSetSchedule}
        onChange={(next) => model.setSyncSchedule(next)}
      />
    </>
  );
}
```

`useSyncExternalStore` works directly because snapshots are value-stable — no
memo wrapper is needed, and a render never dispatches.

Render `p.state` and `r.status` as distinct things. A green readiness label with
a failed preparation is a real and meaningful combination, and collapsing them
would hide it.

## Limitations

- Initial model delivery. **Not mounted, not native-proven**, and no device,
  install or release action is implied.
- The ports are unimplemented here by design. `offline-sync-workflow` supplies
  the real scheduling, persistence and native composition, and the native
  preparation adapter supplies the download observations.
- Nothing in this model, and no state it can reach, establishes that a game
  launches with no network. Supervised validation remains
  [issue 21](https://github.com/ronnierosal/Re-Gear/issues/21).
