# Re-Gear Wiki

**Audience:** players, testers, and contributors<br>
**Reviewed:** 2026-09-06<br>
**Maturity:** experimental development; no general public release

Welcome to the player and contributor guide for Re-Gear, a Decky Loader companion for SteamOS handhelds. Re-Gear is designed for SteamOS handheld PCs across hardware vendors. It explains system state and provides capability-aware docking, recovery, and offline play guidance. Features depend on the device profile and available evidence; the project is not limited in scope to one handheld or eGPU brand.

## Our core goal

**Make SteamOS handheld PCs feel more like consoles:** help players get into their games, move between handheld and docked play, and recover from problems with less troubleshooting, across hardware vendors.

Our immediate priorities are **reliability and recovery**, **offline play confidence**, and **everyday controller-friendly usability**. See the [Feature Roadmap](Feature-Roadmap) for the focus order and development status.

## Featured guides

- **[Confirmed Hardware Testing](Confirmed-Hardware-Testing)** — tested devices, observed successes, failed gates, and remaining validation.
- **[Offline Play Readiness](Offline-Readiness)** — where to find checks, what the badges mean, and preparing a game before leaving Wi-Fi.

- **[Help Improve Re-Gear](Help-Improve-Re-Gear)** — report a problem, collect reviewed diagnostics, and contribute useful compatibility evidence.

## Start here

- [Getting Started](Getting-Started): availability and controlled testing.
- [Current State](Current-State): implemented features and remaining validation.
- [Supported Hardware](Supported-Hardware): the exact profiles with evidence.
- [Safety and eGPU Handling](Safety-and-eGPU-Handling): connection, sleep, and shutdown boundaries.
- [Offline Play Readiness](Offline-Readiness): what game badges can and cannot tell you.
- [Troubleshooting](Troubleshooting): common symptoms and reporting a bug.
- [FAQ](FAQ): quick answers.

## For contributors

Read [Project Overview](Project-Overview), [How Re-Gear Works](How-HDM-Works), [Development](Development), and [Diagnostics and Privacy](Diagnostics-and-Privacy). [Issues Fixed](Issues-Fixed) links selected changes to their evidence; the [historical docking incident](Ally-X-and-GPD-G1-Docking-Incident) explains earlier failures.

The [repository README](https://github.com/ronnierosal/Re-Gear#-current-status) identifies the current development candidate and integration branch. The Wiki explains the product; [repository contracts](https://github.com/ronnierosal/Re-Gear/blob/main/docs/INDEX.md) own engineering and support claims. A newer candidate is not automatically installed or hardware certified.

> **eGPU safety:** follow the verified disconnect policy for your exact hardware. Current Re-Gear testing does not establish physical live-removal support. Restore or retain a known-good state and fully shut down before disconnecting. A Portable display or an accepted shutdown request does not prove safe removal.
