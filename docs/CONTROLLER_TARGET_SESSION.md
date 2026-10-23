# Inert controller target session

Task: #511. This is an unconstructed fixture service, with no native reader,
writer, RPC, UI hook, production import, startup worker or persistent recovery.
It does not establish supported installed setter IDs or hardware acceptance.
The frozen four-fact public controller catalog is unchanged.

## Evidence and authority

`TargetSession` requires an injected reader, writer, monotonic clock and reviewed
type allowlist. Tests use fictional categorical IDs. A `Frame` supplies one
explicit composite binding, provider/bus epoch, generation, affirmative current
Re-Gear settings-management authority, complete original setter-type tuple,
verified supported types and composite compatibility. Unknown evidence fails
closed. Provider ownership, Polkit access, process absence, distro and marketing
names confer no settings-management authority. OS/Bazzite/OGUI or another
manager must be represented as passive authority, never Re-Gear authority.

Admission requires literally true complete/identity/visible/exactly-idle flags,
valid finite time and evidence younger than ten seconds. The injecting owner
must advance generation for game/session changes and invalidate authority and
epoch on withdrawal or reconnect. A future live adapter must establish coherent
evidence and atomic admission semantics; this fixture does not solve native
time-of-check/time-of-use races.

Choices intersect verified daemon IDs, reviewed allowlist and composite
compatibility. Duplicate/conflicting catalogue entries or compatibility IDs,
unknown baseline types and anything other than one gamepad occurrence fail.
Auxiliary occurrences may repeat: their order and multiplicity are preserved.
Both selected and original gamepad must be reviewed compatible choices. No IDs
are derived from object paths or labels. Setter IDs use a bounded categorical
syntax; syntax alone is never proof of installed support.

## Transaction

`stage(composite, target)` changes local selection only. `prepare_apply()` reads
fresh evidence and mints a private immutable request with the complete original
tuple and a single-slot replacement. `dispatch(request)` accepts only the exact
pending object from that session, consumes it before callbacks, and rechecks
binding, baseline, authority, generation, supported catalogue and compatibility
immediately before calling the injected writer. Requests expire ten seconds
after preparation starts, including read time. Concurrent and callback-reentrant
operations fail immediately with `RuntimeError`; invalid admission raises
`ValueError` without a setter call.

Only `Dispatch.REFUSED` explicitly guarantees no submission. It permits a new
Apply request; the old request cannot be replayed. Writer exceptions, timeouts,
late returns and unrecognized results are uncertain and require recovery.
Rollback evidence is captured before submission and is retained on uncertainty.
`SUBMITTED` yields `requested`, never effective. A separate `verify()` requires
fresh valid identity/authority and the exact issued tuple to yield `effective`.
Mismatch or unavailable readback yields `recovery_required` and retains evidence.

`prepare_restore()` requires current identity/authority, unchanged type evidence
and observed targets exactly matching this transaction's issued tuple. A Restore
request replays only the captured complete original tuple. Dispatch is checked
again and yields `restore_requested`; separate verified original readback yields
`restored` and retires rollback evidence. External changes, authority withdrawal,
provider/composite/generation replacement or ambiguous dispatch prohibit blind
rollback, rebinding and retries. Recovery-required is terminal for this session.

`close()` is the fixture contract for B/close/unload: invalidate pending work and
make at most one guarded Restore submission. It does not claim completed cleanup;
`restore_requested` still needs separate readback. Inadmissible/failed cleanup
remains recovery-required. Before submission, close is local and closes the
session. There is no background work, restart-time recovery or saved state.

Ports receive deadlines and must honor them. The service rejects expired reads
and late writer completions but cannot interrupt an arbitrary blocking injected
call. No hard native timeout or teardown guarantee is claimed. A future runner
must provide independently reviewed bounded execution and lifetime management.

## Exact-candidate software checklist

1. Run both `test_controller_target_session.py` and
   `test_controller_target_restore.py`: tuple preservation, passive authority,
   expiry and identity replacement, singleflight/reentrancy, uncertain submission,
   separate readback, takeover and failed restoration must pass.
2. Run architecture, golden behaviors, full backend tests, compileall and diff
   checks. Obtain independent review and required CI for the exact head/base.
3. Confirm only the six issue paths changed and no production caller constructs
   the service. Rollback is a source revert; no device rollback is implied.

Later live work remains separately owned and gated: exact installed setter IDs
and complete baseline, affirmative management/withdrawal semantics, independent
recovery input, reviewed native procedure, lifecycle/RPC through #464 and
presentation through #476. No source-profile edit, interception, input injection,
ordering/suppression, native probe, device operation or package change is included.

Documentation impact: Wiki after separately reviewed integration. This file is
the technical contract; it makes no player-visible or hardware readiness claim.
