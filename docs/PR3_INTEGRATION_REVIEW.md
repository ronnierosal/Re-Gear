# PR #3 historical runtime integration

Issue #34 owns reconciliation of source `cc1bab472740c0dc8886da09852065d400c88bd3`
with main `a9125a93c20c36ab9d135e745e2df566ef2ee10a`. Package metadata remains
0.3.51; this is not a new release or a current installed-build claim.

## Scope and conflict decisions

The original PR includes 207 files of runtime, UI, Offline Readiness, tooling,
tests and evidence. Runtime additions include event-driven readiness with polling
fallback, Portable holds, durable completion retirement, audio preflight and
bounded unload. It is not a branding-only patch.

Ten conflicts were reviewed individually. README and Wiki Home retain main's
newer public guidance. The live overlay retains the release's onSwitch API,
Decky DialogButton, compact layout and wrapping; main's older static mockup
would break the live API and controller regression checks. Two mode icons, four
offline badges and the Re-Gear icon retain intentional sharp release artwork.
Main's unrelated documentation and additional plugin PNG are preserved.

Historical status/Offline documents have private host/user-path details redacted.
Five legacy Windows dash bytes in CURRENT_STATE.md are normalized to valid UTF-8.
This does not rewrite published history. The frontend was rebuilt from the
resolved source with worktree-local frozen dependencies; generated files match
the existing release outputs without copying another checkout's artifacts.

## Checks and evidence limits

Architecture passed; 958 backend tests ran with six platform skips; compileall
and TypeScript passed; all 181 frontend tests passed; build and package checks
passed. Independent bounded runtime review exercised 81 focused tests without a
confirmed new blocker in inspected readiness, completion, audio and recovery
paths. Independent frontend review verified the API/controller/artwork decisions.
Linux CI must pass on the final PR head before a merge decision; issue/PR records
retain final results.

This is not exhaustive security review or hardware validation. No deployment,
service restart, physical test, or new player-facing ZIP occurred here.

## Other agents and later work

No later G1 experiments, Auto TDP implementations, or Claude PR implementations
were imported. Later 0.3.55/0.3.56 source does not silently replace this baseline.
The lineage preserved after closing #4 still needs separate integration review;
issue #24 remains open. Existing audio-parser restrictions predate this PR and
remain separate from the later audio stack.

Keep #33 coordination, #50 popup, #53/#61/#66/#72/#75/#82 runtime stacks and
Claude #84/#89/#97/#98/#99 separately reviewed. Refresh bases and overlapping
contract checks after an authorized main merge. Do not close descendants merely
because their base moved. Shared-main and release-owner worktrees are untouched.
PR publication is fast-forward-only; no force push, main merge, branch deletion
or release is included in this preparation.
