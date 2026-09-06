# Project overview

**Audience:** anyone evaluating or contributing to Re-Gear<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** product and architecture are defined; capabilities remain evidence-gated

The authoritative scope is the repository
[product definition](https://github.com/ronnierosal/Re-Gear/blob/main/docs/PRODUCT.md)
and [architecture](https://github.com/ronnierosal/Re-Gear/blob/main/docs/ARCHITECTURE.md).

## What Re-Gear is trying to solve

Docking a handheld with an eGPU is not one binary event. The eGPU may be
physically present while the game still renders on the internal GPU; an external
connector may be connected while Gamescope is using the internal panel; and a
running game may make an otherwise valid display change unsafe.

Re-Gear models those facts independently, then uses one guarded workflow:

```text
DETECT -> VALIDATE -> PLAN -> PREPARE -> APPLY -> VERIFY -> COMMIT
                                            |
                                            +-> ROLL BACK or retain known-good state
```

Unknown or conflicting evidence fails closed. An already-satisfied request is a
no-op. A failed transition must retain or restore a known-good state instead of
claiming success from an attempted command.

## Design direction

Core policy should ask what the current host, eGPU, display path, and session can
do. Product-specific identity and quirks belong in profiles or platform
adapters. The first Ally X and GPD G1 profile remains intentionally exact while
future profiles should be added through capabilities and bounded mechanisms,
not scattered product-name branches.

## Current non-goals

- Windows support or arbitrary desktop Linux distributions
- support for every handheld, dock, or eGPU by inference
- physical live eGPU removal on the GPD G1
- moving a running game between GPUs
- arbitrary GPU overclocking, fan control, or driver installation
- cloud services or a general plugin ecosystem

Re-Gear is not a port of eGPUBridge. Prior eGPUBridge observations are reference
evidence; native Re-Gear behavior must earn its own implementation and hardware
proof.
