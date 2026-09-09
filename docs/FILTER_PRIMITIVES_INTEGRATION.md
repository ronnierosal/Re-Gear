# Filter primitives integration

Refs #55, #58, #60, #69. This checkpoint integrates only the reusable filter
foundation into current main, alongside the device policy and restart-plan work.

## Included source

- #58, `5b03c2d306c7d42e877a82f47e1c08b4311ef607`: exact character-device
  compiler and experimental lifecycle contracts.
- #60, `0aaee8bdb2e449f5ef2e151eb2a7079c0ec7dc11`: BPF link loader, exact
  link/pin identity primitives, durable journal and owned pin-directory support.
- A combined policy/compiler regression checks the multifunction device set,
  denied access, unaffected neighbouring devices and rejected incomplete policy.

Only the focused source commits are integrated. Their historical release base,
older generated assets and later stacked runtime changes are not included.
The original branch heads are preserved for their dependent PRs.

## Contract for the next application service

`compile_device_filter` consumes the composed exact major/minor tuple.
`CgroupDeviceLink` supplies explicit load/attach/identity/pin/detach operations;
importing these modules activates nothing. Its caller must authenticate and hold
the intended cgroup descriptor. The loader itself does not grant that authority.

The legacy `LaunchBinding` and journal model still bind to the two original leaf
services. They MUST NOT be treated as authorization for a user-manager ancestor
attachment. Parent-scope authorization and recovery need a separately reviewed
contract before a production caller can arm that broader scope.

The existing #63 through #81 stack is not implicitly integrated or approved.
In particular the old per-service authentication and prepared launch paths do
not implement the broader scope exercised by the reported hardware experiment.

The next service must establish fresh exact attachment and complete device
evidence; authorize the target cgroup; serialize and journal ownership; verify
filter enforcement before approved restarts; rescan all relevant holders after
restarts; and preserve recovery on cancellation, timeout or owner failure.
An unpinned link disappearing when its owner exits is not durable recovery.
Neither a composed restart plan nor a clear client scan grants removal authority.

This integration adds no RPC, automatic activation, session restart, software
removal, deployment or physical-disconnect permission. The separate removal PR
and a supervised end-to-end application transaction remain further work.

## Validation and rollback

The integration PR records final-head CI, including architecture, backend tests,
Python compilation, frontend typecheck/tests/build and package checks. Local
Git preflight and whitespace checks complement CI; they are not hardware proof.
No new hardware run is part of this integration.

If rollback is required before dependent work lands, revert the integration
merge commit. Once callers depend on these modules, review those dependencies
before reverting. Do not remove or rewrite the original stacked branches.
