> **Historical checkpoint.** Retained from source `9421c6f`; statements describe that dated session, not current availability.

# Repository audit — 2026-09-02

This is a bounded, read-only baseline for the repository/governance revamp. It
does not replace [Current state](../../CURRENT_STATE.md) and makes no hardware claim.

## Baseline

- Local branch `main`, HEAD `8d96b9c398f77c26ebbef50b5fb1c7d402695169`
- Clean worktree at audit time
- Local `main` 67 commits ahead of `origin/main`
- Project version `0.2.0`
- 55 tracked documents, 120 test files, and 157 backend files
- Existing CI covers architecture, Python tests/compilation, diagnostics smoke,
  frontend typecheck/tests/build, package contract, deterministic archive,
  source revision, SHA-256, artifact verification, and candidate preparation

## Strong foundations to preserve

- Pure `backend/hdm/domain` boundary with an automated architecture check
- Independent physical connection, render GPU, display, Gamescope, game, and
  workflow state
- Explicit safety invariants and fail-closed identity/game/readiness policy
- Detailed evidence-aware roadmap and hardware validation records
- Bounded privacy-safe diagnostics and support bundle contracts
- Embedded source revision and controlled artifact checksum verification
- Supervised deployment ladder and separate hardware evidence gates
- Visually strong README with honest maturity and capability language
- Existing eGPUBridge feature review that can become the parity ledger

## Gaps

| Area | Finding | Priority |
|---|---|---|
| Public authority | GitHub lacks 67 audited local commits; remote CI cannot validate current local behavior | P0 |
| Current state | Candidate, installed, and checkout identity are spread across stale dated records | P0 |
| Hardware architecture | Central discovery and Gamescope launch call only Ally/G1 matchers despite a registry | P0 |
| Agent contract | Obsolete 0.1 rule; no concise one-driver/worker or parallel hardware ownership rule | P1 |
| Diagnostics | CLI is source-oriented, not a packaged unified build/service/transaction/recovery report | P1 |
| Documentation | Status/history/specification are interleaved across several large files | P1 |
| UX | No authoritative UI specification; eGPUBridge comparison remains subjective | P1 |
| GitHub | No contribution/security docs, issue/PR templates, or Wiki content plan | P1 |
| CI | Missing whitespace/generated-output checks, concurrency, and action update policy | P2 |
| Hygiene | Generated frontend outputs are intentional; common local secret-file ignores can improve | P2 |

## Hardware-coupling summary

- **P0:** `SteamOsDiscovery` and Gamescope launch bind directly to Ally/G1
  matchers; adding a registry entry is insufficient.
- **P1:** sleep protection, render binding, AMD activity, and internal-panel
  classification have first-profile assumptions in runtime mechanisms.
- **P2:** support/UI/domain terminology and deployment helpers contain
  profile-specific choices suitable for incremental configuration.
- **P3:** exact IDs inside profile modules and non-default connector/card test
  fixtures are appropriate certification evidence, not defects.

See [Hardware-agnostic audit](../../HARDWARE_AGNOSTIC_AUDIT.md) for exact evidence.

## Target structure

The current filenames are generally useful. Add navigation and governance before
moving historical material:

```text
README.md                 public front door
AGENTS.md                 concise worker contract
CONTRIBUTING.md           contributor workflow
SECURITY.md               reporting and security boundaries
docs/INDEX.md             authority and navigation
docs/CURRENT_STATE.md     mutable repository/build/deployment truth
docs/DEVELOPMENT.md       Git, tests, diagnosis, integration
docs/UI_SPEC.md           accepted player-facing contract
docs/HARDWARE_SUPPORT.md  compatibility and certification authority
docs/EGPUBRIDGE_FEATURE_REVIEW.md  parity ledger
docs/adr/                 durable decisions
```

Dated validation/deployment/session files remain immutable evidence snapshots.
Future consolidation may group them under evidence/operations/design only after
all links and active workers are coordinated.

## Phases

1. Authority, current state, agent ownership, development/Git rules
2. Unified build/deployment identity and installed diagnostic report
3. README/document navigation and vocabulary consolidation
4. eGPUBridge parity and UI specification
5. Narrow P0/P1 hardware-profile seams with synthetic regression tests
6. Publish useful Wiki pages from the approved information architecture
7. CI/templates/ADR/hygiene refinements

No phase authorizes a hardware transition or deployment. The separate Ally X +
GPD G1 journey driver retains that ownership.
