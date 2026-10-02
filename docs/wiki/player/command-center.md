# Command Center & Quick Access

The **Command Center** is Re-Gear's controller-friendly panel for checking status
and reaching common controls without leaving a game.

## For players — no technical background needed

### Availability and limits

The full Command Center described here is implemented in current **development**
source. It is not part of a supported public release. The current production
profile deliberately shows only the eGPU tab, Safe Disconnect, and the fixed
brightness and volume sliders. It hides Quick Access customization, the other
tabs, and the right-side buttons.

The development interface has source and simulated-browser validation. Its
current complete controller flow has not been accepted on an installed build.
Use the labels in your build, and see [Current State](../technical/current-state.md)
before treating a development guide as installed behavior.

### Open and close Re-Gear

In a development build, choose **Open Re-Gear** in Decky's Quick Access menu.
The choices are **View / Back + Y**, **L3 + R3**, and **Disabled**. Press both
buttons in the selected shortcut together. Steam or a game may also react to
them because Re-Gear observes the shortcut without suppressing other input.

If controller shortcut input is unavailable, open Re-Gear from Steam's Quick
Access menu instead. Press **B** from the main panel to close Re-Gear.

### Get around

| Button | What it does |
|---|---|
| **LB** / **RB** | Change tabs |
| **D-pad** | Move between cards |
| **A** | Select the focused control |
| **B** | Go back, cancel, or close |

The development tabs are **Quick Access**, **Performance**, **eGPU**,
**Controllers**, **Offline Readiness**, and **Settings**.

### Quick Access

Quick Access starts with **FPS Target**, **Manual TDP**, **Auto TDP**,
**Display Target**, **eGPU Connection**, **Safe Disconnect**, and
**Controller Status**. The right side starts with **Mic Mute**, **Wi-Fi**,
**Performance Overlay**, and **Record**. Brightness and volume stay fixed on
the left.

Select a brightness or volume slider with **A**, then use **Up** / **Down**.
A card marked **Unavailable** cannot act and should explain why. **Unknown**
means Re-Gear could not confirm the value. Neither label is proof of a fault.

To change the development layout, see [Customize Re-Gear](customize.md).
Labelled picture placeholders are in the [Player Visual Guide](visual-guide.md).

### The other tabs

- **Performance** — frame-rate target, power controls, and Auto TDP.
  [Learn more](performance.md)
- **eGPU** — connection, display, and guarded disconnect actions.
  [Learn more](egpu.md)
- **Controllers** — observed controller information.
  [Learn more](controllers.md)
- **Offline Readiness** — preparation information for playing without internet.
  [Learn more](offline-readiness.md)
- **Settings** — **Diagnostics**, **Reset Layout**, **Tutorials**, and
  **About Re-Gear** in the current development source.

### If it does not work

- Shortcut does nothing: check **Open Re-Gear** is not **Disabled**, press both
  buttons together, and release both before retrying. Use Steam's Quick Access
  menu if the interface says controller input is unavailable.
- A card stays **Unavailable**: read its reason. Re-Gear is declining an action
  it cannot currently perform or verify.
- Your build shows only the eGPU tab: that is the intentional production profile,
  not a missing Quick Access setting.
- For other failures, follow [Troubleshooting](troubleshooting.md) and include
  the displayed Re-Gear version and revision.

## Technical details — for advanced users and contributors

The development tab list lives in
`src/quick-access/expanded-command-center/model.ts`. Control identities,
default Quick Access membership, and right-rail defaults live in
`control-registry.ts`; `layout-preferences.ts` projects saved layouts. The native
adapter mounts the controller shortcut and runtime data in `native.tsx`.

`ExpandedCommandCenter` receives a build policy. Under `policy="production"`,
it restricts `visibleTabs` to `egpu`, removes layout storage and Y-button editing,
and omits the right rail. The owning profile contract is
[Release Pipeline](../../RELEASE_PIPELINE.md#development-and-production-profiles).

| Evidence | What it establishes | Limit |
|---|---|---|
| Merged source on current `main` | Current development labels, tab structure, defaults, and production restriction | Source is not installed controller acceptance |
| [Last-mile runtime contract](../../design/ally-last-mile-runtime-contract.md#follow-up-to-the-03105-ui-test) | Simulated gesture, picker, focus-restoration, and responsive-browser checks | Explicitly not installed sound or controller acceptance |
| [Current State](../technical/current-state.md) | Current build and hardware evidence by revision | Does not promote the full development Command Center to a supported release |

The broader validation checklist is in
[Command Center validation](../../COMMAND_CENTER_VALIDATION.md).
