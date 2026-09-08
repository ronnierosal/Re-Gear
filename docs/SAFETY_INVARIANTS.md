# Safety invariants

These invariants are release gates, not preferences.

1. A running game stays on its current GPU. Re-Gear does not attempt live GPU
   workload migration.
2. A transition that requires restarting Gamescope is blocked while a game is
   running.
3. Failure to determine game state is treated as a running-game blocker.
4. GPU mutation requires one exact, verified hardware identity. Ambiguous,
   changed, incomplete, or missing identity fails closed.
5. DRM card numbers, connector suffixes, and PCI bus addresses are observations,
   never persistent identity.
6. A connected connector is not proof that it is the active display. Nor is the
   compositor no longer preferring a connector proof that it is inactive: a
   connector can stop being preferred while a mode is still committed and it is
   still scanning out, still holding its GPU's resources. An inactive display
   may be reported as verified only when the connector's own mode state says it
   is not driving one. Recorded 2026-09-08 with issue #141; this tightens the
   grade of `external_display_active`, which removal safety requires verified
   false, and it may make that gate decline where it previously passed.
7. A requested transition is not complete until live render GPU, output target,
   Gamescope state, and user-visible readiness are verified.
8. An already-satisfied request is a no-op and must not restart Gamescope.
9. Failure preserves the current known-good state or executes a bounded rollback.
10. The tested Ally X/GPD G1 combination does not support physical live unplug.
    Restore internal operation and shut down before disconnecting it.
11. No normal-use force override may bypass running-game, identity, or unknown-
    state blockers.
12. Diagnostics redact hostnames, addresses, home paths, hardware unique IDs, and
    other user identifiers by default.
13. Display mutation requires either supervised execution or an explicit
    persistent player opt-in to the exact profile-gated automatic path. Hardware
    experiments always require redacted before/live/after evidence.
14. Suppressing a warning never suppresses its underlying safety check,
    inhibitor, approval, or audit event.
15. Process termination targets only backend-discovered users of the exact eGPU
    nodes. The frontend cannot provide arbitrary PIDs, signals, commands, or
    paths.
16. Graceful process closure and force closure are separate approvals. PID start
    time, eGPU identity, and opened nodes are revalidated immediately before a
    signal is sent.
17. Re-Gear never force-closes Gamescope, Steam, Decky, display/session managers,
    mounted-storage clients, or unknown/system processes to make disconnect look
    safe.
18. A sleep inhibitor is released when its verified hardware condition ends or
    the plugin unloads. The plugin must not leave a permanent inhibitor after a
    crash.
19. Steam sleep requests are blocked before Steam prepares the session for
    suspend whenever G1 presence is required, loading, stale, unavailable, or
    unknown. A missing frontend preflight is a critical degraded state, never
    evidence that Sleep is safe.
20. **Safe to disconnect** requires a profile explicitly verified for live
    removal plus independent verified render/display readiness and complete
    client/storage evidence. Clearing software clients alone is insufficient.
21. A pending original sleep request is continued only after expected removal
    and Portable recovery are verified and before its deadline. Expired,
    cancelled, unexpected, or out-of-order flows remain awake.
22. A raw eGPU/display topology event never authorizes sleep. It may start
    recovery; only the exact canonical sleep transaction may later continue its
    bound, unexpired original request.

The first milestone is read-only. The approved 0.2 sleep guard is an ephemeral,
crash-released lease governed by its documented lifecycle state machine.
Guarded 0.2 process release requires its root-owned durable journal, exact
approval, fresh revalidation, mandatory re-scan, protected-client exclusions,
and separate force confirmation. Supervised disposable-process proof remains a
certification gate. Display/GPU mutation still requires its independent durable
transaction, rollback, and hardware gates.
