# Pending TV request

When a player asks for their TV while the TV is switched off or its HDMI side
advertises nothing, Re-Gear records one bounded, non-authorizing request and
answers a single question per reading: is the exact TV they asked for there now?

This is the active half of issue #28. The passive half — a TV a previous dock
succeeded against coming back on while a dock is already in progress — is
`saved_tv` plus `SavedTvSearch`, which landed in PR #233 and is not repeated
here. The two share the remembered profile and nothing else.

The request carries an opaque request ID, the source, the exact eGPU identity it
was made against, and the remembered display identity and its grade. It carries
no connector, no card number, no bus address, no game identity and no transition
plan.

## States

Each is separately presentable, and only `ready` is an affirmative answer.

| State | Meaning |
| --- | --- |
| `waiting` | Recorded. A look finished and the TV was not there. |
| `unobservable` | The reading did not finish, or could not say which TV was meant. Not evidence of an absent TV, and it does not spend the budget. |
| `not_found` | The bounded search is over. Neutral, not an error. |
| `ready` | The exact requested TV is observed, external, connected and verified. |
| `rejected` / `cancelled` / `invalidated` / `none` | Lifecycle; nothing is waiting. |

## Rules

- The request names one panel. A request bound to a remembered EDID identity is
  a request for that panel. A request made with nothing remembered waits for
  exactly one verified, EDID-identified external display, and reports two
  candidates as `unobservable` rather than choosing a display for the player.
- A profile without EDID identity names a socket, not a panel. It ends the
  search on the first reading with `pending_tv.identity_not_verifiable`: that is
  a property of the record, so no number of further looks can change it, and a
  different TV in that socket would wear the same name.
- An unfinished look never spends the budget. A reader that keeps failing must
  not exhaust the attempts and abandon a TV that was there all along.
- Waiting is bounded, and `rearm` restarts the same request from zero without
  changing any authority.
- The request binds to the exact eGPU identity it was made against. A different
  or unidentified attachment invalidates it rather than re-pointing a display
  switch at a new dock's TV. A changed saved-TV record invalidates it for the
  same reason.
- The handheld keeps the session while no ready output exists. Nothing in this
  contract blanks a display, forces a connector, or invents HDMI readiness.
- A found TV and a running game stay independent. The domain is never told the
  game state; the coordinator reports `ready` with a `pending_tv.game_running`
  or `pending_tv.game_state_unknown` blocker beside it. Unknown game evidence is
  a running-game blocker, not an absent one.
- A ready arrival that cannot be offered does not end the request. If the TV
  appears mid-game the intent survives until the game closes.
- An automatic source cannot create a request. It has its own path, and letting
  it mint a player intent here would launder an automatic decision into a manual
  one and bypass the blockers the automatic path honours.

## Two recorded decisions

**A request does not persist across boots.** It is a live intent, not a standing
preference. The standing preference already exists and is already persisted: the
saved TV record. A request that outlived a reboot would move a player's display
on the strength of something they asked for in a session that is over, possibly
from another room. The coordinator therefore holds it in memory only and writes
nothing.

**A ready arrival needs renewed approval.** The handoff a `ready` resolution
produces is evidence, not an approval: a request ID, the attachment it was bound
to, the observation generation that saw the TV, and the exact display identity.
Display mutation is granted to supervised execution or to the explicit
profile-gated automatic path (safety invariant 13), and a request that sat
waiting is neither — the approval that would have covered it is short-lived by
design, and the player may have walked away. So:

- without the automatic-connection preference, `approval_offered` means the
  existing `preview_supervised_tv_switch` → `approve_supervised_tv_switch` →
  `execute_supervised_tv_switch` path may be *shown*. That path re-observes and
  asks the player for itself;
- with the preference on, and only for a request bound to an exact EDID
  identity, `automatic_continuation` says the arrival is eligible for the
  automatic path that already exists. `AutomaticDockCoordinator` still decides,
  under the latches it already honours — including the suppression that keeps a
  deliberate return to the handheld from being undone. This contract adds no
  authority to it.

Either way the one transition engine executes. There is no second execute route.

## Not in scope

Waking a TV, and forcing a modeset onto a connector without evidence, are a
separate researched capability. Nothing here implies either exists. A TV
switched on by hand reaches the same place.

## Verification status

Software only. The domain, the coordinator and the patched runtime call sites
are covered by unit tests against the repository's own snapshot fixtures. No
hardware behaviour is claimed: the hardware gates in issues #147, #161 and #201
remain open, and none of this has been exercised on a handheld or an eGPU.

## Runtime wiring handoff

`main.py` was claimed by another session while this landed, so the call sites
are handed over rather than applied: `docs/pending_tv_request_main_py.patch`
applies cleanly to `main.py` at `8c8eb89` and adds

- `payload["pending_tv"]`, a categorical status that keeps the requested display
  identity and its label behind the boundary the saved-TV status already draws;
- `_pending_tv_request()` over the same `SavedTvSearch`, so one read of the
  record answers both questions;
- `_update_pending_tv()`, called immediately after `_update_saved_tv()` and
  before the automatic-docking opt-in gate, so an explicit request is still
  serviced when automatic docking is switched off;
- `request_tv_when_available`, `cancel_tv_request` and `rearm_tv_request`;
- retirement of the request when a supervised TV switch actually succeeds.

The patched copy was exercised before handover — payload shape, waiting, late
HDMI, the running-game blocker, portable-return suppression, cancel, rearm, and
refusal without an exact eGPU identity all behave as specified, and no path
writes the saved-TV record. `tests/test_main_pending_tv.py` should land with the
patch, following `tests/test_main_saved_tv.py`: assert the payload carries no
display identity, that an absent TV reports `waiting` rather than a failure,
that a running game withholds the offer without losing the request, and that a
request is refused when no exact eGPU identity is resolved.
