# Feature Roadmap

**Audience:** players and contributors<br>
**Reviewed:** 2026-09-26 (eGPU row)<br>
**Maturity:** development priorities, not delivery dates or support promises

Re-Gear aims to reduce everyday friction in SteamOS handheld gaming. The
[engineering roadmap](https://github.com/ronnierosal/Re-Gear/blob/main/docs/ROADMAP.md)
owns contracts and acceptance gates; [Current State](current-state.md) gives the
reviewed implementation checkpoint.

## Focus areas

| Focus | Player benefit | Priority, status, and next gate |
|---|---|---|
| eGPU reliability and recovery | Predictable display/audio handoff, return, and disconnect | Active reliability priority. Ordinary Safe Disconnect has supervised passes on one configuration; merged source (packaged as local development build 0.3.154) adds first-time authorization, staged progress, a still-connected authorization hold, and guarded Disconnect + Sleep and Shutdown, pending supervised hardware validation. Software reconnect is excluded |
| Command Center and modules | Common controls at hand, deeper settings easy to find | Active interface rebuild; approved design, existing navigation merged, new foundation under review; native controller acceptance pending |
| Offline Readiness | Fewer surprises away from Wi-Fi | Implemented local guidance and refresh recovery; continue exact-game/view validation without turning confidence into a guarantee |
| Performance and power | Understandable manual power limits and optional Auto TDP | Development source implemented; provider guards under review and device acceptance pending |
| Controller capabilities | Reliable built-in/external controls and supported customization | Routing foundation plus research/backlog for shortcuts, gyro, rumble, LEDs and player order; verify provider and device behavior before exposing writes |
| Broader compatibility | More configurations earn supported capabilities | Ongoing evidence work; each device/transport/capability requires its own validation |

## What advances a feature

Design, implementation, simulation, installation, hardware testing, and release
are separate steps. A merged PR does not prove the feature is installed, and a
successful device observation does not certify all builds or hardware.

Each [feature guide](../README.md#feature-guides) states the benefit, current status, and
remaining gates. [Issues](https://github.com/ronnierosal/Re-Gear/issues) track
concrete work. Help with reviewed reports through [Help Improve Re-Gear](../player/help-improve.md).
No date or expanded hardware support is promised by this roadmap.
