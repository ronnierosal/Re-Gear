# Current evidence and development state

The eGPU lifecycle reference is the narrow [v0.3.98 checkpoint](egpu-lifecycle.md),
not the old 0.3.95 failure and not the latest UI package number.

## For players — no technical background needed

One supervised disconnect, physical unplug and replug cycle succeeded. That does
not establish repeatability, other hardware or sleep. Read the
[eGPU guide](../player/egpu.md) for practical limits. New UI builds can have different
controls; a built test candidate is not automatically installed or supported.

## Technical details — for advanced users and contributors

The [current-state authority](../../CURRENT_STATE.md) retains the dated sequence
and links later evidence. [Power implementation](../../EGPU_POWER_NEXT.md) separates
merged backend/coordinator code from mounted integration and hardware acceptance.
[Golden preservation](../../GOLDEN_BEHAVIORS.md) keeps the 0.3.98 cycle and earlier
0.3.82 automatic-TV evidence, without treating either as universal qualification.

At the September 14 review, UI PR329/0.3.107 was a built test candidate, not a new
hardware baseline. PR333/334 power consumer/producer work was separate. Follow
the owning PRs and exact revisions rather than inferring capability from version
ordering. Historical point-in-time records are in the [archive](../../archive/README.md).
