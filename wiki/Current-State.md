# Current state

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-09, source baseline `358f411`<br>
**Maturity:** experimental development; no supported public release

This is a dated implementation checkpoint. The repository
[documentation review](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DOCUMENTATION_CLEANUP.md)
records the reconciled source evidence and the
[earlier source/installation snapshot](https://github.com/ronnierosal/Re-Gear/blob/main/docs/STATUS_SNAPSHOT_2026-09-08.md)
preserves the earlier review. [Current repository state](https://github.com/ronnierosal/Re-Gear/blob/main/docs/CURRENT_STATE.md)
retains historical integration and device records; it is not a live device observation.

## Implementation checkpoint

Main declares **0.3.67** at the reviewed revision. GitHub publishes
[development-candidate releases](https://github.com/ronnierosal/Re-Gear/releases);
these are distinct from a supported general release or Decky Store registration. [#116](https://github.com/ronnierosal/Re-Gear/issues/116) is closed; that tracker state
does not certify an artifact, an installation, or hardware support. A version
number or merged branch does not establish a complete installable feature set.

| Area | Implemented or reviewed work | Remaining gate |
|---|---|---|
| Quick Access | [Command Center](Command-Center) foundation [#153](https://github.com/ronnierosal/Re-Gear/pull/153), tile grid [#189](https://github.com/ronnierosal/Re-Gear/pull/189), and shared controls/routes [#212](https://github.com/ronnierosal/Re-Gear/pull/212) merged | Native installed Decky/controller acceptance and real device screenshots remain separate gates |
| Performance | Manual/Auto TDP integrated through [#49](https://github.com/ronnierosal/Re-Gear/pull/49); guard refinements [#132](https://github.com/ronnierosal/Re-Gear/pull/132) and shared module controls [#212](https://github.com/ronnierosal/Re-Gear/pull/212) merged | Provider and hardware acceptance remain distinct from fixture tests |
| Offline Readiness | Local selected-game guidance, confidence labels, badges, and bounded refresh recovery | Native view/controller validation and actual offline launches remain distinct from source tests |
| eGPU release | Filter lifetime [#124](https://github.com/ronnierosal/Re-Gear/pull/124) and complete holder-scan evidence [#137](https://github.com/ronnierosal/Re-Gear/pull/137) merged; the client scan and arm sequence repaired in [#187](https://github.com/ronnierosal/Re-Gear/pull/187) after both were found to refuse on a live system | Installed behavior and a captured artifact still needed; the September 9 runs were driven from a source checkout on the device |
| Software removal | Operator tool and backend runtime integrated through [#181](https://github.com/ronnierosal/Re-Gear/pull/181); source-driven September 9 operator observations are recorded below | Source observations do not establish installed Decky transport behavior or physical cable-removal safety |
| Disconnect presentation | Typed client/status mapping [#198](https://github.com/ronnierosal/Re-Gear/pull/198) and player controls [#212](https://github.com/ronnierosal/Re-Gear/pull/212) merged; [#214](https://github.com/ronnierosal/Re-Gear/pull/214) separates software removal, bus absence and cable clearance | A software-removal result does not authorize unplugging; complete dock/USB/link evidence and the physical-removal contract remain unresolved |
| Recovery state | Pure interrupted-removal record and storage port [#152](https://github.com/ronnierosal/Re-Gear/pull/152) merged; durable storage and the restore-never-continue path wired in [#181](https://github.com/ronnierosal/Re-Gear/pull/181) | The recovery path has not been exercised on hardware: no run has been interrupted deliberately |
| External display release | The eGPU keeps a mode committed after the return, held by the kernel console rather than any client; a DRM master release and its automatic restore merged in [#184](https://github.com/ronnierosal/Re-Gear/pull/184) and [#185](https://github.com/ronnierosal/Re-Gear/pull/185), closing [#168](https://github.com/ronnierosal/Re-Gear/issues/168) | Proven on one configuration only; the release lasts exactly as long as the descriptor holding it |
| Controllers | Routing/diagnostic foundations; gyro research [#154](https://github.com/ronnierosal/Re-Gear/pull/154) open | Broader configuration, gyro, rumble, LEDs and player order are not established working features; see [Controllers](Controllers) |

## Candidate provenance and historical status fixes

The useful history from [#200](https://github.com/ronnierosal/Re-Gear/pull/200) is
retained: 0.3.63 followed a 0.3.62 holder-status defect, and #198 supplied typed
disconnect presentation. Those versions and the then-inert tile are historical,
not the current implementation checkpoint.

The local 0.3.64 and 0.3.65 ZIPs match the hashes recorded in
[#204](https://github.com/ronnierosal/Re-Gear/pull/204), but both embed
`revision: uncommitted`; they cannot prove the exact source revisions claimed
in that PR. They remain preserved historical artifacts. The local 0.3.67 ZIP
embeds `9f7ce8192c014475e5d4adc81f85ac8dfb50d016` and SHA-256
`7fe98c9c9c4597ce5a5c0f89bad56ea502e8acec6533226feb86f987db3bd519`.
This is local archive evidence only; staging and installation reports belong
to the release/hardware owner. No device was inspected in this review.

## Installed and hardware evidence

On **September 9** a supervised session removed both eGPU PCI functions in
software while the handheld stayed powered and the cable stayed attached, then
restored them by bus rescan with drivers rebound. The sequence armed a device
filter with enforcement verified, performed the approved restarts, released the
external display, assessed removal safety against fresh evidence, and wrote a
durable record before the first detach. See
[Confirmed Hardware Testing](Confirmed-Hardware-Testing) for the dated entries
and their limits.

Three limits apply to that result and none of them are small. It was driven
from a **source checkout on the device**, not the installed plugin, so it is
evidence about the sequence and the kernel rather than about an installed
feature. The player's Steam session **restarted**, because that is what
released the holders. And no redacted before/live/after capture is archived
([#136](https://github.com/ronnierosal/Re-Gear/issues/136)), so the account is
the operator's record rather than artifact-backed validation.

The September 8 account reporting installed 0.3.58 remains accurate for that
build. Its scan gaps are now understood: the client scan could not complete on
a live system at all, which [#187](https://github.com/ronnierosal/Re-Gear/pull/187)
repaired.

This documentation review did not inspect a device or verify its current
build/checksum.

Earlier supervised sessions produced individual TV/render, audio, and Portable
successes alongside recovery failures. They do not establish repeatable operation,
support for other hardware, or physical live-removal safety. See
[Confirmed Hardware Testing](Confirmed-Hardware-Testing) for the dated ledger.

The separate historical **0.3.56** graphics trial in [closed #82](https://github.com/ronnierosal/Re-Gear/pull/82)
remains a dated staging record, not current installation evidence. Compare exact ancestry and artifacts,
not version numbers across branches.

## Remaining disconnect and release gates

- Verify each exact candidate independently; closed [#116](https://github.com/ronnierosal/Re-Gear/issues/116) is not a substitute for artifact provenance.
- Drive a disconnect through Decky's RPC transport from the shipped build. The runtime behind it has removed the eGPU on hardware with the backend performing its own restarts, so the automated restart step is no longer unproven; what remains untested is the channel and the packaged build.
- Establish whether the session restart is necessary. Today a live disconnect restarts the player's Steam session, which no player-facing flow can ask for silently; [#178](https://github.com/ronnierosal/Re-Gear/issues/178) asks whether the audio restart alone suffices.
- Resolve the physical-removal contract in [#147](https://github.com/ronnierosal/Re-Gear/issues/147) and USB recovery concerns in [#105](https://github.com/ronnierosal/Re-Gear/issues/105). External-display release evidence [#143](https://github.com/ronnierosal/Re-Gear/issues/143) and the console-held CRTC [#168](https://github.com/ronnierosal/Re-Gear/issues/168) are resolved.
- Exercise the interrupted-removal recovery path deliberately; it is implemented and untested on hardware.
- Capture repeatable exact-build attach, display, audio, gameplay, Portable return, recovery, reconnect, and physical shutdown evidence.

**Current physical live eGPU removal remains unsupported.** Follow
[Safety and eGPU Handling](Safety-and-eGPU-Handling). Development toward a live
disconnect feature does not change today's shutdown-before-disconnect requirement.

This is worth stating precisely, because the September 9 result is easy to
misread. Removing the eGPU **in software** while the system runs has now been
done. That is not the same as unplugging it, and it does not make unplugging it
safe. Whether an unplug may follow a verified software removal is
[#147](https://github.com/ronnierosal/Re-Gear/issues/147) and remains
undecided.
