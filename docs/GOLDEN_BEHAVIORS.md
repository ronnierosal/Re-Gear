# Golden behavior preservation

Golden protects demonstrated behavior, not source bytes. Refactors, fixes and
improvements are welcome. A green general suite alone is not golden clearance.
Never delete, skip or weaken a behavior assertion merely to accommodate a change.

## Baseline and evidence

The initial hardware reference is the narrow
[0.3.82 automatic-TV checkpoint](EGPU_0382_CHECKPOINT.md): source
`09ff57128ca6e0526f4b5376af825d87557c0f2e`, immutable `Re-Gear-0.3.82.zip`,
SHA256 `c27e48366daa4374d49d02128e40c27e038cafa87488dcf449b3863b1841b06f`.
Its three supervised trials cover idle attach, clean boot then attach, and one
TV's standby behavior, with picture, audio and controls confirmed. They do not
prove genuine missing HDMI/EDID, all reconnect cases, running-game recovery,
second-attempt hardware behavior, or live physical unplug safety.

The [v0.3.92 release](https://github.com/ronnierosal/Re-Gear/releases/tag/v0.3.92)
and `checkpoint/0.3.92-auto-tv` resolve to
`6c638a81607bd2b16f9976cc3d6723b00dfe34c7`. The later checkpoint annotation says
user-verified automatic TV; the release text still calls recovery untested.
Until exact installed provenance, settings and trial evidence are reconciled,
retain 0.3.82 as the documented hardware reference. Neither version freezes
main or requires reverting improvements. Compare behavior, including safety
fixes made after the checkpoint, rather than copying old code back.

## Executable contract

[`contracts/golden-behaviors.json`](../contracts/golden-behaviors.json) maps stable
behavior IDs to concrete unit tests, affected source patterns and supervised
hardware cases. The manifest identifies the historical hardware reference;
the tests run against the current candidate. It is an initial coverage set,
not certification of every feature in Re-Gear.

```text
python scripts/check_golden_behaviors.py
python scripts/check_golden_behaviors.py --base origin/main
```

The gate validates the manifest and executes every named golden test. Missing
tests, empty suites, skips, expected failures, failures and errors fail the gate.
`tests/test_golden_behaviors.py` executes the real manifest during normal unittest
discovery, so the existing required `foundation` CI check enforces this gate
without a separate optional workflow. The optional base
reports affected contracts; it never narrows test execution. Source patterns
are review aids, not proof that an unlisted dependency is harmless. Review
shared services, settings, lifecycle, startup/unload and feature interactions.
Run the full integration matrix in [Development](DEVELOPMENT.md) as well.

When renaming or replacing a test, preserve its behavioral assertions and update
the mapping in the same PR with an explanation. Changing the intended behavior
requires an explicit product decision, replacement acceptance evidence and a
baseline migration record. Do not manufacture a pass by updating expected
outputs to an unexplained regression. Review contract/test/checker/workflow
changes as changes to enforcement itself.

## Every candidate review

1. Record the exact candidate revision and comparison base; identify affected
   golden IDs and indirect dependencies. Explain changes to existing behavior.
2. Add a failing reproducer for a demonstrated defect, then verify the fix and
   the successful journey. Include timing and state changes between eligibility
   and dispatch where operations can disrupt a session.
3. Run golden checks and the applicable full matrix on the combined candidate.
   Reassess and rerun applicable checks when the integration base changes. Use
   final-head CI and branch protection; independent branch passes do not prove
   the combined candidate.
4. Obtain independent semantic review for material golden-path changes. The
   reviewer reports exact revision, findings, checks and remaining limits. An
   agent review is evidence, not a GitHub approval identity or a bypass.
5. Record one verdict: **software gates passed**, **regression blocked**, or
   **hardware validation pending**. Missing required evidence prevents golden
   clearance. Passing software gates permits routine repository integration
   under existing policy; it does not authorize replacing a working install.

For hardware-affecting changes, repeat affected supervised cases under
[deployment validation](DEPLOYMENT_VALIDATION.md) before replacing the working
installation. Preserve an installable rollback ZIP, its hash and configuration
instructions. Installation, settings restoration and device readback are
separate steps. Keep live-unplug clearance separate from automatic-TV success.

## Promotion and ownership

A promoted baseline records source revision, immutable artifact and hash,
installed readback, relevant OS/kernel and settings, exact scenarios, results,
limitations and rollback steps. Retain the previous artifact. A tag, version
number or CI success alone cannot promote a hardware baseline.

This task owns independent regression acceptance; implementing tasks retain
their code ownership. Track blockers in the shared hub and coordinate overlaps
before editing. CI executes when the agent is inactive; no promise of continuous
agent monitoring is implied. Required checks and protection settings are the
repository enforcement boundary, while semantic and hardware review remain
separate evidence. Existing baseline work stays in
[issue #300](https://github.com/ronnierosal/Re-Gear/issues/300), which remains open
until its broader hardware and preservation acceptance is met.
