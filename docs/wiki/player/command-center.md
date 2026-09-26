# Command Center & Quick Access

The **Command Center** is Re-Gear's full-screen control panel. It opens over your
game so you can check status and act without leaving it.

Quick Access is for **actions now**. Deeper configuration lives on the other tabs.

---

## For players — no technical background needed

### Availability and limits

This page describes current development builds, reviewed against merged source
on September 24. The approved "V3" card artwork and live eGPU controls were in
the 0.3.129 test build installed on the maintainer's test handheld. That confirms
they are present in an installed build, not that every card has been checked on
a device. There is no supported public release; see
[Getting Started](getting-started.md). The [Player Visual Guide](visual-guide.md)
shows labelled mockups until real screenshots are added.

### Open Re-Gear

Open Re-Gear from your controller with the shortcut you choose in Decky's Quick
Access menu under **Open Re-Gear**: **View / Back + Y** (the default), **L3 + R3**,
or **Disabled**. Press both buttons together. Steam or your game may also react
to the same buttons, because Re-Gear only listens for them.

### Get around

| Button | What it does |
|---|---|
| **LB** / **RB** | Change tabs |
| **D-pad** | Move between cards |
| **A** | Select |
| **B** | Go back or close |

The tabs are **Quick Access**, **Performance**, **eGPU**, **Controllers**,
**Offline Readiness** and **Settings**.

### Quick Access

Quick Access starts with **FPS Target**, **Manual TDP**, **Auto TDP**,
**Display Target**, **eGPU Connection**, **Safe Disconnect** and
**Controller Status**. A column on the right holds quick toggles, starting with
**Mic Mute**, **Wi-Fi**, **Performance Overlay** and **Record**. To adjust a
brightness or volume slider, select it with **A**, then use **Up** / **Down**.

Every card shows current status. A card that cannot act right now keeps its
place, shows why, and does nothing when selected. **Unknown** means Re-Gear could
not confirm a value; it never guesses.

You can change, add, remove and move these buttons: see
[Customize Re-Gear](customize.md).

### The other tabs

- **Performance** — frame-rate target, power limit and Auto TDP.
  [Learn more](performance.md)
- **eGPU** — connection, display and disconnect actions.
  [Learn more](egpu.md)
- **Controllers** — what Re-Gear can see about your controllers.
  [Learn more](controllers.md)
- **Offline Readiness** — whether a game looks ready to play without internet.
  [Learn more](offline-readiness.md)
- **Settings** — **Diagnostics**, **Reset Layout**, **Tutorials** (short guides
  for connecting, disconnecting and getting help) and **About** (version and
  credits).

### If it does not work

- The shortcut does nothing: check **Open Re-Gear** is not set to **Disabled**,
  press both buttons at the same moment, and release both before trying again.
  If the setting says controller input is unavailable, the shortcut cannot work
  in this build; report it through [troubleshooting](troubleshooting.md) with
  your Re-Gear version.
- A card stays **Unavailable**: read its reason. It is Re-Gear declining an action
  it cannot confirm is safe, not necessarily a fault.
- Anything else: [troubleshooting](troubleshooting.md).

---

**Next:** [Customize Re-Gear →](customize.md)

## Technical details — for advanced users and contributors

Tabs, default Quick Access controls and right-rail defaults are declared in
`src/quick-access/expanded-command-center/model.ts` and `control-registry.ts`.
The production Command Center routes eGPU actions directly
([PR #353](https://github.com/ronnierosal/Re-Gear/pull/353)) and opens in the
in-game focused overlay ([PR #354](https://github.com/ronnierosal/Re-Gear/pull/354)).
The approved V3 artwork is wired across the registry controls
([PR #378](https://github.com/ronnierosal/Re-Gear/pull/378)); **Render GPU** and
plain **Shutdown** keep the earlier artwork because no approved V3 asset exists
for them.

| Evidence | What it establishes | Remaining limit |
|---|---|---|
| Merged source at `5ed1e3d`, 2026-09-24 | Tabs, labels, defaults, navigation and routing above | Source review is not native or hardware acceptance |
| Installed 0.3.129 test build (`e8ad848`), 2026-09-22 | V3 artwork and production eGPU controls present in an installed build; the eGPU actions exercised in that trial are listed in [current state](../technical/current-state.md) | Later layout and text polish is not in that build; per-card native checks are not recorded |

The owning evidence record is the
[Command Center validation](../../COMMAND_CENTER_VALIDATION.md).
