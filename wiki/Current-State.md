# Current state

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** experimental development; no general public release

Use the [README status](https://github.com/ronnierosal/Re-Gear#-current-status) for the development candidate and source branch. The [repository status](https://github.com/ronnierosal/Re-Gear/blob/main/docs/CURRENT_STATE.md) and dated validation records distinguish implementation, installation, and hardware evidence. While newer work remains on an integration branch, consult that branch's records too; older main-branch snapshots do not establish the newest candidate's status.

## Available development work

| Area | Evidence and limits |
|---|---|
| Decky dashboard and diagnostics | Implemented; compact controller-focused status and actions in newer candidates |
| Profile-based hardware discovery | Exact tested combinations are listed in [Confirmed Hardware Testing](Confirmed-Hardware-Testing); other profiles are not certified by similarity |
| TV docking and Portable return | Guarded shared transition engine; bounded supervised successes, with repeatability and recovery gates remaining |
| Automatic TV docking | Experimental persistent opt-in, off by default; exact readiness and idle-game checks apply |
| Audio handoff | External HDMI default selection observed on the documented test profile; display success alone never proves audio success |
| Offline Readiness | Newer candidates read selected-game local Steam evidence; badges are guidance, not a guarantee of offline launch |
| Sleep protection and support export | Implemented with capability-specific controller and hardware acceptance gates |
| Disconnect status | Observes blockers; Portable return and a clear client scan do not authorize physical unplug |
| Boosted Handheld | Unproven and unavailable |
| Physical live eGPU removal | Unsupported; shutdown before disconnect remains required |

## Recorded hardware evidence

Supervised sessions on the [documented test hardware](Confirmed-Hardware-Testing) activated the TV and selected the external GPU. A later cycle selected external HDMI audio and returned to Portable. Other attempts encountered black-TV recovery, delayed enumeration, or missing driver binding. These are separate outcomes, not a claim that docking is uniformly reliable.

A watched shutdown lost networking while the handheld fan and LEDs remained on. More recent Portable trial records also found retained external GPU references despite a working internal display. Neither network loss nor a usable Portable screen proves complete shutdown or released eGPU resources.

## Resource-release experiment: September 6 update

**Priority: active disconnect work.** The latest recorded hardware run used installed
**0.3.54 / e765fad4b928**. TV output and return to the internal display worked;
the player confirmed normal controls and audio afterward. Steam and Gamescope
still retained external GPU allocations, and WirePlumber retained an audio-control
handle even with playback endpoints closed. A working handheld screen therefore
does not mean the external GPU has been released.

The OpenGL and Vulkan selection experiment is packaged in **0.3.56**, tracked in
[draft PR #82](https://github.com/ronnierosal/Re-Gear/pull/82). The candidate is staged,
**not installed or hardware validated**. It combines the graphics trial, allocation
diagnostics, and return-control correction; the separate experimental filter series
is excluded. The current priority is GitHub review and documentation; hardware
installation and testing are paused pending a separate supervised continuation.
Preparation-only tests and repeated unchanged display switches do not complete it.
Physical live removal remains unsupported.

Follow [the resource-release experiment (#51)](https://github.com/ronnierosal/Re-Gear/issues/51)
and [remaining audio ownership (#52)](https://github.com/ronnierosal/Re-Gear/issues/52).
See the [dated evidence summary](https://github.com/ronnierosal/Re-Gear/blob/codex/disconnect-progress-docs/docs/DISCONNECT_PROGRESS_2026-09-06.md)
for the tested configuration and limits.

## Remaining gates

Repeatable attach, TV picture, audio, gameplay, Portable return, reconnect, and physical shutdown need coordinated validation on the exact build. Experimental launch trials and local regression tests do not establish live-removal support.

See [Safety and eGPU Handling](Safety-and-eGPU-Handling), the [deployment gates](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEPLOYMENT_VALIDATION.md), and the [historical incident](Ally-X-and-GPD-G1-Docking-Incident).

See **[Confirmed Hardware Testing](Confirmed-Hardware-Testing)** for the capability-by-capability test ledger and **[Offline Play Readiness](Offline-Readiness)** for game checks.
