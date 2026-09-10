# ADR 0002: Capability-driven hardware profiles

- Status: Accepted
- Date: 2026-09-02

## Decision

Re-Gear core policy reasons about observed capabilities and independent state.
Exact model/ID knowledge remains in conservative profiles and platform adapters.
Runtime observation is authoritative; a profile entry does not certify hardware.

The Ally X + GPD G1 remains the first exact certification profile. Abstraction
is introduced only at seams required by current evidence or a concrete second
profile, with synthetic tests before production broadening.

## Consequences

- Exact first-profile checks remain strict and fail closed.
- Central discovery and mechanisms must eventually consume a narrow resolved
  profile contract rather than call one model matcher directly.
- Player UI uses capability language; diagnostics and compatibility pages may
  identify exact models.
- Future hardware is Untested until capability-specific evidence promotes it.
