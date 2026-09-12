## Problem

What user or engineering problem does this solve?

Linked issue / hub task (publish the issue link when remote access is available):

## Ownership and dependencies

Owner / agent / task:
Branch and base commit:
Claimed files or modules:
Overlapping PRs and agreed integration order (or evidence checked with none found):
Stacked base / prerequisite PRs:

## Backlog disposition

Canonical issue (`Closes` only for fully met acceptance; otherwise `Refs`):
Existing PR updated, or reason a separate PR/stack is needed:
Predecessors/duplicates to reconcile after merge (links and unique-work disposition):
Remaining work/hardware gates, owner and next action (or none):

## Approach

Describe the focused change and important tradeoffs.

## Source credit

Material external inspiration or reused code/tests/text/assets: project/author,
source link (pinned revision where available), affected feature and reuse type,
plus the credit/notice location. If none was used, say so. Follow
[source attribution](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SOURCE_ATTRIBUTION.md); do not claim independent
implementation solely because an AI wrote or rewrote it.

## Verification

List exact targeted and integration checks run, including failures diagnosed.
Include checks for other agents' affected behavior. Distinguish worker tests
from checks on the combined integration commit; CI must match the current head.

## Scope and evidence

### Golden behavior preservation

- Comparison base and candidate revision:
- Affected golden behavior IDs and shared dependencies (or explained none):
- Existing behavior preserved / intentional approved change:
- Golden gate result and added regression coverage:
- Independent review evidence for material golden-path changes:
- Hardware cases required before installation, evidence or pending owner:
- Rollback artifact, hash and configuration reference (or not applicable):
- Changes to golden tests/manifest/checker/CI, with preservation rationale:

Follow [golden behavior preservation](https://github.com/ronnierosal/Re-Gear/blob/main/docs/GOLDEN_BEHAVIORS.md).
No unexplained behavior changes or unresolved regressions qualify as golden.

Identify affected workflows/hardware and classify evidence as designed,
implemented, simulated, installed, hardware tested, or unknown. Note required
documentation changes and any separately owned hardware validation.
