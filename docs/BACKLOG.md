# Backlog

This file retains detailed work-item history and acceptance notes. The ordered
cross-feature status and dependency plan is maintained in the
[authoritative roadmap](ROADMAP.md); deployment gates are maintained in
[Deployment and validation strategy](DEPLOYMENT_VALIDATION.md).

## Restore natural controller scrolling in Decky troubleshooting

**Status:** OBSERVED ON HARDWARE — deferred minor UX defect
**Target:** Controller-first UX hardening; does not block current safety or
hardware-discovery work

On the ASUS ROG Ally X in Gaming Mode, the Re-Gear troubleshooting panel can be
read with a mouse wheel, but upward travel using the D-pad or left stick does
not behave like ordinary scrolling. Focus can move too abruptly or fall through
to Steam's QAM Back control instead of progressing naturally through Re-Gear's
content. The explicit **Back to top** action works and remains an accessible
fallback.

The current Decky-native scroll-panel experiment did not correct this behavior.
Do not add a custom gamepad listener or synthesize mouse-wheel events as a
workaround: Re-Gear must remain Decky-native and must not interfere with Steam's
controller routing.

Acceptance requires supervised controller validation on the Ally X:

- D-pad and left-stick up/down traverse the troubleshooting content predictably
  in both directions without skipping to the QAM Back control.
- Mouse-wheel behavior remains usable.
- **Back to top** remains a reliable optional shortcut, not the only way to
  return upward.
- The fix neither changes Re-Gear safety state nor adds display, GPU, sleep, audio,
  controller, or process-control authority.

## Add guarded eGPU process closure

**Status:** DECKY FLOW IMPLEMENTED AND SIMULATED — supervised proof pending
**Target:** Milestone 0.2 after transition-journal and approval-token gates

Let a player resolve an otherwise idle disconnect blocker by closing only
backend-discovered processes that still hold resources belonging to the exact,
verified eGPU. This workflow does not make physical live unplug safe and cannot
bypass storage, identity, game-state, or protected-session blockers.

Implemented read-only foundation:

- Exact eGPU DRM and audio-node client discovery.
- Process-instance identity derived from PID plus process start time and the
  ephemeral eGPU identity, preventing a PID alone from becoming authority.
- Pure classification of Steam games, same-session user processes, protected
  SteamOS session processes, other-user/system processes, and unknown clients.
- Fail-closed disconnect readiness when process, storage, or identity evidence
  is incomplete.

Required mutation gates:

- A backend-generated preview containing only the exact eligible process
  instances; the frontend must never submit a PID, signal, command, or path.
- A short-lived, single-use approval token bound to the candidate set, eGPU
  identity, resources, and observation generation.
- Immediate revalidation of process start time, ownership, opened eGPU nodes,
  exact hardware identity, and storage state before every signal.
- A bounded `SIGTERM` phase followed by a fresh observation. `SIGKILL` requires
  a separate explicit **Force close remaining** approval and a second
  revalidation.
- Steam, Gamescope, Decky, display/session managers, root/other-user/unknown
  processes, and mounted-storage clients are non-overridable.
- A final full readiness scan that reports the real remaining blocker and never
  claims live removal is safe on the certified G1 profile.
- Structured audit events without command lines, private paths, raw PIDs, or
  stable hardware identifiers in exported diagnostics.

Implemented unattended-safe approval foundation:

- Backend-owned graceful/force preview policy for close-eligible same-session
  user processes only; preview rows expose no PID or process-instance token.
- Bounded, short-lived, single-use approvals bound to release phase, exact eGPU
  identity, complete client/resource fingerprint, eligible process instances,
  and observation generation.
- Mandatory fresh full revalidation rejects PID reuse, changed resources,
  changed client set, storage use, or changed eGPU identity.
- Force approval requires evidence of a prior graceful attempt, a new
  observation, and a remaining target subset; it cannot add processes.
- Decky exposes only exact enum/token operations; no PID, signal, command, path,
  or raw process-instance identity crosses the frontend boundary.

Implemented guarded-runner evidence:

- Typed graceful/force signal boundary plus a Decky-wired narrow Linux adapter.
- Mandatory fresh complete re-scan after every typed action and subset
  revalidation before every subsequent action.
- Deadline, missing/stale/incomplete scan, changed-client, remaining-client,
  signal-rejection, and already-exited-target paths.
- Identity-free bounded audit and an explicit distinction between cleared
  software blockers and hardware removal authority.
- Shared transaction-journal integration from request through terminal result,
  without tokens, process identity, or raw hardware identity.
- Guarded pidfd signal adapter with injected tests for the exact
  graceful/force mapping, process-start-time verification, absent process,
  permission/OS failure, missing pidfd support, and non-POSIX fail-closed
  behavior. There is no numeric-PID fallback. Decky can reach it only after
  redacted inspection, destructive confirmation, token issuance, and fresh
  exact revalidation.
- Delivery-independent facade with authority-free inspection, explicit
  single-use approval, fresh-sample execution, one-operation locking, durable
  recovery, and an opaque expiring receipt over private graceful evidence for a
  separate force approval.

Acceptance requires pure policy/token/replay/PID-reuse tests, adapter tests with
an injectable signal boundary, failure injection, and supervised Ally X/GPD G1
validation with disposable user-process fixtures. The public close RPC is now
implemented but remains unverified on hardware and has not been deployed during
unattended work.

