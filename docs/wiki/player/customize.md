# Customize Re-Gear

In development builds, you can choose the buttons in Quick Access and move
cards so your common controls are easier to reach.

## For players — no technical background needed

### Availability and limits

Customization is implemented in current merged **development** source. It is
hidden by the production profile and is not part of a supported public release.
The current tap-Y, hold-Y, picker, save, and reset behavior has source and
simulated-browser validation; the complete flow still needs acceptance on an
installed build with a controller.

Use these instructions only when your coordinated development build displays
the matching Y-button hints. The [Player Visual Guide](visual-guide.md) contains
labelled mock pictures that can later be replaced with device screenshots.

### The controls in one place

| Where | Input | What to expect |
|---|---|---|
| **Quick Access** button | Tap **Y** | Opens **Change _button name_** so you can choose a replacement |
| Empty Quick Access slot | Tap **Y** | Opens the same picker so you can add a button |
| Any development tab | Hold **Y** for about half a second | Cards wiggle and the selected card shows **MOVE** |
| Other tabs | Tap **Y** | Nothing; their card membership is fixed |

Step-by-step guides:

- [Change, add, or remove a Quick Access button](how-to/change-quick-access-button.md)
- [Move cards](how-to/rearrange-quick-access.md)
- [Reset the layout](how-to/reset-quick-access.md)

### What is saved

The development layout is saved on that Steam client. Another device keeps its
own layout. Removing a Quick Access button does not remove the feature from its
own tab.

If saving fails, Re-Gear says **Could not save this layout. Your saved layout is
unchanged.** Your prior saved layout remains in place. Try once more, then use
[Troubleshooting](troubleshooting.md) if the message returns.

## Technical details — for advanced users and contributors

`createCustomizeGestureRecognizer` in
`src/quick-access/expanded-command-center/customization-input.ts` separates a Y
tap from a 550 ms hold. `layout-customization.tsx` supplies move behavior, while
`shell.tsx` renders the picker and saves through `layout-preferences.ts` under
`regear.command-center-layout.v1`. `control-registry.ts` declares which controls
can be added, replaced, or reordered.

The native adapter supplies Y as the edit button only outside the production
profile. Production also omits layout storage, so this page must not be read as
production availability.

| Evidence | What it establishes | Limit |
|---|---|---|
| Current merged development source | Labels, 550 ms gesture split, picker, persistence, and reset path | Implemented source is not installed acceptance |
| [Last-mile runtime contract](../../design/ally-last-mile-runtime-contract.md#follow-up-to-the-03105-ui-test) | Focused tests and actual-source browser captures for the revised tap/hold flow | Explicitly source/simulated, not installed controller proof |
| [Release Pipeline](../../RELEASE_PIPELINE.md#development-and-production-profiles) | Production hides customization | No supported public release currently exposes this guide's flow |

The owning presentation contract is the
[UI design contract](../../UI_DESIGN_CONTRACT.md).
