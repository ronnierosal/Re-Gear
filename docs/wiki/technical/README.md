# Re-Gear Technical Guide

Understand how Re-Gear works and what the evidence actually establishes.
For everyday use, start with the [Player Guide](../player/README.md).

## Core guides

- [eGPU lifecycle acceptance matrix](egpu-lifecycle.md) — v0.3.98 baseline,
  production entry points, evidence, failures, owners and next gaps.
- [Architecture and hexagonal layers](architecture.md) — policy, ports, adapters
  and production composition.
- [Scripts and CI gates](scripts-and-ci.md) — readiness probes versus execution,
  local validation and continuous integration.
- [Current state](current-state.md) — evidence status, not the newest version number.
- [Development](development.md), [roadmap](roadmap.md), and [issues](issues.md).
- [Project overview](project-overview.md) and [how Re-Gear works](how-regear-works.md).

## Hardware evidence

- [Evidence ledger](hardware-evidence.md)
- Historical [automatic recovery](history/automatic-recovery.md),
  [docking incident](history/docking-incident.md),
  [docking investigation](history/docking-troubleshooting.md), and
  [controller investigation](history/raikiri-ii.md).

Implemented, simulated, installed and hardware-tested are different states.
A test fixture does not establish native mounting; a single supervised success
does not establish repeatability or other-hardware support. Owning contracts live
in the [complete engineering index](../../INDEX.md). The Wiki explains them.
