# Re-Gear Player Manual

Learn what Re-Gear does, find your way around its controls, and get help when
something is unclear. Read from the beginning or jump to the part you need.
No terminal commands or technical background are required.

## For players — no technical background needed

1. [Before you begin](#1-before-you-begin)
2. [Find your way around](#2-find-your-way-around)
3. [Understand the numbers and controls](#3-understand-the-numbers-and-controls)
4. [Read the message as well as the status](#4-read-the-message-as-well-as-the-status)
5. [Use a dock or external graphics device](#5-use-a-dock-or-external-graphics-device)
6. [Prepare for playing without internet](#6-prepare-for-playing-without-internet)
7. [Get help](#7-get-help)

### 1. Before you begin

Re-Gear is a companion for handheld gaming on SteamOS. It brings together
information about your screen, graphics, controllers and game readiness, with
controls for supported features.

Re-Gear is still in development. This manual describes controls present in the
development source; your installed version may look different or offer fewer
features. A control appearing on screen does not mean every device supports it.
Read [Getting Started](Getting-Started) before installing anything. If you already
have a build for a coordinated test, follow the instructions for that build.

**A few useful words:**

| Word | What it means |
|---|---|
| Decky | The plugin system that makes Re-Gear available inside Steam's interface |
| Quick Access | The side panel you open while using Steam |
| Module | A section of Re-Gear for a particular feature |
| Dock | A device that connects your handheld to accessories such as a display |
| eGPU | An external graphics device; connecting one does not automatically mean a game is using it |

### 2. Find your way around

If Re-Gear is already installed for your test:

1. Open Steam's **Quick Access** panel, open Decky, and select **Re-Gear**.
2. Start with **Command Center**, the overview for status and quick controls.
3. Select **Modules** for the **eGPU**, **Auto TDP**, or **Controller** pages.
4. Select **Troubleshoot** for diagnostic details or a support report.

The **eGPU status** and **Controller status** entries open information about
those devices. Opening a status view does not apply a setting. **Back** returns
toward the previous view; reopening Re-Gear's Quick Access view starts at
Command Center in the documented development interface.

Controller navigation still needs checking on each installed build. If a named
control is absent, use [Get help](#7-get-help); you do not need to install another
build just to match this manual. **Open expanded demo**, if present, shows a
preview layout with sample information. Use the regular controls for actual status.

<!-- Future screenshot: installed Command Center with Modules and Troubleshoot
identified. Record build, capture date and native validation; remove private
information. Keep all steps understandable without the image. -->

### 3. Understand the numbers and controls

| Control | What it is for | What to expect |
|---|---|---|
| FPS target | A target for how many picture frames appear each second | Currently unavailable without a verified frame-rate control source; separate from Auto TDP's target |
| TDP limit | A limit on the handheld's processor power, expressed in watts | **Choose limit** opens supported choices and **Apply limit**. The configured limit is not a measurement of current power use |
| Auto TDP | Adjusts processor power within a chosen range toward a frame-rate target | **Configure** opens settings when it is not running; **Stop** stops automatic adjustments when it is running. It cannot guarantee the target frame rate |
| Display target | Requests a change of display through Re-Gear's available display controls | **Choose target** opens choices; opening them does not switch the display. Read the explanation and confirmation before applying a change |
| Safe Disconnect | Opens the available disconnect workflow | Follow its current explanation. A software-disconnect result is not permission to pull a powered eGPU cable |

You do not have to change settings simply because they are present. For power
controls, **Stop** keeps the current power limit; **Restore** returns to saved
settings. Applying a manual power limit stops Auto TDP. Saving a preference does
not start Auto TDP.

For more detail, see [Performance and Power](Performance-and-Power) and
[Command Center](Command-Center). Those guides also contain development and
validation information.

### 4. Read the message as well as the status

**Unknown** or **Unavailable** means Re-Gear cannot currently establish or offer
that information or action. It does not automatically mean a device is broken
or disconnected. An unavailable tile stays in its usual position; selecting it
shows an explanation below the controls.

Your screen and the graphics device drawing the game are different things.
A picture on an external screen does not by itself prove that an eGPU is
rendering the game. Report what you see if status and behavior disagree.

### 5. Use a dock or external graphics device

Start with [Supported Hardware](Supported-Hardware) for recorded compatibility
limits. In an authorized test, read the displayed status and instructions for
that exact build before requesting a display change.

Some development display/disconnect paths restart the Steam session. Follow the
build's instructions about closing a game first; this manual does not promise
that an active game will stay running through a change.

For physical eGPU disconnection, follow
[Safety and eGPU Handling](Safety-and-eGPU-Handling). The documented guidance
requires complete shutdown before unplugging. A blank screen, a removed-device
message or the words **Safe Disconnect** on a control are not proof that a powered
cable can be removed safely.

### 6. Prepare for playing without internet

Where **Offline Readiness** is available, check the game you plan to play while
you still have internet access. Read the reason beside its result and resolve
reported updates or cloud-save conflicts before leaving.

A readiness result is a useful check, not a guarantee. **Likely offline-ready**
is not the same as a successful offline launch. **Tested offline** records a
player's reported test for a matching game context; Re-Gear did not run that test
for you. See [Offline Readiness](Offline-Readiness) for the labels and limits.

### 7. Get help

If something does not work, note what you expected, what happened, and your
Re-Gear version. Include whether a game was running and which screen you were
using. Do not repeat a risky failure just to collect a report.

- [Diagnostics and Privacy](Diagnostics-and-Privacy) explains **Troubleshoot**,
  **Preview redacted support bundle**, and how to review, copy or save a report.
- [Help Improve Re-Gear](Help-Improve-Re-Gear) explains where to report a problem
  and what information helps.
- [Troubleshooting](Troubleshooting) links symptoms and existing investigations.

A saved support report stays local until you choose to share it. If the support
controls are missing, you can still report the symptom and installed version.

## Technical details — for advanced users and contributors

Source reviewed **2026-09-13**, against merged revision
[`ab87e2e`](https://github.com/ronnierosal/Re-Gear/commit/ab87e2e0f6b7beb462cacdc7f83e2f5d280844db).
Control labels and routing come from
[the main interface](https://github.com/ronnierosal/Re-Gear/blob/ab87e2e0f6b7beb462cacdc7f83e2f5d280844db/src/index.tsx)
and [Quick Access](https://github.com/ronnierosal/Re-Gear/tree/ab87e2e0f6b7beb462cacdc7f83e2f5d280844db/src/quick-access).
[UI validation](https://github.com/ronnierosal/Re-Gear/blob/main/docs/COMMAND_CENTER_VALIDATION.md)
and the [evidence index](https://github.com/ronnierosal/Re-Gear/blob/main/docs/INDEX.md)
own technical details and validation limits. This review performed no installation
or hardware trial. Future screenshots should identify the installed build and
illustrate these steps without becoming a prerequisite for reading them.
