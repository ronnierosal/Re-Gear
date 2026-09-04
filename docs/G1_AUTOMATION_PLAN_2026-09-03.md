# G1 automatic lifecycle completion and event observation

## Goal

Make normal Ally X/GPD G1 attachment use the proven display/audio transition
without repeated success acknowledgements. Preserve deliberate Portable return,
failure handling, exact readiness, idle-game checks and shutdown-before-removal.
Use PCI/DRM events to invalidate observations, with bounded fallback polling.

The app already contains an unfinished lifecycle goal (reported blocked); it
refused creation of a second goal. This plan tracks the resumed local work and
does not claim the app goal was replaced or completed. The shutdown hang's layer
and cause remain unproven, irrespective of older goal wording.

## Hardware checkpoint before this change

On installed `1981259840ce`, the maintainer confirmed a manual switch to TV with
TV audio, then acknowledgement and Prepare G1 disconnect returned picture/audio
and usable controls to the Ally. These are user-observed successes for one idle
software cycle, not live removal or repeated reconnect certification. Automatic
docking previously reached readiness and hit a pending journal gate. No remote
runtime changes were made during the implementation below.

## Implementation milestones

1. **Local implementation:** retain one-shot/Portable suppression through partial
   identity (see [research application](G1_RESEARCH_APPLICATION_2026-09-03.md)).
2. **Local implementation:** reconcile only explicitly owned COMMITTED
   presentation journals against a fresh verified target/render/session/idle
   observation. Archive a bounded receipt before releasing the active journal.
   Unknown, failed, recovered, incomplete or foreign records are not auto-cleared.
3. **Local implementation:** a Portable receipt holds automatic docking across
   plugin reload and incomplete topology until host-verified absence without
   link/client/sleep-presence evidence. A new explicit manual TV request can still
   use the existing engine. Archive errors retain evidence and inhibit redocking.
4. **Local implementation:** Linux kernel PCI/DRM netlink invalidations wake the
   existing automatic observation loop. No event supplies hardware identity or
   mutation permission. Coalesce for 100 ms; bound each receive/drain; reject
   user-space sender IDs, truncated/invalid and unrelated messages. Fallback
   reconciliation is five seconds when subscribed; existing 250 ms readiness
   settling remains. Unavailable subscription falls back to the previous polling
   policy. Existing 15-second docked wait and five-second game wait remain but
   relevant events wake them early. Sleep protection/native recovery loops are
   deliberately unchanged: this is not elimination of all HDM polling.
5. **Local implementation:** existing categorical journey logs report observer
   startup/degradation and completion state changes. No raw uevent paths or
   identifiers are exported. QAM clears a stale presentation acknowledgement ID
   when the backend reports an idle active journal; no layout changes.
6. **Local integration verified:** 873 backend tests (six skipped), 69 frontend
   tests, architecture, compileall, typecheck, build, package and diff checks pass.
   Clean candidate packaging and separately supervised validation remain. Do not claim measured speed improvements
   or Linux netlink availability from synthetic tests.

## Completion semantics and rollback

`completed-presentation.json` is one root-owned bounded latest-result receipt,
not an unbounded history or a physical-removal permit. Receipt write/replace/fsync
precedes active removal. A crash leaving both copies is retryable. Retaining a
Portable receipt across an unobserved detach/reconnect can conservatively hold a
new attachment; the explicit manual switch remains available. Do not infer a
physical absence from a missing exact profile.

Only `transition.committed` / `transition.no_op` with matching requested/final
target qualify. Fresh render/display/session evidence must still match. Audio
continues through the existing handoff mechanism; this completion policy does
not turn default-sink selection into proof of audible output. Hardware testing
must confirm both directions again.

Explicit acknowledgement of a COMMITTED presentation also archives before
clearing, under the same service lock. This closes the race where a player
acknowledges Portable success before reconciliation and a reload loses its hold.
Failed/recovered acknowledgement behavior is unchanged.

Rollback is to the previous combined artifact, with the same powered-hardware
deployment boundary. Older code ignores the completed receipt and cannot provide
its durable Portable hold: disable automatic docking before an approved rollback
or test the rollback with G1 absent. Never deploy during a live transition.

## Supervised acceptance sequence

Give one physical action at a time and inspect after each confirmation:

- Verify exact installed candidate, detached Portable audio/control baseline.
- Enable automatic docking, attach G1; verify exactly one request and TV pixels,
  audio and root-readable render selection. Record readiness/request/result times.
- Verify success acknowledgement disappears without user intervention.
- Request Prepare G1 disconnect; verify Ally picture/audio/controls, no automatic
  redock, and shutdown-request control available without success acknowledgement.
- Complete normal shutdown and confirm physical poweroff before removal. If
  shutdown hangs, preserve evidence; do not call this milestone complete.
- Boot detached and reconnect for repeated cycles. Never intentionally live-pull
  as part of this acceptance sequence.

Failures remain diagnosable and explicitly acknowledged; no blanket success
clearance or repeated Steam restart loop is allowed.
