# Prepared-session trial configuration and owner state

This review slice tracks [issue #55](https://github.com/ronnierosal/Re-Gear/issues/55).
It extracts existing implementation from 30fc314, 95c771f, 65773f9 and cc74059.
No new hardware action or activation is introduced by this publication.

The setup controller records owner intent before suspending the exact managed
legacy override, applying a designated root-owned drop-in, publishing the arm,
and requesting a user-manager reload. Each durable phase precedes its matching
mutation. A recorded scheduling phase must recover instead of replaying setup.

The drop-in store preserves exact original bytes and rejects reused trials. The
legacy store quarantines only the two known managed overrides, with a root-only
record on the same filesystem before the rename. User-owned ancestors remain a
limitation: replacement or missing paths can require manual recovery. Neither
store starts or stops sessions.

Rendered drop-ins reset ExecStart only and retain native hooks and environment
files. Owner records bind the candidate to the runtime, user and exact arm.
A restart-requested record remains explicitly unverified.

This is a library/setup slice. It does not install a runtime, provide a startup
recovery dispatcher, execute a session restart, grant a filtered launch, release
GPU resources, or establish safe physical disconnect. Higher-level recovery and
supervised hardware observation remain separate integration requirements.

Validation on the isolated runtime PR base: 1,410 backend tests passed (68
platform skips), architecture and compilation checks passed. Linux filesystem
fixtures are included but were skipped on this Windows host. No deployment or
hardware run was performed for this slice.
