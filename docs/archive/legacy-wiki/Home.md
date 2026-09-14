> **Archived September 14, 2026.** Historical source at `9421c6f`; superseded by the [canonical Wiki](https://github.com/ronnierosal/Re-Gear/tree/main/docs/wiki). Do not use this as current instructions.

# Re-Gear Wiki

## Player manual — start here

New to Re-Gear? Read the **[Player Manual](Player-Manual.md)** for a plain-language
tour: what Re-Gear does, where to find controls, what the messages mean, and how
to get help. For a visual tour, use the **[Player Visual Guide](Player-Visual-Guide.md)**.
The visual guide currently uses clearly labeled temporary mockups while the native
Decky interface is still being validated.

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-13<br>
**Maturity:** experimental development; no supported public release

> **Release status:** No public supported Re-Gear release is available. Current
> GitHub releases are development candidates; ordinary users must not treat a
> mockup, screenshot, or development build as a hardware-support claim.

<!-- Keep release status aligned with Getting-Started.md. Temporary generated/mockup
visuals are allowed only when visibly labeled as mockups. Replace them with real
installed Decky screenshots after visual/native validation and record build/capture
context. Never present a mockup as validation evidence. -->

Re-Gear is a Decky Loader companion for SteamOS handheld gaming: clear status,
useful controls, and guided recovery across handheld and docked play. The README
introduces the project; this Wiki explains its features, limitations, and evidence.

## Start here

- [Getting Started](Getting-Started.md) — availability and controlled testing.
- [Player Visual Guide](Player-Visual-Guide.md) — temporary visual tour of menus and customization.
- [Manual Installation](Manual-Installation.md) — the future verified-release ZIP route.
- [Current State](Current-State.md) — what is merged, in development, and tested.
- [Feature Roadmap](Feature-Roadmap.md) — focus areas and gates ahead.
- [Supported Hardware](Supported-Hardware.md) and [Confirmed Hardware Testing](Confirmed-Hardware-Testing.md) — compatibility and recorded results.

## Feature guides

| Guide | What you will find |
|---|---|
| [Command Center](Command-Center.md) | Quick controls, status links, modules, and the interface rebuild |
| [Player Visual Guide](Player-Visual-Guide.md) | Performance, eGPU, Controllers, Settings, Quick Access customization and button how-tos |
| [eGPU and Docking](eGPU-and-Docking.md) | Placement, guarded display changes, disconnect development, and recovery limits |
| [Performance and Power](Performance-and-Power.md) | Manual TDP, Auto TDP, provider requirements, and validation |
| [Controllers](Controllers.md) | Navigation, shortcuts, extra buttons, and capability research |
| [Offline Readiness](Offline-Readiness.md) | Selected-game checks, confidence labels, badges, and offline-test limits |

## Help and contribution

[Troubleshooting](Troubleshooting.md), [FAQ](FAQ.md), and [Diagnostics and Privacy](Diagnostics-and-Privacy.md)
explain common questions and reviewed diagnostic collection. [Help Improve Re-Gear](Help-Improve-Re-Gear.md)
describes useful reports. Contributors start with [Project Overview](Project-Overview.md),
[How Re-Gear Works](How-HDM-Works.md), and [Development](Development.md).

Repository contracts and evidence remain authoritative. A Wiki guide, mockup, or
screenshot is not a hardware-support claim. For current eGPU handling, read
[Safety and eGPU Handling](Safety-and-eGPU-Handling.md): current testing does not
establish live unplug safety; complete shutdown remains required before physical
disconnect.