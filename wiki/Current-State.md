# Current state

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-08, source baseline `de90cd4`<br>
**Maturity:** experimental development; no supported public release

This is a dated implementation checkpoint. The repository
[documentation review](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DOCUMENTATION_CLEANUP.md)
records the reconciled source evidence and the
[earlier source/installation snapshot](https://github.com/ronnierosal/Re-Gear/blob/main/docs/STATUS_SNAPSHOT_2026-09-08.md)
preserves the earlier review. [Current repository state](https://github.com/ronnierosal/Re-Gear/blob/main/docs/CURRENT_STATE.md)
retains historical integration and device records; it is not a live device observation.

## Implementation checkpoint

Main declares **0.3.58** at the reviewed revision. GitHub publishes
[development-candidate releases](https://github.com/ronnierosal/Re-Gear/releases);
these are distinct from a supported general release or Decky Store registration. The release lineage has been
reconciled, but [#116](https://github.com/ronnierosal/Re-Gear/issues/116) still
tracks the installable-build/candidate gap. A version number or merged branch
does not establish a complete installable feature set.

| Area | Implemented or reviewed work | Remaining gate |
|---|---|---|
| Quick Access | Existing section chooser/navigation merged in [#129](https://github.com/ronnierosal/Re-Gear/pull/129) | New [Command Center](Command-Center) foundation [#153](https://github.com/ronnierosal/Re-Gear/pull/153) remains draft; complete shell, module UI, and native acceptance pending |
| Performance | Manual/Auto TDP development source integrated through [#49](https://github.com/ronnierosal/Re-Gear/pull/49) | [#132](https://github.com/ronnierosal/Re-Gear/pull/132) guard refinements remain draft; provider and hardware acceptance pending |
| Offline Readiness | Local selected-game guidance, confidence labels, badges, and bounded refresh recovery | Native view/controller validation and actual offline launches remain distinct from source tests |
| eGPU release | Filter lifetime [#124](https://github.com/ronnierosal/Re-Gear/pull/124) and complete holder-scan evidence [#137](https://github.com/ronnierosal/Re-Gear/pull/137) merged | Installed behavior, persistent integration, and fresh captured hardware evidence still needed |
| Software removal | Operator tool [#122](https://github.com/ronnierosal/Re-Gear/pull/122) landed through [#148](https://github.com/ronnierosal/Re-Gear/pull/148), with fresh-plan guards | No player-facing live-disconnect RPC/UI; [#146](https://github.com/ronnierosal/Re-Gear/issues/146) remains open |
| Recovery state | Pure interrupted-removal record and storage port [#152](https://github.com/ronnierosal/Re-Gear/pull/152) merged | Storage adapters and runtime wiring remain; duplicated filter-ownership model from #150 was removed by [#155](https://github.com/ronnierosal/Re-Gear/pull/155) |
| Controllers | Routing/diagnostic foundations; gyro research [#154](https://github.com/ronnierosal/Re-Gear/pull/154) open | Broader configuration, gyro, rumble, LEDs and player order are not established working features; see [Controllers](Controllers) |

## Installed and hardware evidence

The September 8 operator account reports installed **0.3.58**, enforcement of a
device filter, a clear holder verdict, and source-driven software removal/rescan.
No redacted before/live/after capture is archived for that run
([#136](https://github.com/ronnierosal/Re-Gear/issues/136)). Scan gaps in that run
remain an evidence limit even though a later code fix merged. This documentation
review did not inspect a device or verify its current build/checksum.

Earlier supervised sessions produced individual TV/render, audio, and Portable
successes alongside recovery failures. They do not establish repeatable operation,
support for other hardware, or physical live-removal safety. See
[Confirmed Hardware Testing](Confirmed-Hardware-Testing) for the dated ledger.

The separate **0.3.56** graphics trial in [draft #82](https://github.com/ronnierosal/Re-Gear/pull/82)
remains recorded as staged and unvalidated. Compare exact ancestry and artifacts,
not version numbers across branches.

## Remaining disconnect and release gates

- Complete build provenance and the installable candidate tracked in [#116](https://github.com/ronnierosal/Re-Gear/issues/116).
- Connect the existing filter/removal/recovery components to the guarded runtime and player flow in [#146](https://github.com/ronnierosal/Re-Gear/issues/146).
- Resolve the physical-removal contract in [#147](https://github.com/ronnierosal/Re-Gear/issues/147), external-display release evidence in [#143](https://github.com/ronnierosal/Re-Gear/issues/143), and USB recovery concerns in [#105](https://github.com/ronnierosal/Re-Gear/issues/105).
- Capture repeatable exact-build attach, display, audio, gameplay, Portable return, recovery, reconnect, and physical shutdown evidence.

**Current physical live eGPU removal remains unsupported.** Follow
[Safety and eGPU Handling](Safety-and-eGPU-Handling). Development toward a live
disconnect feature does not change today's shutdown-before-disconnect requirement.
