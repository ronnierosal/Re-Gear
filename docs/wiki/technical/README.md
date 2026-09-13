# 🛠️ Re-Gear Technical Guide

This is the engineering side of the Re-Gear Wiki.

If you only want to install and use Re-Gear, use the [Player Guide](../player/README.md). This section is for contributors, developers, testers, hardware investigators, and anyone who wants to understand how Re-Gear works under the hood.

## Architecture & design

- [Architecture](../../ARCHITECTURE.md)
- [Agent coordination](../../AGENT_COORDINATION.md)
- [Project backlog](../../BACKLOG.md)
- [Branding](../../BRANDING.md)

## eGPU lifecycle

The eGPU work is documented as evidence-driven engineering rather than a collection of player instructions. Relevant technical topics include:

- device discovery and identity
- attach readiness
- automatic docking
- display/render selection
- Gamescope interaction
- resource release
- safe disconnect
- link recovery
- repeat-cycle recovery

Start with:

- [Attach Readiness](../../ATTACH_READINESS.md)
- [Automatic Link Recovery](../../AUTOMATIC_LINK_RECOVERY.md)
- [Audio Resource Release Trial](../../AUDIO_RESOURCE_RELEASE_TRIAL.md)
- [Ally X + GPD G1 docking incident record](../../ALLY_X_GPD_G1_DOCKING_INCIDENT_2026-09-02.md)

## Power & sleep

- [Sleep Guard ADR](../../ADR_SLEEP_GUARD.md)
- [Steam Sleep Preflight ADR](../../ADR_STEAM_SLEEP_PREFLIGHT.md)

## Performance / Auto TDP

- [Auto TDP Independent Plan](../../AUTO_TDP_INDEPENDENT_PLAN.md)

## Evidence vs product behavior

Technical documentation should distinguish between:

1. **Observed evidence** — what a test, log, kernel interface, or device actually showed.
2. **Current implementation** — what Re-Gear currently does.
3. **Intended behavior** — the product experience Re-Gear is working toward.
4. **Validated behavior** — behavior demonstrated through an appropriate test or supervised hardware validation.

A successful experiment is not automatically a supported player feature. Keeping those concepts separate makes the project safer to evolve and makes the research more useful to other SteamOS/Linux developers.

## Player-facing documentation boundary

Do not copy low-level troubleshooting into the Player Guide unless a player actually needs it to complete an action. Player documentation should translate internal state into useful messages such as **Connected**, **Switching**, **Ready to disconnect**, or **Needs attention**.

Deep diagnostics, command output, kernel behavior, PCI/DRM details, and validation records belong here.