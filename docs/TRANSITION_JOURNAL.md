# Durable transition journal

Re-Gear's transition journal is the crash-recovery authority for future mutating
operations. It records what was requested, observed, validated, planned,
attempted, verified, recovered, and committed. It does not infer success from a
mechanism call.

## Schema and privacy

The immutable schema is versioned and bounded to 128 entries. Entries have a
contiguous sequence, categorical event/code/details, workflow phase, observed
placement, and timestamp supplied by the caller. Invalid event order, unknown
fields, private/free-form details, post-terminal appends, and over-bound history
fail closed.

The journal must not contain:

- commands or arguments
- paths
- PIDs or process-instance IDs
- approval tokens
- raw hardware or account identity
- hostnames or network information

## Fixed-path store

The dormant file adapter stores one journal as `active-transition.json` under an
absolute backend-owned state directory. No frontend path or filename is
accepted.

The production composition has a separate fixed state-root boundary at
`/var/lib/handheld-dock-mode`. It creates only that final directory from the
existing real `/var/lib` parent, requires a POSIX root process, and accepts only
a real root-owned mode-0700 directory below a real root-owned, non-writable
parent. Symlinks, alternate leaf names, group/world-writable parents, non-root
ownership, and permission drift fail closed. The user-owned Gamescope
launch-config directory is never journal authority.

Save behavior:

1. Validate the existing journal, if any.
2. Require the same operation and request IDs.
3. Require the existing history to be an exact prefix of the replacement.
4. Encode strict bounded JSON.
5. Create a mode-0600 no-follow temporary file in the same directory.
6. Flush and `fsync` the file.
7. Atomically replace the fixed target.
8. `fsync` the containing directory where supported.

An injected replace failure leaves the prior journal intact and removes the
known temporary file. A different operation, regressed/divergent history,
corrupt file, unsupported schema, target symlink, or unavailable/symlink state
directory is rejected.

Only a matching terminal operation may be cleared. Incomplete state cannot be
discarded through the store.

## Runtime orchestration

The dormant runtime orchestrator persists every journal state through this
store. In particular, `step_started` must be durable before it calls a
mechanism. It re-observes the exact bound profile/GPU/display and game state
immediately before that point, then accepts a result only after a new snapshot
verifies the requested placement inside the deadline.

Apply failure, verification timeout, or inability to durably commit causes an
idempotent source-placement recovery attempt. If a restart finds an incomplete
journal before `step_started`, it terminals the abandoned request without a
mechanism call. If a step may have started, it attempts source recovery using a
fresh observation and records verified recovery or Action Required. It never
continues the interrupted target request.

### Restart-safe presentation acknowledgement

A Gamescope restart may replace the visible Decky UI before the original
supervised-transition RPC can return. The RPC result is therefore never the
authority for a display transition. After the UI returns, its delivery adapter
must read the presentation service's durable status and show one categorical
result: `transition.idle`, `transition.recovery_required`, a terminal journal
code, `transition.foreign_journal`, or `transition.journal_unavailable`.

Only a terminal presentation journal carries an acknowledgement ID. An
incomplete journal is Action Required and cannot be cleared; it must enter the
existing explicit recovery path. A foreign sleep/process-release journal is
also Action Required and is never acknowledged or described as a presentation
result. Status inspection does not restart Gamescope, retry a target, or create
automatic attach authority.

The exact transition binding and experimental approval identity are not written
to this privacy-safe journal.

### Shared owner-aware delivery

The Decky delivery layer reads the one shared journal through an owner-aware
status service. It identifies only `presentation`, `process_release`, `sleep`,
or `unknown`; request identity is never returned. A terminal sleep result now
has an explicit controller-visible acknowledgement because canonical sleep is
not otherwise exposed as a Decky workflow. That endpoint validates the exact
operation ID, terminal state, and `sleep.requested` owner marker before using
the store's matching-terminal-only clear operation. It cannot clear an
incomplete, presentation, process-release, or unknown journal.

Older presentation journals created before the categorical capability marker
are recognized only by their original `request.accepted` first event. New
presentation journals retain the explicit `presentation_transition` marker.
Unknown owner state remains Action Required and cannot be cleared.

## Current boundary

The store is constructed by Decky for guarded process release and supervised
presentation transitions under the root-owned state directory. Process
execution durably records `step_started` before signaling, and startup recovery
terminalizes an incomplete release without repeating a signal. Presentation
requests use the same journal and transition engine; manual confirmation and
the off-by-default automatic docking opt-in converge on that one path.

The canonical sleep coordinator uses the same port in deterministic tests and
persists each active stage before returning its directives. It remains unwired
from Decky. An interrupted journal never resumes an original sleep request after
restart; verified Portable recovery is terminal recovery evidence only, while
unknown or docked state fails closed into Action Required.

The journal now has strict `substep_started` / `substep_verified` events inside
an active parent step. Canonical sleep uses them for guarded process release:
every signal is preceded by a durable identity-free substep, every rescan closes
that substep, and graceful plus force phases remain inside the original sleep
operation. A second authoritative process journal is never opened. The sleep
child target bound is 26 so the worst-case verified-save, game-close,
two-phase-release, completion, and recovery path fits the 128-entry journal.

The verified-save and guarded game-close children use the same substep ordering.
Save persists `game.save_substep_started` before its injected mechanism and
`game.save_substep_verified` only after a new independent proof generation is
Verified. Close then persists an
identity-free `game.close_substep_started` event before invoking its injected
mechanism and closes the substep only after a fresh exact observation proves
the game Idle. Steam AppID, scope names, approval tokens, and mechanism details
are never journal fields; recipe, evidence, profile, and proof identities are
also excluded. Any save/close failure terminalizes the parent sleep transaction
as Action Required; no production save or game-close adapter is wired.

Adding the two save entries reduces the canonical sleep child process limit to
26. A deterministic maximum-path test proves that save, close, 26 graceful and
26 force substeps, all later sleep stages, and commit fit in 125 of 128 entries,
leaving bounded recovery capacity.

Every recovery/acknowledgement service first verifies the journal's categorical
owner marker. Process-release startup recovery cannot terminalize, clear, or
misreport a sleep or other foreign transaction; it returns a foreign-journal
blocker without modifying the file.
