# Project overview

**Audience:** anyone evaluating or contributing to Re-Gear<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** shared product direction with capabilities at different development stages

Re-Gear is a Decky Loader companion for console-like SteamOS handheld gaming.
Its [product definition](https://github.com/ronnierosal/Re-Gear/blob/main/docs/PRODUCT.md)
and [architecture](https://github.com/ronnierosal/Re-Gear/blob/main/docs/ARCHITECTURE.md)
own scope and technical contracts.

## The experience

The project brings everyday controls and understandable system status together:
handheld and docked play, performance and power, controllers, offline readiness,
and guided recovery. Different areas have different implementation and validation
levels; see [Current State](Current-State).

The [Command Center](Command-Center) is the approved direction for immediate
controls and status. Modules provide deeper configuration. Technical detail
belongs in optional troubleshooting, while the main experience answers what is
available, what needs attention, and what action is supported.

## Shared principles

- **Games first:** keep background work bounded and avoid unnecessary activity during play.
- **Evidence before action:** observe device, display, render, input, game and provider state independently.
- **One guarded path:** common controls and shortcuts share authorization, verification and recovery behavior.
- **Capability-based support:** profiles and adapters hold exact device requirements; unknown hardware does not inherit support.
- **Honest status:** an attempted command, passed simulation, installed build and validated device result mean different things.

## Scope limits

Current scope does not include Windows or arbitrary desktop Linux support,
universal hardware compatibility, moving a running game between GPUs, arbitrary
overclocking/fan control/driver installation, or a cloud plugin marketplace.
Physical live eGPU removal remains unsupported while its separately gated
development continues.

**Compatibility note:** Re-Gear was formerly Handheld Dock Mode. New repository
builds use the `Re-Gear` Decky directory. Older test installs may still use
`HandheldDockMode` and require the separately supervised
[cutover procedure](https://github.com/ronnierosal/Re-Gear/blob/main/docs/IDENTITY_CUTOVER.md);
merged code does not migrate an installed device. Internal state identifiers and
legacy Wiki slugs remain stable. eGPUBridge provides reference evidence; Re-Gear
must establish its own behavior and hardware proof.
