# Dock power inhibitor handoff

Contract proposal reviewed against `d9d0ce9a06810b85c29fca0e77049ccf942af872`.
This supplements [DOCK_POWER](DOCK_POWER.md); it does not enable sleep or supply
hardware evidence. Only the existing power coordinator may consume the original
request. No parallel executor, software reconnect, reauthorization or PCI rescan
is proposed.

## Existing executable boundary

`SleepGuardController.reconcile` acquires for PRESENT, releases for ABSENT and
holds for UNKNOWN. Its lock protects only its own lease. `close()` is terminal:
later reconciliation cannot reacquire. Directly releasing its lease is also not
a handoff: the next PRESENT sample acquires again.

`Plugin._run_whole_dock_trial` acquires a second Login1 lease, stores it in
`_whole_dock_trial_lease`, and retains it once the runtime owns an operation.
Releasing the background guard therefore cannot make this path sleepable.
`DockPowerCoordinator` has no inhibitor handoff callback; delivery rejects sleep
before calling it. Submission errors remain consumed, preventing automatic replay.

The process-backed lease is not durable inhibition across plugin death. A durable
dock claim prevents a new application mutation but does not itself block logind
sleep. Reacquisition after restart is a separate capability requirement.

## Proposed change for the owning production agent

Extend the existing guard with operation-bound temporary handoff and finish/abort
methods, distinct from terminal `close`. Add a small coordinated lease owner at
the existing power continuation seam, not a new teardown executor. It must own
both the background guard pause and retained transaction lease, with one lock
order shared by reconcile, cancellation and unload. Never expose a boolean
"ignore inhibitors" setting or use `sleep_supported=True` as implementation.

An immutable handoff token binds original operation/action/session/deadline,
attachment identity/generation, verified-down evidence and both lease owners.
No caller may substitute a new power request after the initiating UI disappears.
The journal must record handoff state separately from once-only intent consumption.

| Boundary | Required behavior |
| --- | --- |
| Before release | Keep both leases active; require exact capability/profile, idle Portable state, current ownership, complete same-attachment evidence and unexpired original sleep intent. |
| Handoff prepared | Pause background reconciliation for this token; retain both leases until original intent is durably consumed and evidence is rechecked. |
| Release and submit | Verify both releases; submit only the consumed original request through the existing power coordinator. A failed/ambiguous release must not submit. |
| Cancel before consumption | Resume reconciliation and verify reacquisition of both required leases; no power call. |
| Cancel/failure after consumption | Reacquire and verify protection; retain consumed intent and dock claim. Never replay submission or automatically reauthorize. |
| Ambiguous submission | Reconcile actual platform sleep/resume state under the same operation. Do not claim either completed sleep or definite cancellation from a missing response. |
| Reacquisition failure | Keep durable recovery-required state, refuse further automatic operations, and report protection unverified. A stored flag is not proof of an active inhibitor. |
| Unload/crash | Never replay original power intent. Process-local leases may disappear; a supported implementation needs independently verified continuity/recovery protection. |

An operation-aware platform sleep observer and reversible guard pause are missing.
The existing fixed poweroff adapter is not a suspend/resume contract. These are
the smallest production seams to add and fault-test before considering enablement.
Application admission alone cannot serialize an unrelated OS sleep request.

## Wake without software reconnect

Wake means verified host/Portable operation while the same dock remains
deauthorized. Restore/verify inhibition before normal lifecycle reconciliation,
observe attachment and storage state afresh, and keep the durable dock claim.
Do not call reconnect, authorize, rescan, or turn on enclosure power. Unexpected
authorization, missing identity, replacement attachment or failed observation
enters recovery-required state; it never authorizes repair automatically.

No currently verified profile establishes that this state is reachable on wake
without platform firmware reconnecting the dock. No repository fixture proves
enclosure power removal or acceptable heat while deauthorized. If the enclosure
stays powered and violates the user's thermal requirement, software sleep cannot
satisfy the requested workflow; retain unavailable status until an independently
supported physical/power-isolation mechanism exists.

`DISCONNECT_BEFORE_SLEEP_VERIFIED` describes canonical physical removal, not
still-cabled deauthorized sleep. These capabilities must never share an enabling
flag. Hardware operations and heat-producing reconnect trials remain excluded.

## Offline coverage and remaining gates

`tests/test_dock_power_inhibitor_contract.py` exercises actual guard, lease,
delivery and coordinator seams with fake processes: independent lease ownership,
background reacquisition, terminal close, refusal of a forged sleep request, and
once-only ambiguous submission retaining protection. It does not implement or
claim a successful handoff.

Production follow-up needs interleaving/fault tests for every table boundary,
release/readback failures, deadline expiry, competing operation, unload and resume.
Physical proof remains required for inhibitor continuity, platform wake without
reauthorization, same-attachment identity and enclosure thermal/power behavior.
