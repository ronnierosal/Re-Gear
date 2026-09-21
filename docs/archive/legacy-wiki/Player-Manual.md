> **Archived September 14, 2026.** Historical source at `9421c6f`; superseded by the [canonical Wiki](https://github.com/ronnierosal/Re-Gear/tree/main/docs/wiki). Do not use this as current instructions.

# Re-Gear Player Manual

Learn what Re-Gear does, find your way around its controls, and get help when
something is unclear. Read from the beginning or jump to the part you need.
No terminal commands or technical background are required.

**About the pictures:** these are labelled mock illustrations, not screenshots.
They show the order of actions and the labels to look for, not exact screen
positions or current device readings. Real screenshots can replace them later;
the written steps remain usable on their own.

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
Read [Getting Started](Getting-Started.md) before installing anything. If you already
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

#### Walkthrough A — Open Re-Gear

If Re-Gear is already installed for your test:

1. Open Steam's **Quick Access** panel and open **Decky**.
2. Select **Re-Gear** from your installed plugins.
3. You should reach **Command Center**, the overview for status and quick
   controls. Look for **Modules** and **Troubleshoot**.

![Mock picture: three panels show Quick Access to Decky, selecting Re-Gear, and reaching Command Center.](https://raw.githubusercontent.com/wiki/ronnierosal/Re-Gear/assets/player-manual/mock-open-regear.png)

*Mock picture — not an actual screenshot. Follow the labels, not the illustrated
positions. If Re-Gear is missing from Decky, report your installed build rather
than installing an unrelated candidate.*

#### Walkthrough B — Find a module and return

1. From **Command Center**, select **Modules**.
2. You should see **eGPU**, **Auto TDP**, and **Controller**. For this example,
   select **Controller** to open its page.
3. Read the information and any availability message, then use **Back** to return
   to the module list. Opening the page does not apply a setting.

![Mock picture: select Modules, choose Controller from the module list, then read the page and use Back.](https://raw.githubusercontent.com/wiki/ronnierosal/Re-Gear/assets/player-manual/mock-find-module.png)

*Mock picture — not an actual screenshot. “Read the information” is an instruction
in this illustration, not a status message. If a page is unavailable, read its
explanation; that does not establish that your controller is broken.*

Select **Troubleshoot** from Command Center or Modules when you need diagnostic
details or a support report.

The **eGPU status** and **Controller status** entries open information about
those devices. Opening a status view does not apply a setting. **Back** returns
toward the previous view; reopening Re-Gear's Quick Access view starts at
Command Center in the documented development interface.

Controller navigation still needs checking on each installed build. If a named
control is absent, use [Get help](#7-get-help); you do not need to install another
build just to match this manual. **Open expanded demo**, if present, shows a
preview layout with sample information. Use the regular controls for actual status.

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

For more detail, see [Performance and Power](Performance-and-Power.md) and
[Command Center](Command-Center.md). Those guides also contain development and
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

Start with [Supported Hardware](Supported-Hardware.md) for recorded compatibility
limits. In an authorized test, read the displayed status and instructions for
that exact build before requesting a display change.

Some development display/disconnect paths restart the Steam session. Follow the
build's instructions about closing a game first; this manual does not promise
that an active game will stay running through a change.

For physical eGPU disconnection, follow
[Safety and eGPU Handling](Safety-and-eGPU-Handling.md). The documented guidance
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
for you. See [Offline Readiness](Offline-Readiness.md) for the labels and limits.

### 7. Get help

If something does not work, note what you expected, what happened, and your
Re-Gear version. Include whether a game was running and which screen you were
using. Do not repeat a risky failure just to collect a report.

#### Walkthrough C — Preview a support report

A **support report** contains selected Re-Gear status to help explain a problem.
**Redacted** means identifying details have been removed or replaced.

1. Select **Troubleshoot**. Find **Support bundle** and select
   **Preview redacted support bundle**.
2. The **Redacted support bundle preview** should open. Read the report, then
   select **Close preview**. You have not saved or sent a file by doing this.

![Mock picture: open Preview redacted support bundle, review the report in the preview, then select Close preview.](https://raw.githubusercontent.com/wiki/ronnierosal/Re-Gear/assets/player-manual/mock-support-preview.png)

*Mock picture — not an actual screenshot. Gray lines stand in for report text;
they are not a real diagnostic result.*

After reviewing, choose **Copy reviewed JSON** to copy the report, or **Save
reviewed bundle to Downloads** to save it locally. JSON is the report's text
format; you do not need to edit it. Save approval lasts five minutes from preview
creation and can be used once. If it expires, create and review a new preview.
See [Diagnostics and Privacy](Diagnostics-and-Privacy.md) for the complete save flow
and help with preview, copy or save failures.

- [Diagnostics and Privacy](Diagnostics-and-Privacy.md) explains **Troubleshoot**,
  **Preview redacted support bundle**, and how to review, copy or save a report.
- [Help Improve Re-Gear](Help-Improve-Re-Gear.md) explains where to report a problem
  and what information helps.
- [Troubleshooting](Troubleshooting.md) links symptoms and existing investigations.

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
or hardware trial. The mock illustrations were generated with the built-in image
tool for this manual; [asset notes and replacement instructions](https://github.com/ronnierosal/Re-Gear/blob/main/wiki/assets/player-manual/README.md)
retain the prompts and filenames. They are not a product design replacement or
installed-validation evidence. Future screenshots should identify the installed
build and illustrate these steps without becoming a prerequisite for reading them.
