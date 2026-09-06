# Confirmed Hardware Testing

**Reviewed:** 2026-09-06. This ledger records historical supervised results, not a new test session or blanket certification.

## Tested hardware

ASUS ROG Ally X running SteamOS, GPD G1 with AMD Radeon RX 7600M XT, and a TV connected directly to the G1. Other combinations are not confirmed by similarity. See [Supported Hardware](Supported-Hardware).

## Confirmed observations

| Test | Recorded result | Evidence and limits |
|---|---|---|
| Exact hardware discovery and Portable inference | Observed on the first Ally X/G1 profile | [Initial native validation, August 31](https://github.com/ronnierosal/Re-Gear/blob/main/docs/HARDWARE_VALIDATION_2026-08-31.md); observation does not prove display handoff |
| Automatic TV docking and external rendering | Steam visible on TV; RX 7600M XT selected; transition committed | [September 2 incident](https://github.com/ronnierosal/Re-Gear/blob/main/docs/ALLY_X_GPD_G1_DOCKING_INCIDENT_2026-09-02.md); bounded watched success |
| Automatic G1 HDMI selection and Portable return | Later retry selected G1 HDMI as default; Prepare G1 disconnect returned to the internal display | Same incident record; default-sink observation is distinct from player-confirmed audible output |
| Portable trial: screen, audio, and controls | Player confirmed normal Ally screen, audio, and controls after returning to Portable on September 5 | [Dated trial evidence](https://github.com/ronnierosal/Re-Gear/blob/560ec33/docs/CURRENT_STATE.md); external GPU references remained, so this did not prove resource release |

## Failed or incomplete gates

| Gate | Result |
|---|---|
| Full physical shutdown | A watched request lost networking but left fan and LEDs on; forced player power-off was required |
| External resource release after Portable return | Retained Gamescope/Steam render references and audio control were observed in the September 5 trial |
| Repeated attach, audio, gameplay, return, and reconnect | Individual successes do not establish repeatability; complete acceptance remains pending |
| Live G1 removal | Unsupported; no safe-removal certification |
| Boosted Handheld | Unproven |
| Offline game launch | No confirmed game-specific offline-launch result is asserted by this page; badges and local tests are not launch proof |

## Recording another confirmed test

Record the date, exact Re-Gear build/revision, SteamOS version, hardware combination, expected and observed result, player-visible confirmation where relevant, and a redacted evidence link. Label pass, fail, or incomplete for each capability separately. Record recovery and remaining blockers. GitHub issues track defects; this ledger summarizes reviewed evidence.

Never include private addresses, credentials, raw identifiers, or unrestricted logs. Follow [Safety and eGPU Handling](Safety-and-eGPU-Handling): fully shut down before G1 disconnect, even when Portable appears normal.
