# Hardware support model

## Support tiers

- **Certified:** directly tested with captured evidence and bounded known behavior.
- **Compatible:** expected to work through standard mechanisms but not fully
  validated on hardware.
- **Experimental:** detected and intentionally available for controlled testing.
- **Unsupported:** blocked because required identity, safety, or mechanism is absent.

A combination-level tier does not verify every feature. Capabilities such as
display handoff, audio handoff, controller ordering, sleep behavior, and live
removal retain independent evidence/status. In particular, the certified
Ally X/G1 identity does not override its shutdown-before-disconnect rule or
turn untested live removal into a supported capability.

## Catalog evidence model

The pure catalog schema stores a combination status separately from individual
capability claims. Capabilities include exact identity, eGPU detection, external
display output, display/audio handoff, Docked-iGPU, sleep behavior, live
removal, controller handoff/suppression, and optional controller power-off.

The R7a composite controller/audio plan is implemented and simulated only. Its
private bindings and recovery ordering do not promote any physical capability;
live observers, mechanisms, and supervised rollback proof remain required.

Simulation and passive observation cannot promote either a combination or a
capability. Promotion requires an intentional reviewed test with exact
host/eGPU profiles, Re-Gear and SteamOS versions, and a timestamp. Read-only hardware
evidence may verify identity/detection/output observation, but a mutating
capability needs supervised hardware evidence plus verified rollback or
recovery. Live-removal verification additionally requires expected removal,
verified Portable recovery, and clean kernel evidence.

Known Issue and Unsupported remain first-class outcomes rather than being
silently translated into support. The schema and tests now have a dormant,
fixed-path atomic local store for already validated catalog records; it cannot
collect evidence or expose a Decky write path. Its backend-only transaction
service can apply only the existing domain promotion rules under the store lock;
it neither creates/reviews evidence nor runs in the production plugin. Existing
claims remain limited to the evidence in this document and dated validation
records.

## First certified profile

| Component | Identity |
|---|---|
| Host | ASUS ROG Ally X running SteamOS |
| eGPU | GPD G1, AMD Radeon RX 7600M XT (`1002:7480`) |
| HDMI audio | AMD `1002:ab30` |
| Removable bridge | Intel Titan Ridge `8086:15ef` |
| xHCI | Intel `8086:15f0` |
| Observed USB4 device | Intel Tapex Creek |

The certified host matcher accepts only the normalized full DMI tuple captured
from the validated Ally X: `ASUSTeK COMPUTER INC.` / `ROG Ally X RC72LA` /
`RC72LA`. Similar product names, partial fields, and substring matches remain
Unknown. A firmware update that changes this tuple requires review and new
read-only evidence before the profile matcher is expanded.

Runtime resolution uses an explicit profile catalog. A catalog entry pairs one
profile ID with its conservative capability record; eGPU entries also require a
strict opaque stable-ID matcher. No fuzzy product-name fallback exists, and
ambiguous or absent catalog matches retain Unknown capability values. The
catalog currently contains only the Ally X and GPD G1 profiles described here;
adding an entry is not a certification claim and needs its own evidence.

The complete topology and privacy-preserving USB4 identity must be verified; the
GPU PCI ID alone does not prove that the device is the certified G1. The live G1
topology contains one top-level removable Titan Ridge bridge and multiple
downstream `8086:15ef` bridge functions. The USB4 host-router record has no
external-device identity and is not counted as a connected peripheral; any
other unidentified authorized USB4 node remains a certification blocker.
The GPU DRM and PCI functions must be bound to `amdgpu`, the removable bridge to
`pcieport`, HDMI audio to `snd_hda_intel`, and xHCI to `xhci_hcd`. Runtime G1
resolution also requires the exact hashed-identity form to match the backend
disconnect-scan binding; neither value is delivered to the frontend.

Read-only diagnostics report independent transport, display output/handoff,
audio output/handoff, controller, power-button, sleep, and removal axes. For the
current profile, output observation is Verified, display/audio handoff remains
Experimental, controller capabilities remain Unknown, sleep requires the
verified disconnect-first workflow, and removal remains
`shutdown_before_disconnect`.

The diagnostic matrix is structurally complete: local construction rejects any
duplicate or omitted capability axis. This guards later profile edits and does
not promote a capability or add hardware observation.

## eGPUBridge reference evidence

- Internal and G1-connected TV discovery
- Portable ↔ TV output transitions in approximately 4–6 seconds
- Exact G1 identity persistence without storing its raw USB4 unique ID
- Fail-closed Steam game detection
- Running-game transition blocking without restarting Gamescope
- Idempotent internal restore

These observations informed Re-Gear design but are not proof that native Re-Gear has
implemented or certified the corresponding mutations. Current native Re-Gear
hardware evidence is listed in the dated validation record and the
[authoritative roadmap](ROADMAP.md).

## Unproven or unsupported

- G1 rendering to the Ally internal panel remains unproven.
- Mid-game iGPU presentation on the TV remains a research case.
- Physical live eGPU removal is unsupported.
- The G1 currently requires a shutdown-before-disconnect policy. It must not be
  assigned a live-removal capability without a separate approved teardown
  experiment and clean recovery evidence.
- Other hosts, eGPUs, and SteamOS versions are not certified by inference.

All addresses and connector names observed during validation are ephemeral and
must be rediscovered after boot, reconnect, and resume.

See [Re-Gear 0.1 read-only hardware validation](HARDWARE_VALIDATION_2026-08-31.md)
for the first native snapshot result and its privilege-boundary finding.
