# eGPU and docking

**Audience:** players and supervised testers<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** guarded development workflows; capability-specific hardware evidence

Re-Gear helps explain a docked setup and guide supported changes between handheld
and external-display play. [Product](https://github.com/ronnierosal/Re-Gear/blob/main/docs/PRODUCT.md),
[safety](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SAFETY_INVARIANTS.md), and
[hardware support](https://github.com/ronnierosal/Re-Gear/blob/main/docs/HARDWARE_SUPPORT.md)
own the underlying contracts.

## What the modes mean

| Placement | Intended meaning | Evidence limit |
|---|---|---|
| Portable | Internal GPU and internal panel | Observed on the recorded test configuration; does not prove external resources are released |
| TV Docked / Docked-eGPU | Verified external GPU and its directly attached display | Bounded supervised successes; repeatability, audio and recovery still need exact-build validation |
| Docked-iGPU | Internal GPU with an external display | Read-only observation and guarded foundations exist; placement and production action acceptance remain unverified |
| Boosted Handheld | External GPU renders to the internal panel | Unproven and unavailable |

Physical connection, rendering GPU, selected display, audio route, and game state
are observed separately. A connected monitor is not proof of a usable picture;
a working picture is not proof of audio or input readiness.

## Display changes and recovery

Manual display requests and experimental automatic docking share the guarded
transition engine. Automatic docking is an explicit opt-in and off by default.
Unknown state blocks unsafe actions, and a running game is not moved between GPUs.
Supported preparation, verification, and recovery depend on the exact profile.

## Disconnect development

Holder-scan completeness, a bounded filter hold-open window, the operator
software-removal tool, and a pure interrupted-removal transaction model have
landed in source. These are implementation steps, not an end-to-end player
disconnect feature. The transaction model alone does not provide durable
storage or wire recovery into the running plugin.

**Safe live physical unplug is not validated.** Return to or retain a known-good
state, fully shut down, and confirm physical power-off before disconnecting under
the current policy. A clear scan or successful software removal does not clear
the rest of a dock, its USB devices, or storage for unplugging.

**Priority:** active reliability work, including the live-disconnect objective.
[Current State](Current-State) links merged work and remaining integration gates.
[Safety and eGPU Handling](Safety-and-eGPU-Handling) explains today's handling rules;
[Confirmed Hardware Testing](Confirmed-Hardware-Testing) preserves actual observed
results. Tests of code never upgrade those historical device results.

## Troubleshooting and lessons

For the recorded device-specific issues, see
[Ally X and GPD G1 troubleshooting](Ally-X-and-GPD-G1-Troubleshooting).
It separates symptoms, causes, source fixes and unresolved hardware gates while
preserving links to the original dated incident.
