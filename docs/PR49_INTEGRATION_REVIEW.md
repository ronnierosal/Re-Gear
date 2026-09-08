# Auto TDP stack integration review

Issue #34 / PR #49. Combined sources: main `482710f21310da0e096c154ceda2dbebfeba8ff8`
and published Auto TDP tip `49f7f1f000bd39843541004182d606b52df0618b`.
Both histories are retained by a normal merge; no rebase or force push.
PR #31 is closed as superseded by restacked telemetry. The other carried PRs
remain open until #49 is actually merged into main.

## Coordination and conflict decisions

The maintainer relayed the agreed order #49 -> #81 -> #82. The existing 0.3.56
trial artifact and its source pin remain immutable and independent of merge order.
This integration preserves main's 0.3.51 package metadata; it creates no release,
does not replace a staged artifact and makes no installed-build claim. A later
release requires a newly reserved version under the release-owner workflow.

Eleven conflict paths were resolved: notices, generated JS/map, current state,
index, handoff, work queue, main.py, package verifier, UI entry point and Decky
contract test. Main's current UI, offline classification, topology wakeup and
bounded unload behavior remain. Auto TDP's explicit controls, RPC contracts and
cancellation are added. TDP closes before observer cleanup; a close exception is
categorically recorded and does not prevent main's topology/sleep-guard cleanup.
Two combined unload regressions verify both paths. The generated bundle is rebuilt
from combined source. No older bundle is copied or hand-resolved.

The auto-merged RPC bindings are additive; existing bindings are retained. Product
wording keeps TDP in development and unvalidated. Documentation conflict resolution
preserves current-main and TDP evidence without upgrading historical checkpoints.
README/Wiki source from current main is retained; no public hardware claim or Wiki
publication is introduced. Claude-owned implementation paths are untouched.

## Combined command boundary review

One reviewer read the entire combined `commands.py`, not just its diffs, and found
no blocking composition defect. Existing shapes remain: validated per-user pw-dump
and wpctl set-default; fixed sleep-inhibitor helper; allowlisted systemctl scope
discovery; exact user daemon-reload/LoadState/Gamescope restart operations; and
root-only no-block system poweroff. Main's remaining-deadline PipeWire timeout
support is preserved. These paths retain their existing independent callers/gates.

Added by this merge: the fixed SteamOS Manager TdpLimit1 busctl reads for current,
minimum and maximum limits; DBus GetNameOwner; and the unsigned TdpLimit property
write addressed to a validated unique service owner. Root-or-session-user identity,
exact runtime/bus paths, sanitized environment, no shell, no service auto-start,
no interactive authorization, two-second bus/eight-second process deadlines and
late dispatch guards are retained. Setter success means accepted, not readback
verified. The shared transaction service owns all-register verification/recovery.
Eighty-nine focused command/transaction/audio/service/power/guard tests passed.
Accepted-output size limits are checked after capture and do not guarantee a
peak-memory bound; existing non-TDP internal error/environment behaviors are not
widened or presented as new guarantees.

## Approved development milestone — 2026-09-08

Safety invariant 9 (preserve known-good state or bounded rollback) governs the
TDP transaction's journal-before-dispatch, verified readback, conditional restore
and uncertain-result recovery. Invariants 3, 4, 11 and 12 provide relevant unknown
game/identity/no-override/redaction constraints. TDP does not migrate workloads,
switch display/GPU or change the display authorization of invariant 13.

Ronnie approved proceeding with this bounded manual power writer and opt-in Auto
TDP development milestone in response to the milestone/merge decision request:
"if its safe to merge then go ahead". The authorization is conditional on clean
code, passing verification and no unresolved conflicts with other agents. The
integration owner verified those conditions against main 482710f, the complete
combined command boundary, final-head CI and the agreed #49 -> #81 -> #82 order.
This records approval to integrate the reviewed implementation, not hardware
certification, deployment, release, or permission to bypass runtime safety checks.
The independent hardware-validation gates remain. Existing rollback coverage and
safety tests support invariant 9; no display/GPU authority is widened.

## Validation

Combined local matrix: architecture passed; 1,409 backend tests ran successfully
with 17 platform skips; compileall passed; 203 frontend tests passed; typecheck,
build and package checks passed. Two new tests cover combined unload behavior.
Generated-output reproducibility and both Linux CI runs passed at 56ff8ad.
The decision-only follow-up must also pass final-head CI before merging.
Local Windows tests do not replace skipped Linux behavior, native Decky rendering,
actual collection cost, profile thermal evidence or hardware readback/restore proof.

Reversibility: before a main merge, #49 can remain unmerged without changing main.
After an authorized merge, any code rollback must retain durable TDP recovery
records and be reviewed against intervening work; reverting source is not proof
that device limits were restored. No device state was changed by this integration.
