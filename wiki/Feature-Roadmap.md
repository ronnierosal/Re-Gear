# Feature Roadmap

**Reviewed:** 2026-09-06. This is the player-facing focus order, not a delivery-date promise or hardware-support claim. The [engineering roadmap](https://github.com/ronnierosal/Re-Gear/blob/main/docs/ROADMAP.md), candidate source, and linked issues own implementation and acceptance details.

## Core goal

Re-Gear makes SteamOS handheld PCs feel more like consoles: helping players get into their games, move between handheld and docked play, and recover from problems with less troubleshooting. We prioritize reliable gameplay, clear status, low overhead, and safe recovery across hardware vendors.

## Focus and priority

| Priority | Focus | Player benefit | Current status and next gate |
|---|---|---|---|
| Now — 1 | Reliability and recovery | Predictable docking, display/audio handoff, Portable return, sleep/wake, and reconnect | Implemented paths and bounded device successes; repeated end-to-end acceptance remains |
| Now — 2 | Offline play confidence | Fewer surprises when leaving Wi-Fi | Candidate game checks, badges, and refresh recovery; real offline-launch evidence remains distinct |
| Now — 3 | Everyday usability | Clear controller navigation, contextual actions, and useful progress messages | Compact UI implemented in candidates; visible/controller acceptance depends on the installed build |
| Next — 4 | Performance and power | Guarded controls with understandable, measurable effects | Development/review work; provider ownership and hardware validation must precede support claims |
| Ongoing — 5 | Broader compatibility | More handhelds, docks, eGPUs, displays, and controllers earn verified support | Additional profiles require their own evidence; runs alongside feature work |

## Helping users contribute evidence

Existing support preview and a read-only diagnostic CLI are available for reviewed reports. A packaged, easy-to-run diagnostic helper is a future usability improvement, not a released tool. It should reuse the same bounded collector and provide local review before sharing. See [Help Improve Re-Gear](Help-Improve-Re-Gear).

## How to read feature status

Priority and status are separate. Use **Proposed**, **In development**, **Available for testing**, **Validated for a named configuration**, and **Released**. A passing unit test, uploaded package, or installed candidate does not imply hardware validation.

Each feature guide should explain the problem, intended behavior, what works today, what is missing, and the acceptance criteria for advancing. See [Current State](Current-State), [Offline Play Readiness](Offline-Readiness), [Confirmed Hardware Testing](Confirmed-Hardware-Testing), and [GitHub issues](https://github.com/ronnierosal/Re-Gear/issues). Keep detailed backlog and investigation in issues rather than expanding the homepage indefinitely.
