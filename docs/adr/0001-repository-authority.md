# ADR 0001: Repository authority and Wiki boundary

- Status: Accepted
- Date: 2026-09-02

## Decision

Version-controlled product, safety, architecture, state, development, and
evidence documents own Re-Gear engineering truth. Code/tests own executable behavior
and immutable build/deployment evidence owns runtime identity. The GitHub Wiki
is a human guide that links back to these contracts. Issues, pull requests,
Codex notes, and chat history are context rather than authority.

## Consequences

- New workers can start from `AGENTS.md`, `docs/INDEX.md`, and
  `docs/CURRENT_STATE.md`.
- Volatile build/deployment claims live in one current-state page with links to
  dated evidence.
- Critical contracts are never maintained only in the Wiki.
- Conflicts trigger verification and correction of the owning repository source.
