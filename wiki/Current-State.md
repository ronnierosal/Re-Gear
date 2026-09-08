# Current state

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** experimental development; no general public release

The [repository status](https://github.com/ronnierosal/Re-Gear/blob/main/docs/CURRENT_STATE.md)
and [September 8 source/evidence snapshot](https://github.com/ronnierosal/Re-Gear/blob/main/docs/STATUS_SNAPSHOT_2026-09-08.md)
distinguish merged implementation, reported installation, and hardware validation.
The reviewed main revision `5b18edf` declares 0.3.58 and includes the reconciled
release line. Separate candidates retain their own review and validation gates;
a higher version number alone does not establish ancestry or installation.

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
| eGPU client release | Operator reported a clear holder result under a device filter; no archived capture and known scan gaps prevent treating it as complete-release proof. Operator CLI only; no unplug clearance |
| Boosted Handheld | Unproven and unavailable |
| Physical live eGPU removal | Unsupported; shutdown before disconnect remains required |

## Recorded hardware evidence

Supervised sessions on the [documented test hardware](Confirmed-Hardware-Testing) activated the TV and selected the external GPU. A later cycle selected external HDMI audio and returned to Portable. Other attempts encountered black-TV recovery, delayed enumeration, or missing driver binding. These are separate outcomes, not a claim that docking is uniformly reliable.

A watched shutdown lost networking while the handheld fan and LEDs remained on. More recent Portable trial records also found retained external GPU references despite a working internal display. Neither network loss nor a usable Portable screen proves complete shutdown or released eGPU resources.

## Resource-release experiment: September 8 update

**Priority: active disconnect work.** The September 8 operator account reports
installed **0.3.58**, an enforced device filter, approved unit restarts, and a clear
holder result. It separately reports source-driven removal and rescan recovery.
No redacted before/live/after capture is archived for this run. Known scan gaps
mean the clear verdict is not proof that every resource was released. The
September 6 failure on 0.3.54 remains historical evidence for that earlier run.

**This is not unplug clearance.** Physical live removal remains unsupported and
shutdown before disconnect remains required. Three limits keep this from being a
disconnect precondition: the holder scan can report clear while holders remain
([#120](https://github.com/ronnierosal/Re-Gear/issues/120)), the clear state does
not persist because the filter detaches as success is reported
([#123](https://github.com/ronnierosal/Re-Gear/issues/123)), and no reviewed
software-removal tool exists on the installed build
([PR #122](https://github.com/ronnierosal/Re-Gear/pull/122), unmerged at this review). Nothing is
wired to a player-facing control; the capability is operator CLI only.

The earlier OpenGL and Vulkan selection experiment is packaged in **0.3.56**, tracked
in [draft PR #82](https://github.com/ronnierosal/Re-Gear/pull/82), staged and **not
installed or hardware validated**.

Follow [the resource-release experiment (#51)](https://github.com/ronnierosal/Re-Gear/issues/51)
and [remaining audio ownership (#52)](https://github.com/ronnierosal/Re-Gear/issues/52).
See the [dated evidence summary](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DISCONNECT_PROGRESS_2026-09-08.md)
and the [device filter release record](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVICE_FILTER_RELEASE_2026-09-08.md)
for the tested configuration, measurements, and limits.

Scan completeness is being addressed in [PR #137](https://github.com/ronnierosal/Re-Gear/pull/137),
stacked on the filter-lifetime work in [PR #124](https://github.com/ronnierosal/Re-Gear/pull/124).
Both were open at this review; their tests do not upgrade the historical hardware report.

## Remaining gates

Repeatable attach, TV picture, audio, gameplay, Portable return, reconnect, and physical shutdown need coordinated validation on the exact build. Experimental launch trials and local regression tests do not establish live-removal support.

See [Safety and eGPU Handling](Safety-and-eGPU-Handling), the [deployment gates](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEPLOYMENT_VALIDATION.md), and the [historical incident](Ally-X-and-GPD-G1-Docking-Incident).

See **[Confirmed Hardware Testing](Confirmed-Hardware-Testing)** for the capability-by-capability test ledger and **[Offline Play Readiness](Offline-Readiness)** for game checks.
