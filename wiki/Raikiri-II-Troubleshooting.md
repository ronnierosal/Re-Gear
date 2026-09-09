# Raikiri II extra-button troubleshooting

**Audience:** Raikiri II users and input contributors<br>
**Evidence reviewed:** 2026-09-08; source investigation recorded September 6<br>
**Maturity:** transport-specific observations and diagnostic/routing foundations; no installed menu-mapping fix

## 1. Scope / who this helps

This page concerns the ASUS ROG Raikiri II extra front buttons and the goal of
opening Steam's main menu and Quick Access while preserving ordinary controls.
Bluetooth, PC-mode wireless dongle and USB cable are separate test contexts.
No behavior transfers to another mode, transport or controller by similarity.

## 2. Situation (what / where / when)

[Issue #23](https://github.com/ronnierosal/Re-Gear/issues/23) records earlier
Bluetooth evdev captures and PC-mode dongle investigation. The
[September 6 technical note](https://github.com/ronnierosal/Re-Gear/blob/main/docs/RAIKIRI_CONTROLLER_SUPPORT.md)
pins upstream activation/decoder sources and documents a standalone diagnostic.
This review did not capture new controller events or operate a device.

## 3. Symptoms

- In the recorded Bluetooth captures, the extra buttons duplicated ordinary L3/R3 stick-click events; they were not independently distinguishable through that observed input path.
- PC-mode ordinary controls working did not establish that Steam received distinct extra-button events.
- Passive vendor-HID capture did not establish repeatable front-button events; capture timing was not consistently paired with button presses.

These observations do not prove that every firmware or possible Bluetooth input
path behaves identically. They do rule out treating the recorded duplicated
stick clicks as independent menu buttons.

## 4. Evidence and likely cause

The source-backed PC-mode approach enables vendor event reporting before capture.
The pinned RaikiriMapper source supplies activation and acknowledgement handling;
ShadowLink separately supplies a candidate front-button decoder. This explains
why passive listening alone can miss vendor events and provides a concrete
investigation path.

Combining those sources is not yet repeatable SteamOS front-button proof for
the tested unit. An activation acknowledgement only confirms a protocol response;
it does not prove correct left/right identification, release behavior or Steam
menu delivery. Windows-oriented source support is distinct from Linux hardware
validation. Exact references and diagnostic limits are in the technical note.

## 5. What Re-Gear does

The pure router matches exact device/transport evidence, deduplicates press edges
and resets around reconnects. Its tests use synthetic events. The standalone
diagnostic includes opt-in activation and candidate decoding, but marks events
unverified and sends nothing to the menu router. The plugin does not launch it.

Mapping and live routing remain in progress: no enabled Raikiri profile,
configuration UI or verified Steam main-menu/Quick Access adapter is established.
Globally remapping L3/R3 would steal ordinary controls and is not a supported fix.

## 6. Steps to try

1. Record the selected controller mode, connection type, firmware and Re-Gear/SteamOS build when reporting the symptom; omit serial numbers and raw device paths.
2. Compare each extra button with the corresponding ordinary stick click using existing input-test UI, and describe whether they appear identical. Keep normal game mappings intact.
3. Use the existing Steam/Decky access path while extra-button integration is unavailable.
4. Share a reviewed report through [Help Improve Re-Gear](Help-Improve-Re-Gear), linked to #23. Vendor activation/capture is a separately supervised investigation, not a general setup step.

Do not apply generic driver swaps, raw HID writes or global stick-click remaps
from this page. Reconnect behavior and configuration persistence remain part of
the device-specific investigation.

## 7. Verification status

| Evidence level | Established | Limit |
|---|---|---|
| Source / tests | Pinned activation/decoder leads and synthetic diagnostic/router tests | Source capability is not observed physical delivery |
| Merged | Routing/diagnostic foundation exists in reviewed main | No enabled live mapping or menu adapter |
| Installed | No installed Re-Gear extra-button fix established | Ordinary controller operation is a separate result |
| Hardware tested | Prior Bluetooth captures duplicated L3/R3; ordinary PC-mode controls were player-confirmed in issue #23 | Repeatable independent front-button capture, SteamOS mapping, holds/releases and reconnect remain unverified |

## 8. Known limits / unresolved work

Next evidence should compare a rear-button positive control, each front extra,
actual L3/R3, holds/releases and mixed presses in timestamped captures after
activation. Cold reconnect and each transport need independent tests. Only then
can a verified adapter feed the router and test native Steam menu delivery without
double triggers or game-input leakage. Capture evidence and a supported menu
delivery API are both required; one does not prove the other.

## 9. Related guides / issues / PRs

[Controllers](Controllers) · [Troubleshooting](Troubleshooting)
· [Issue #23](https://github.com/ronnierosal/Re-Gear/issues/23)
· [Technical source and diagnostic limits](https://github.com/ronnierosal/Re-Gear/blob/main/docs/RAIKIRI_CONTROLLER_SUPPORT.md)
