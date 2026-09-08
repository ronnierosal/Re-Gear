# Ally X and GPD G1 troubleshooting

**Audience:** players and supervised testers using this exact configuration<br>
**Evidence reviewed:** 2026-09-08; observations span September 2–8<br>
**Maturity:** bounded historical device evidence and later source fixes; no live-unplug support

## 1. Scope / who this helps

This page covers ASUS ROG Ally X running SteamOS with a GPD G1 and an external
display connected directly to the G1. It explains recorded problems on that
configuration. It does not certify other handhelds, docks, operating systems,
firmware versions or builds. Start with the general [eGPU guide](eGPU-and-Docking)
for placement and workflow concepts.

## 2. Situation (what / where / when)

The [September 2 incident](Ally-X-and-GPD-G1-Docking-Incident) records supervised
TV-docking attempts, followed by bounded display/render and audio successes.
Later Portable and shutdown tests exposed separate release and recovery problems.
The [September 8 engineering account](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVICE_FILTER_RELEASE_2026-09-08.md)
reports installed 0.3.58 and source-driven removal/rescan; its before/live/after
capture is missing. This page is a documentation review, not a new device test.

## 3. Symptoms

- G1 connected but readiness incomplete, or a TV detecting a signal while remaining black.
- Steam reaching the TV while audio stayed on the handheld.
- A successful return to the handheld screen while Steam/Gamescope or audio clients still held external-device resources.
- A shutdown request losing networking while the fan and power LEDs stayed on.
- Separate USB-branch errors and recovery failures; a clean GPU teardown did not resolve them.

## 4. Evidence and likely cause

| Recorded problem | Evidence-backed explanation | Fix or unresolved limit |
|---|---|---|
| Incomplete readiness / black TV | September 2 record traced a rejected valid link-width format, launch binding mismatch and unreadable launch configuration | Source corrections and one later watched TV/render success; not repeatability proof |
| Wrong audio output | Active display did not select the correct audio default | Exact-output selection and rollback guards; each build/cycle still needs audio verification |
| Retained resources after Portable return | Display selection did not close existing GPU/audio handles; an open-device filter prevents new opens but does not close existing handles | Separate guarded release work; a Portable screen is not release evidence |
| False or short-lived clear verdict | Older scan skipped some unreadable/scope holders; filter lifetime ended too early | [#137](https://github.com/ronnierosal/Re-Gear/pull/137) and [#124](https://github.com/ronnierosal/Re-Gear/pull/124) merged source fixes; historical reports are not upgraded |
| Incomplete shutdown | Physical fan/LED observations contradicted command/network status | Root cause is not established by this guide; complete power-off remains a separate gate |
| USB recovery failure | [#105](https://github.com/ronnierosal/Re-Gear/issues/105) tracks ACS errors and failed xHCI recovery | Unresolved; GPU-function removal does not prove the dock or USB branch safe to unplug |

## 5. What Re-Gear does

Guarded transitions check render GPU, active display, game state and recovery
evidence separately. Journal ownership and Portable acknowledgement prevent a
successful return from being treated as permission to immediately redock.
Shutdown is presented as a request whose physical outcome still needs verification.

The software-removal tool landed through [#148](https://github.com/ronnierosal/Re-Gear/pull/148).
The interrupted-removal record in [#152](https://github.com/ronnierosal/Re-Gear/pull/152)
is a pure model/storage port. Runtime wiring, durable integration and the player
entry point remain separate work. Neither is a safe-unplug certificate.

## 6. Steps to try

1. Check the displayed Re-Gear build and record which screen, audio output and controls actually work.
2. Read the specific status reason; distinguish device connection, active display, render GPU and workflow progress.
3. Use only the supported guarded action in the coordinated test plan. If readiness is unknown, stop and collect a reviewed support preview through [Troubleshooting](Troubleshooting).
4. Keep the G1 connected until complete physical power-off under the current disconnect policy. Network loss alone is insufficient. If shutdown is incomplete, stop and follow the current supervised recovery plan rather than repeating transitions or unplugging.

This page supplies no privileged filter, PCI removal, service-restart or forced
power-off recipe. Historical incident commands are not general player workarounds.

## 7. Verification status

| Evidence level | Established | Limit |
|---|---|---|
| Source / tests | Guarded display/release/removal and recovery components have deterministic coverage | Tests do not establish installation or device behavior |
| Merged | Later holder-scan, filter-lifetime and operator-removal fixes are on the reviewed main | End-to-end live-disconnect integration remains incomplete |
| Installed | September 8 account reports 0.3.58 | No fresh installed SHA/checksum verified in this review |
| Hardware tested | Earlier bounded TV/render/audio/Portable successes; later operator-reported removal/rescan | Mixed failures, incomplete repeatability, missing September 8 capture; no live-unplug validation |

## 8. Known limits / unresolved work

The [current checkpoint](Current-State) links installable-build work (#116),
player entry-point integration (#146), physical-removal contract (#147),
external-display release evidence (#143), missing capture (#136), and USB
recovery (#105). These require their own resolution and exact-build tests.
No merged correction proves that a historical or currently installed build is fixed.

## 9. Related guides / issues / PRs

[eGPU and Docking](eGPU-and-Docking) · [Safety and eGPU Handling](Safety-and-eGPU-Handling)
· [Confirmed Hardware Testing](Confirmed-Hardware-Testing)
· [Original September 2 incident](Ally-X-and-GPD-G1-Docking-Incident)
· [Engineering evidence](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVICE_FILTER_RELEASE_2026-09-08.md)
