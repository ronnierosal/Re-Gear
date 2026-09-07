# Documentation and authority

The product is now **Re-Gear**, formerly Handheld Dock Mode (HDM). See
[branding and compatibility](BRANDING.md) before changing names or paths.

The repository is HDM's engineering memory. Chats, Codex notes, issues, pull
requests, and the GitHub Wiki may explain or propose work, but they do not own
critical engineering contracts.

## Read first

1. [Current state](CURRENT_STATE.md) — branch/build/deployment truth and active
   workstream boundaries.
2. [Product](PRODUCT.md) — product scope, placements, and player experience.
3. [Safety invariants](SAFETY_INVARIANTS.md) — non-negotiable mutation gates.
4. [Architecture](ARCHITECTURE.md) — components, state, and dependency rules.
5. [Development](DEVELOPMENT.md) — Git, testing, diagnosis, and integration.

Agents should also read `AGENTS.md`, which is the concise operating contract
loaded at the start of repository work.

## Authority by question

| Question | Authority | Supporting evidence |
|---|---|---|
| What should HDM do? | `PRODUCT.md`, `SAFETY_INVARIANTS.md`, accepted ADRs | Architecture and UI specifications |
| How is HDM designed? | `ARCHITECTURE.md`, accepted ADRs | Focused design documents |
| What does current code do? | Source code and tests | CI results and deterministic fixtures |
| What is implemented, simulated, or proven? | `CURRENT_STATE.md`, `ROADMAP.md` | Dated validation records |
| What version is built or installed? | Immutable build metadata plus `CURRENT_STATE.md` | Artifact checksum and deployment evidence |
| What hardware is supported? | `HARDWARE_SUPPORT.md` | Dated hardware validation records |
| What may workers change and how? | `AGENTS.md`, `DEVELOPMENT.md`, `WORK_QUEUE.md` | Active driver coordination |

When sources conflict, do not select the most convenient statement. Verify the
current code, build, or device as appropriate, then correct the document that
owns the claim. A dated evidence record remains historical evidence and should
not be silently rewritten into a current-state page.

## Evidence vocabulary

- **Designed:** reviewed contract; no executable behavior implied.
- **Implemented:** present in current code with relevant deterministic checks.
- **Simulated:** exercised through fixtures/fakes; no device claim implied.
- **Installed:** exact build identity observed on a device.
- **Hardware tested:** behavior intentionally exercised on the named hardware.
- **Certified:** defined capability passed its documented release evidence gate.
- **Unknown:** current evidence is absent, incomplete, stale, or conflicting.

Compatibility uses a separate vocabulary: **Certified**, **Tested**,
**Experimental**, **Community reported**, **Untested**, and **Unsupported / Known
issue**. Architectural possibility is not support.

## Document map

- Public entry point: [README](../README.md)
- Status and work: [Current state](CURRENT_STATE.md), [Roadmap](ROADMAP.md),
  [Worker queue](WORK_QUEUE.md)
- Hardware and compatibility: [Hardware support](HARDWARE_SUPPORT.md),
  [hardware-agnostic audit](HARDWARE_AGNOSTIC_AUDIT.md)
- UX: [UI specification](UI_SPEC.md)
- Operations: [Deployment validation](DEPLOYMENT_VALIDATION.md),
  [operator handoff](OPERATOR_HANDOFF.md), [diagnostics](DIAGNOSTICS.md),
  [release pipeline](RELEASE_PIPELINE.md)
- Reference ancestry: [eGPUBridge parity](EGPUBRIDGE_FEATURE_REVIEW.md)
- Audio sequencing: [G1 audio activation candidate](G1_AUDIO_ACTIVATION.md)
- Hardware incident evidence: [Ally X and GPD G1 automatic docking incident](ALLY_X_GPD_G1_DOCKING_INCIDENT_2026-09-02.md)
- Public documentation: [Wiki source](../wiki/README.md) and
  [Wiki information architecture](WIKI_INFORMATION_ARCHITECTURE.md)
- Decisions: [ADR index](adr/README.md)
- Historical evidence: dated validation, deployment, and supervised-session
  documents in this directory

The existing focused design documents remain valid references. Consolidation
should classify and link them before moving or deleting them.
