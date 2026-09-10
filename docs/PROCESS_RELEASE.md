# Guarded eGPU process-release contract

Re-Gear may eventually help close ordinary same-session user processes that retain
exact G1 resources. This is a software-blocker workflow, not proof that physical
eGPU removal is safe.

## Eligibility

Only a backend-discovered process classified as `user` and `close_eligible` may
be targeted. Steam games, Gamescope, Steam, Decky, display/session services,
root, other-user, system, protected, unknown, and storage clients are never
eligible through this workflow.

The preview is generated from one complete observation with exact eGPU identity
and no mounted/swap storage. It shows bounded process names and categorical
resource kinds, but no PID, process-instance token, command line, path, or raw
hardware identity.

## Approval and revalidation

An approval is:

- short lived, bounded, and single use
- bound to graceful or force phase
- bound to exact eGPU identity and observation generation
- bound to the complete client/resource fingerprint
- bound to exact PID-plus-start-time-derived process instances internally

Consuming a token is not authority to signal immediately. Re-Gear must collect a
new complete observation and prove the exact facts are unchanged. Before every
subsequent signal it must prove the remaining clients are only a subset of the
approved facts. After every signal it must re-scan immediately. PID reuse, a new
client, changed resources, storage use, incomplete scans, stale generation, or
changed eGPU identity stops the operation.

Re-Gear keeps semantic generation and scan freshness separate. Approval and target
facts remain bound to the semantic client fingerprint, while the process runner
requires a different per-scan sample ID before the first signal and after every
signal. An unchanged semantic snapshot can therefore be freshly observed
without weakening the exact-client checks.

Force approval is a second flow. It requires a recorded prior graceful attempt,
a post-graceful observation, and a target set limited to remaining previously
attempted instances. It cannot add a process.

## Implementation status

The deterministic runner implements:

```text
approval
  -> fresh exact revalidation
  -> one typed signal request
  -> mandatory fresh re-scan
  -> revalidate remaining subset
  -> repeat or stop
```

It covers graceful and force actions, already-exited targets, signal rejection,
deadlines, stale or missing scans, changed clients, incomplete evidence, and
remaining blockers. Its privacy-safe audit contains sequence, phase, categorical
event/outcome, target ordinal, and resource kinds only.

The runner can now persist the shared bounded transition journal through the
real journal port from request, observation, validation, and plan through every
step and terminal commit, block, or failure. `step_started` is durably saved
before the signal port is called. A persistence failure before that event sends
no signal; a later failure leaves enough durable state to require recovery. The
journal contains only categorical codes and observed placement; it does not
contain approval tokens, PIDs, instance IDs, process names, eGPU identity, or
commands.

Restart recovery never repeats or escalates a signal. It terminalizes any
incomplete process-release journal as Action Required using a fresh placement
observation when available, then requires exact operation acknowledgement
before another release can begin. It first verifies the journal's
`process_release.requested` owner marker; a sleep or other foreign journal is
left byte-for-byte untouched and reported as a blocker.

A delivery-independent guarded facade now joins observation, inspection,
approval, execution, persistence, and recovery. Read-only inspection returns
the same redacted target rows but never creates a token. Explicit confirmation
creates a short-lived single-use approval, execution collects a fresh sample,
and one in-process lock prevents overlapping requests. When an attempted target
remains, a graceful result returns only a bounded, expiring opaque receipt. The
receipt store retains private backend evidence for a separately inspected and
approved force phase; process-instance identities never enter the public value.
The force candidate remains limited to instances actually signaled during the
graceful phase, and issuing force approval consumes the receipt.

The Decky payload mapper is now implemented independently of runtime wiring. A
preview contains only bounded process names, resource categories, counts,
blocker codes, and an optional approval token. An execution contains only
categorical status, counts, an acknowledgement ID, and the optional opaque
force receipt. It excludes audit events, PIDs, process-instance IDs, exact eGPU
identity, and target identity. Journal status similarly exposes only the exact
opaque operation ID needed for acknowledgement.

Even when every observed software blocker is cleared, the result exposes
`software_blockers_cleared=true` and always keeps
`hardware_removal_authorized=false`. The certified G1 profile still requires
shutdown before disconnect.

## Remaining gates

- validate with disposable processes under direct supervision
- preserve the independent G1 teardown/removal prohibition

A narrow Linux adapter is implemented and unit tested with injected pidfd and
identity boundaries. It opens a pidfd, verifies the process start time captured
by the approval, and only then sends a typed graceful (`SIGTERM`) or force
(`SIGKILL`) action through that pidfd. It has no numeric-PID fallback: missing
pidfd support, changed/unavailable start-time identity, non-POSIX execution,
permission failure, or OS failure stops categorically. It performs no wait,
retry, target discovery, or escalation. Decky constructs it only behind the
guarded service, root-owned journal, exact enum/token RPCs, and
controller-native destructive confirmation flow. Runtime capability preflight
blocks inspection before consent if that exact-instance mechanism is absent.

The Decky flow is implemented and simulated but not hardware validated. It
supports inspection without authority, explicit graceful approval, a separate
force confirmation through the opaque receipt, terminal acknowledgement, and
startup no-repeat recovery. It remains experimental until supervised
disposable-process validation passes.

The same runner also supports a delivery-independent canonical-sleep child
mode. Its approval binds the backend-owned parent operation ID; the frontend
cannot provide that ID. Each target is recorded as a bounded, identity-free
substep in the active sleep journal before the pidfd signal and verified after
the mandatory rescan. Graceful evidence and force receipts cannot cross sleep
transactions. Child mode never creates or commits a second journal and is
bounded to 26 targets to reserve full journal capacity for verified save,
graceful plus force release, sleep completion, and recovery.
This composition is simulated and remains unwired from Decky sleep requests.
