# Supported hardware

**Audience:** players, testers, and profile contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** one exact first profile; capability status varies

The authoritative compatibility model is
[Hardware support](https://github.com/ronnierosal/Re-Gear/blob/main/docs/HARDWARE_SUPPORT.md).

## Initial validated profile

| Component | Profile |
|---|---|
| Host | ASUS ROG Ally X running SteamOS |
| eGPU/dock | GPD G1 |
| Render GPU | AMD Radeon RX 7600M XT |
| Display path | TV attached through a G1 display output |

Re-Gear matches the full recorded host and eGPU topology conservatively. A similar
product name or matching GPU PCI ID alone is not enough. Runtime card numbers,
connector suffixes, and bus addresses are rediscovered and are never persistent
identity.

## What “certified” does not mean

Certification applies to a defined profile and capability with evidence; it is
not a blanket promise. The exact profile can be recognized while Boosted
Handheld, physical live removal, a particular sleep path, or the latest TV
transition remains experimental, unsupported, or awaiting new proof.

Other ROG Ally models, Lenovo Legion Go devices, Steam Deck, other SteamOS
handhelds, Thunderbolt/USB4 enclosures, NVIDIA eGPUs, displays, and docks are not
supported merely because the architecture intends to accommodate them.

## Adding another profile

A future profile should supply exact identity, capabilities, mechanisms, and
quirks while core policy remains product-neutral. It needs synthetic boundary
tests and then capability-specific hardware evidence. Fuzzy device-name
matching or falling back to `card0`, `card1`, or a connector name is not
acceptable.