## Improve eGPU and TV connection responsiveness

**Status:** IN PROGRESS — read-only responsiveness complete; transition mutation gated
**Target:** Milestone 0.2 transition-engine work

Reduce software-added latency when a verified GPD G1 and its connected TV
appear, without weakening Re-Gear's fail-closed identity, game-state, Gamescope, or
display verification.

Planned investigation and implementation:

- Add read-only timing instrumentation for the eGPU event, PCI/USB4 identity,
  DRM readiness, TV connector/EDID readiness, Gamescope and game-state checks,
  transition readiness, and verified final output.
- Replace the Decky panel's fixed three-second discovery delay with an
  event-driven or adaptive refresh path.
- Observe independent hardware and session state concurrently where snapshot
  consistency can still be proven.
- Separate the fast connection-readiness path from the more expensive
  disconnect-client and storage scan.
- Prepare the transition plan while hardware settles, then re-observe every
  safety-critical fact immediately before applying it.
- Perform at most one idempotent Gamescope transition and verify the live render
  GPU and active TV output before reporting success.
- Show progressive native UI states such as **G1 detected**, **TV
  initializing**, **Ready to dock**, and an exact blocker when readiness fails.

Implemented read-only slice:

- Privacy-safe per-stage and total snapshot timings.
- Non-overlapping adaptive refresh: 1 s while discovering or ready, 750 ms while
  idle evidence settles, 3 s for unknown game state or verified TV Docked state,
  and 5 s while a game is running. Explicit player refresh remains immediate.
- Progressive **Waiting for G1**, **G1 detected**, **TV initializing**, **Ready
  to dock**, **TV Docked**, and exact verification-blocked UI states.
- Five live end-to-end snapshot RPC samples on the attached certified profile
  measured 25–31 ms, showing that the old fixed refresh cadence—not observation
  runtime—was the dominant software delay. Concurrent source scans are deferred
  until instrumentation demonstrates a real need and a consistency proof.

The transition-planning, apply, verify, rollback, and supervised
Portable/TV-Docked work remains gated by the transition-engine milestone and is
not part of this read-only backlog slice.

Acceptance evidence:

- Before/after timing capture on the certified Ally X/GPD G1/TV profile.
- No persistent DRM card, connector, or PCI address assumptions.
- Running or unknown game state remains blocked when a Gamescope restart would
  be required.
- Failure preserves or restores the known-good Portable state.
- Supervised redacted Portable → TV Docked → Portable hardware validation.

The documented 4–6 second transition is reference behavior; native Re-Gear timing
must be measured before assigning a performance target. Physical USB4, GPU, and
HDMI/EDID initialization time is not bypassed with fixed sleeps.

## Add a privacy-safe support bundle

**Status:** IMPLEMENTED — device UI/save acceptance pending
**Target:** Before public multi-hardware testing

Give users a controller-friendly **Export Support Bundle** action so hardware
and SteamOS issues can be diagnosed without requesting unrestricted system logs.

Planned investigation and implementation:

- Add a bounded, rotating structured Re-Gear event log with timestamps, severity,
  stable event codes, component, operation stage, and an ephemeral correlation
  identifier.
- Include the current versioned diagnostic snapshot, recent Re-Gear events, blocker
  codes, hardware support/profile result, sleep-guard state, disconnect
  readiness, and Re-Gear/Decky/SteamOS/kernel versions.
- Record which exact profile rules passed or failed without exporting raw USB4
  identities, hardware serials, PCI bus addresses, DRM enumeration numbers, or
  private filesystem paths.
- Let the user preview the manifest and redacted contents before saving or
  sharing the bundle.
- Keep collection narrowly scoped to Re-Gear. Do not include the full system
  journal, Steam account data, arbitrary process command lines, IP addresses,
  usernames, or home-directory contents.
- Provide a native copy/save workflow and a clear bundle schema/version so
  reports can be parsed across Re-Gear releases.
- Add deterministic redaction and size-limit tests, including adversarial
  fixtures containing serials, usernames, paths, addresses, and raw hardware
  identifiers.

Acceptance evidence:

- A bundle created on the certified Ally X/GPD G1 profile contains enough state
  to explain an injected discovery, inhibitor, and disconnect-readiness failure.
- Automated tests prove forbidden private values are absent from every exported
  file and the manifest.
- Bundle size and retained-event count remain bounded after long plugin uptime.
- Export is read-only and cannot trigger a sleep request, process signal,
  display/GPU transition, service restart, or hardware removal.
- The user can inspect the bundle locally before choosing whether to share it.

Implemented software evidence:

- 128-event rotating structured in-memory log and 256 KiB encoded bundle cap.
- Allowlisted reduced snapshot, categorical profile checks, observation timings,
  and Re-Gear/Decky/SteamOS/kernel versions.
- Exact JSON preview plus copy action; saving requires a five-minute single-use
  token and accepts no path or filename from the frontend.
- Exclusive, no-follow fixed Downloads writer for the Decky user home.
- Deterministic adversarial privacy, size, token expiry/replay, rotation, version
  allowlist, exact-byte save, collision, and path-boundary tests.

Controller-visible preview/save acceptance remains pending. The installed
visible-parent correction is documented, but no support bundle file was created
on the Ally without player review.
