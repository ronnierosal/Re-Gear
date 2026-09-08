# Re-Gear Wiki

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-08<br>
**Maturity:** experimental development; no supported public release

> **Release status — 2026-09-08:** No public supported Re-Gear release is available.
> Current [GitHub releases](https://github.com/ronnierosal/Re-Gear/releases) are
> development candidates; ordinary users must not install them. The
> [Manual Installation](Manual-Installation) guide is conditional on a future
> verified, supported release ZIP and published checksum.

<!-- Keep this dated status aligned with Getting-Started.md. When a supported
release is verified, update both with its exact release, checksum and support scope.
Only add real Quick Access screenshots from an installed, visually verified build;
record the build and capture context. Do not use mockups or generated images. -->

Re-Gear is a Decky Loader companion for SteamOS handheld gaming: clear status,
useful controls, and guided recovery across handheld and docked play. The
[README](https://github.com/ronnierosal/Re-Gear) introduces the project; this Wiki
explains its features, limitations, and evidence.

## Start here

- [Getting Started](Getting-Started) — availability and controlled testing.
- [Manual Installation](Manual-Installation) — the future verified-release ZIP route; no public supported release is available yet.
- [Current State](Current-State) — what is merged, what is still in development, and what has been tested.
- [Feature Roadmap](Feature-Roadmap) — focus areas and the gates ahead.
- [Supported Hardware](Supported-Hardware) and [Confirmed Hardware Testing](Confirmed-Hardware-Testing) — exact compatibility and recorded results.

## Feature guides

| Guide | What you will find |
|---|---|
| [Command Center](Command-Center) | Quick controls, status links, modules, and the interface rebuild |
| [eGPU and Docking](eGPU-and-Docking) | Placement, guarded display changes, disconnect development, and recovery limits |
| [Performance and Power](Performance-and-Power) | Manual TDP, Auto TDP, provider requirements, and validation |
| [Controllers](Controllers) | Navigation, shortcuts, extra buttons, and capability research |
| [Offline Readiness](Offline-Readiness) | Selected-game checks, confidence labels, badges, and offline-test limits |

## Help and contribution

[Troubleshooting](Troubleshooting), [FAQ](FAQ), and
[Diagnostics and Privacy](Diagnostics-and-Privacy) explain common questions and
reviewed diagnostic collection. [Help Improve Re-Gear](Help-Improve-Re-Gear)
describes useful reports. Contributors start with [Project Overview](Project-Overview),
[How Re-Gear Works](How-HDM-Works), and [Development](Development).

Repository [contracts and evidence](https://github.com/ronnierosal/Re-Gear/blob/main/docs/INDEX.md)
remain authoritative. A Wiki guide or screenshot is not a hardware-support claim.
For current eGPU handling, read [Safety and eGPU Handling](Safety-and-eGPU-Handling):
current testing does not establish live unplug safety; complete shutdown remains
required before physical disconnect.
