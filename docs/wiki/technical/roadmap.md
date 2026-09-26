# Feature Roadmap

Re-Gear aims to reduce everyday friction in SteamOS handheld gaming. This page
shows what is being worked on and how far each area has got. It lists priorities,
not delivery dates or support promises. Reviewed against merged source `5ed1e3d`
on September 24, 2026.

## For players — no technical background needed

| Area | What it means for you | Where it stands |
|---|---|---|
| eGPU reliability and recovery | Predictable picture, sound and controls when you dock, return to the handheld and disconnect | Top priority. Safe Disconnect followed by physical unplug and replug has worked on several supervised test builds on one setup. Disconnect + Sleep is redesigned but has not yet worked on an installed build. Software reconnect is permanently out of scope |
| Command Center and modules | Common controls at hand, deeper settings easy to find | Live controls, approved artwork and Quick Access customization are in development builds and in an installed test build. Per-card checks on a device and real screenshots are still to come |
| Offline Readiness | Fewer surprises away from Wi-Fi | Implemented local guidance and refresh recovery; continue exact-game/view validation without turning confidence into a guarantee |
| Performance and power | Understandable manual power limits and optional Auto TDP | Implemented in development builds, including guards against settings a device cannot actually apply. Using a device's reported power range to limit Auto TDP at runtime is still to do, as is device acceptance |
| Automatic per-game graphics | Your preferred graphics settings follow you between handheld and TV without editing them twice | Early development. A safe foundation is built but not connected to anything: no game is supported and nothing changes your settings yet |
| Controller capabilities | Reliable built-in/external controls and supported customization | You can choose the button combination that opens Re-Gear. Gyro, rumble, lights and player order remain research or backlog; provider and device behavior is verified before any setting is exposed |
| Broader compatibility | More configurations earn supported capabilities | Ongoing evidence work; each device, connection type and capability needs its own validation |

### What moves a feature forward

Design, implementation, simulation, installation, hardware testing and release
are separate steps. A merged change does not mean the feature is installed on
your device, and one successful test does not certify every build or handheld.

Each [player guide](../player/README.md) states the benefit, current status and
remaining steps. Help through reviewed reports on
[Help Improve Re-Gear](../player/help-improve.md). No date or expanded hardware
support is promised by this roadmap.

## Technical details — for advanced users and contributors

The [engineering roadmap](../../ROADMAP.md) owns contracts and acceptance gates.
[Current state](current-state.md) lists the merged changes, installed builds and
supervised results behind each row, with PR links and dates.
[Issues](https://github.com/ronnierosal/Re-Gear/issues) track concrete work.

Row sources: eGPU — [lifecycle matrix](egpu-lifecycle.md) and
[power implementation](../../EGPU_POWER_NEXT.md); per-game graphics —
[staged plan](../../AUTOMATIC_GAME_OPTIMIZATION.md), which describes proposed
architecture, not enabled runtime optimization; performance —
[TDP control](../../TDP_CONTROL.md).
