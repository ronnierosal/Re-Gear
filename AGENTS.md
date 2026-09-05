# Re-Gear Instructions

## Project identity

Re-Gear (formerly Handheld Dock Mode / HDM) is a SteamOS-first, safety-critical
dock-mode controller. Branding and compatibility rules: `docs/BRANDING.md`. It is a new
project; eGPUBridge is reference evidence, not the architecture to reproduce.

## Sources of truth

- Documentation map and authority rules: `docs/INDEX.md`
- Current repository/build/deployment snapshot: `docs/CURRENT_STATE.md`
- Product scope: `docs/PRODUCT.md`
- Non-negotiable safety rules: `docs/SAFETY_INVARIANTS.md`
- Component and state design: `docs/ARCHITECTURE.md`
- Certified hardware claims: `docs/HARDWARE_SUPPORT.md`
- Diagnostics contract: `docs/DIAGNOSTICS.md`
- Ordered status and dependencies: `docs/ROADMAP.md`
- Hardware deployment gates: `docs/DEPLOYMENT_VALIDATION.md`
- Maintainer/agent SSH and current deployment handoff: `docs/OPERATOR_HANDOFF.md`
- Bounded worker ownership, checkpoints, and integration: `docs/WORK_QUEUE.md`
- Current executable behavior: code plus tests; docs and memory never override it

Use the source that owns the question. Product, safety, architecture, and
accepted ADRs define intended contracts. Code and tests define executable
behavior. `docs/CURRENT_STATE.md` plus linked evidence defines what is built or
installed. Issues, pull requests, the Wiki, Codex notes, and chat history are
context only. When sources conflict, stop the claim, verify current evidence,
and correct the owning repository document.

## Ownership and coordination

- One driver owns integration and durable decisions for each workstream.
- Use parallel workers for bounded searches, audits, tests, or isolated changes.
  Workers return evidence and focused diffs; the driver integrates them.
- Do not have multiple workers independently redesign architecture, state
  machines, UX, hardware abstractions, or deployment strategy.
- Inspect branch, HEAD, worktree status, and overlapping active work before
  editing shared files. Never revert or absorb unrelated changes.
- The Ally X + GPD G1 end-to-end hardware journey has a separate driver. Shared
  diagnostics and documentation may support it, but this workstream must not
  deploy, run hardware transitions, or rewrite its runtime path without explicit
  coordination.

## Required rules

- Keep physical connection, render GPU, display target, Gamescope state, and
  running-game state independent.
- Never hard-code DRM card numbers, connector suffixes, or PCI bus addresses.
- Unknown GPU identity, game state, or transition readiness fails closed.
- Never migrate a running workload between GPUs or claim live eGPU removal is safe.
- Manual and automatic requests must eventually use one transition engine.
- Keep `backend/hdm/domain` pure: no filesystem, subprocess, network, or OS calls.
- Display/GPU mutation remains limited to explicitly documented, approved,
  supervised mechanisms. Do not widen authority without a milestone decision,
  rollback coverage, and corresponding safety tests.

## Workflow

Use proportional verification. During iteration, run the smallest relevant
checks. Before a focused commit, run targeted regression tests and architecture
checks when applicable. Run the full matrix at meaningful integration,
deployment, and release gates. See `docs/DEVELOPMENT.md`.

When a test or remote check fails, diagnose it in the same work cycle: capture
the failure, inspect bounded logs/transactions/relevant state, correlate the
earliest divergence, form one hypothesis, apply the smallest justified fix,
and retest. Do not stop at "test failed" when evidence is locally available.

Minimum backend integration gate:

```text
python scripts/check_architecture.py
python -m unittest discover -s tests -v
python -m compileall -q backend tests scripts
```

Hardware-affecting work additionally requires redacted before/live/after evidence
and supervised validation on a supported profile.

## Shared release coordination

Before editing or packaging, read `docs/CHAT_COORDINATION.md`. Register tested
completed commits with `scripts/release_coordination.py ready <workstream>`.
All player ZIPs use plain Re-Gear-X.Y.Z.zip names. Do not overwrite archives.
