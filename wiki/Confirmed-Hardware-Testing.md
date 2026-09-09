# Confirmed Hardware Testing

**Reviewed:** 2026-09-09. This ledger records historical supervised results, not a new test session or blanket certification.

## Hardware testing scope

Re-Gear is designed for SteamOS handheld PCs, docks, eGPUs, and external displays across hardware vendors. This ledger tracks validation by capability so results from additional configurations can be recorded consistently.

Each result below applies only to the exact hardware and software configuration documented in its linked evidence. The entries currently summarize one recorded test configuration; they do not establish cross-device validation. Device models belong to those individual test records, not the definition of Re-Gear. See [Supported Hardware](Supported-Hardware) for compatibility details.

## Recorded observations and evidence limits

| Test | Recorded result | Evidence and limits |
|---|---|---|
| Exact hardware discovery and Portable inference | Observed on the configuration in the linked test record | [Initial native validation, August 31](https://github.com/ronnierosal/Re-Gear/blob/main/docs/HARDWARE_VALIDATION_2026-08-31.md); observation does not prove display handoff |
| Automatic TV docking and external rendering | Steam visible on TV; external GPU selected; transition committed | [September 2 incident](https://github.com/ronnierosal/Re-Gear/blob/main/docs/ALLY_X_GPD_G1_DOCKING_INCIDENT_2026-09-02.md); bounded watched success |
| Automatic external HDMI selection and Portable return | Later retry selected external HDMI as default; the disconnect-preparation workflow returned to the internal display | Same incident record; default-sink observation is distinct from player-confirmed audible output |
| Portable trial: screen, audio, and controls | Player confirmed normal handheld screen, audio, and controls after returning to Portable on September 5 | [Dated trial evidence](https://github.com/ronnierosal/Re-Gear/blob/560ec33/docs/CURRENT_STATE.md); external GPU references remained, so this did not prove resource release |
| eGPU client release under a device filter | Operator reported enforcement before restart and a clear holder verdict; complete release is not independently established | [Device filter release record, September 8](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DEVICE_FILTER_RELEASE_2026-09-08.md); installed 0.3.58, operator CLI only. Recorded from the supervised session, not yet backed by a capture artifact. Release is not unplug clearance, and the clear verdict has known scan gaps ([#120](https://github.com/ronnierosal/Re-Gear/issues/120)) |
| eGPU software removal and rescan recovery | Operator reported both PCI functions detached and restored by rescan with drivers rebound | Same record; driven from a source checkout rather than the installed plugin, so this is evidence about the kernel and device, not about an installed feature |
| External display release and automatic restore, September 9 | With the compositor on the internal panel, the eGPU still had a mode committed on one CRTC. Taking DRM master on that card and turning the CRTC off cleared it; closing the descriptor restored the console's mode on the same framebuffer | Two supervised runs, root, cable attached. Scoped to the eGPU's card: the internal panel was never opened. Recovery is the descriptor closing, so it also happens if the process dies. One configuration only |
| Live eGPU software removal with the handheld powered, September 9 | The full sequence ran end to end: filter armed with enforcement verified, approved restarts performed, holders cleared, display released, removal safety assessed against fresh evidence, durable record written, both PCI functions detached and verified absent, display restored, filter disarmed. Confirmed independently of the tool's own report | Driven from a source checkout on the device, not the installed plugin. The player's Steam session **restarted**, because that is what released the holders. No capture artifact archived ([#136](https://github.com/ronnierosal/Re-Gear/issues/136)). **Not unplug clearance** |
| Live disconnect driven by the backend RPC, September 9 | The same sequence run through `execute_egpu_disconnect` rather than the operator tool. The backend performed both approved restarts itself and verified each released the device; no restart was typed by hand. Reported `stage: removed`, both functions detached, `display_released: [98]`, `filter_disarmed: true`, `device_disturbed: false` | Driven from a source checkout with the current backend, not the shipped 0.3.62, which predates a status fix made the same day. Decky's transport was not in the path: the runtime was called directly. The session still restarted |
| Restore after live removal, September 9 | A bus rescan returned both functions with `amdgpu` and `snd_hda_intel` rebound, DRM nodes back, no durable record left and no filter attached | Same session. The connector returned without a committed mode, because nothing had driven the external display since |

The [September 6 return-run summary](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DISCONNECT_PROGRESS_2026-09-06.md)
records installed 0.3.54: TV output followed by player-confirmed normal internal
display, controls, and audio. Steam and Gamescope retained external allocations;
WirePlumber retained audio control. This adds evidence of the resource-release
blocker, not live-removal validation. Follow [#51](https://github.com/ronnierosal/Re-Gear/issues/51)
and [#52](https://github.com/ronnierosal/Re-Gear/issues/52).

A later operator account reported a clear result on installed 0.3.58, with scan
gaps and no archived capture preventing independent confirmation; see the
[September 8 summary](https://github.com/ronnierosal/Re-Gear/blob/main/docs/DISCONNECT_PROGRESS_2026-09-08.md).
Those scan gaps are now understood rather than merely noted: the client scan
could not complete on a live system at all, because a descriptor closing during
the scan marked the whole reading incomplete. See
[Fixes and issue tracking](Issues-Fixed).

Client release is not live-removal validation, and neither is software removal:
physical live unplug remains unsupported and shutdown before disconnect remains
required.

## Failed or incomplete gates

| Gate | Result |
|---|---|
| Full physical shutdown | A watched request lost networking but left fan and LEDs on; forced player power-off was required |
| External resource release after Portable return | Retained Gamescope/Steam render references and audio control were observed in the September 5 trial |
| Repeated attach, audio, gameplay, return, and reconnect | Individual successes do not establish repeatability; complete acceptance remains pending |
| Live eGPU **physical** removal | Unsupported; no safe-removal certification. Software removal having succeeded does not change this |
| Live disconnect without disturbing the session | Not achieved. The September 9 removal restarted the player's Steam session, which is what released the holders ([#178](https://github.com/ronnierosal/Re-Gear/issues/178)) |
| Live disconnect through Decky's own RPC transport | Not achieved. The runtime behind the RPC has run on a device and removed the eGPU, but it was called directly rather than over Decky's channel, and from a source checkout rather than the installed build |
| Interrupted-removal recovery | Implemented and never exercised: no run has been interrupted deliberately to observe the restore |
| Boosted Handheld | Unproven |
| Offline game launch | No confirmed game-specific offline-launch result is asserted by this page; badges and local tests are not launch proof |

## Recording another confirmed test

Record the date, exact Re-Gear build/revision, SteamOS version, hardware combination, expected and observed result, player-visible confirmation where relevant, and a redacted evidence link. Label pass, fail, or incomplete for each capability separately. Record recovery and remaining blockers. GitHub issues track defects; this ledger summarizes reviewed evidence.

Never include private addresses, credentials, raw identifiers, or unrestricted logs. Follow [Safety and eGPU Handling](Safety-and-eGPU-Handling): fully shut down before eGPU disconnect under the current tested policy, even when Portable appears normal.
