# Current state

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** experimental development; no general public release

Use the [README status](https://github.com/ronnierosal/Re-Gear#-current-status) for the development candidate and source branch. The [repository status](https://github.com/ronnierosal/Re-Gear/blob/main/docs/CURRENT_STATE.md) and dated validation records distinguish implementation, installation, and hardware evidence. While newer work remains on an integration branch, consult that branch's records too; older main-branch snapshots do not establish the newest candidate's status.

## Available development work

| Area | Evidence and limits |
|---|---|
| Decky dashboard and diagnostics | Implemented; compact controller-focused status and actions in newer candidates |
| Exact Ally X/GPD G1 discovery | Hardware observations exist; other profiles are not certified by similarity |
| TV docking and Portable return | Guarded shared transition engine; bounded supervised successes, with repeatability and recovery gates remaining |
| Automatic TV docking | Experimental persistent opt-in, off by default; exact readiness and idle-game checks apply |
| Audio handoff | Exact G1 HDMI default selection observed in a supervised cycle; display success alone never proves audio success |
| Offline Readiness | Newer candidates read selected-game local Steam evidence; badges are guidance, not a guarantee of offline launch |
| Sleep protection and support export | Implemented with capability-specific controller and hardware acceptance gates |
| Disconnect status | Observes blockers; Portable return and a clear client scan do not authorize physical unplug |
| Boosted Handheld | Unproven and unavailable |
| Physical live G1 removal | Unsupported; shutdown before disconnect remains required |

## Recorded hardware evidence

Earlier supervised sessions activated the TV and selected the RX 7600M XT. A later cycle selected G1 HDMI audio and returned to Portable. Other attempts encountered black-TV recovery, delayed enumeration, or missing driver binding. These are separate outcomes, not a claim that docking is uniformly reliable.

A watched shutdown lost networking while the handheld fan and LEDs remained on. More recent Portable trial records also found retained external GPU references despite a working internal display. Neither network loss nor a usable Portable screen proves complete shutdown or released eGPU resources.

## Remaining gates

Repeatable attach, TV picture, audio, gameplay, Portable return, reconnect, and physical shutdown need coordinated validation on the exact build. Experimental launch trials and local regression tests do not establish live-removal support.

See [Safety and eGPU Handling](Safety-and-eGPU-Handling), the [deployment gates](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEPLOYMENT_VALIDATION.md), and the [historical incident](Ally-X-and-GPD-G1-Docking-Incident).
