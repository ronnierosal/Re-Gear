# Re-Gear

**Audience:** players, testers, and contributors<br>
**Evidence reviewed:** 2026-09-02<br>
**Maturity:** early development; no general public release

Re-Gear (formerly Handheld Dock Mode / HDM) is a SteamOS-first, safety-focused Decky Loader plugin
for console-like handheld, eGPU, dock, and external-display workflows. It aims
to detect current state, block unsafe operations, explain what is happening in
player language, and recover to a known-good state when a verified transition
fails.

The engineering authorities are the repository
[documentation index](https://github.com/ronnierosal/Handheld-Docked-Mode-SteamOS/blob/main/docs/INDEX.md),
[current state](https://github.com/ronnierosal/Handheld-Docked-Mode-SteamOS/blob/main/docs/CURRENT_STATE.md),
[product definition](https://github.com/ronnierosal/Handheld-Docked-Mode-SteamOS/blob/main/docs/PRODUCT.md),
and [safety invariants](https://github.com/ronnierosal/Handheld-Docked-Mode-SteamOS/blob/main/docs/SAFETY_INVARIANTS.md).

## Target placements

| Placement | Intended render and display path | Current evidence |
|---|---|---|
| Portable | Internal GPU to internal panel | Observed on the first hardware profile |
| Boosted Handheld | Verified eGPU to internal panel | Designed; not available or hardware proven |
| Docked-iGPU | Internal GPU to external display | Research path; not an implemented product claim |
| TV Docked / Docked-eGPU | Verified eGPU to its external display | Automatic exact-profile path hardware tested once; repeated journey validation remains |

Re-Gear keeps physical connection, render GPU, active display, Gamescope state, and
running-game state separate. A cable or connector reported as `connected` does
not prove that the display is active or usable.

## First validated profile

Development began with an ASUS ROG Ally X running SteamOS and a GPD G1 with an
AMD Radeon RX 7600M XT. That exact profile is legitimate compatibility and
quirk knowledge, not a reason for core workflows to assume every host or eGPU
behaves the same way.

Start with [Current State](Current-State), [Getting Started](Getting-Started),
the [Ally X and GPD G1 incident](Ally-X-and-GPD-G1-Docking-Incident), or
[How Re-Gear Works](How-HDM-Works). Before touching an eGPU, read
[Safety and eGPU Handling](Safety-and-eGPU-Handling).
