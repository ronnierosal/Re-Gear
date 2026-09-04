# How Re-Gear works

**Audience:** players, testers, and contributors<br>
**Evidence reviewed:** 2026-09-02<br>
**Maturity:** implemented foundation with capability-specific validation

The repository [architecture](https://github.com/ronnierosal/Handheld-Docked-Mode-SteamOS/blob/main/docs/ARCHITECTURE.md)
and [product definition](https://github.com/ronnierosal/Handheld-Docked-Mode-SteamOS/blob/main/docs/PRODUCT.md)
own the model summarized here.

Re-Gear first observes the system, then derives a placement and health state. It
does not assume that plugging in a cable completed a docking workflow.

## Independent facts

- Is an eGPU physically connected and exactly identified?
- Which GPU is actually rendering the session?
- Which display is active, not merely connected?
- Is Gamescope in the expected generation and launch configuration?
- Is a game running, idle, or unknown?
- Is the eGPU link stable and are required clients or storage still attached?

Only mutually consistent evidence can make a transition eligible. Missing or
ambiguous evidence becomes Unknown and blocks unsafe mutation.

## Profiles, capabilities, and mechanisms

Hardware profiles hold exact identity and required quirks, such as the first
Ally X and GPD G1 topology. Capability contracts describe what a resolved
profile may safely do. SteamOS adapters observe sysfs, procfs, Gamescope, and
session state. Narrow mechanisms perform only approved operations. Pure domain
policy decides whether a request is allowed and how it must recover.

This separation is still incomplete in several P1 areas. The project is fixing
those seams incrementally rather than replacing proven first-profile behavior
with speculative abstractions.

## Verification matters

A requested transition is complete only after Re-Gear re-observes the intended
render GPU, active display, Gamescope state, and user-visible readiness.
Command success or connector presence alone is insufficient. A timeout or
contradiction triggers bounded rollback or retains the known-good state.
