# Customize Re-Gear

You can choose which buttons appear in Quick Access and move cards around, so
the actions you use most are easiest to reach. Everything is done from the
controller.

## For players — no technical background needed

### Availability and limits

Quick Access customization is in current development builds, including the
0.3.129 test build installed on the maintainer's test handheld. No
customization-specific check on that handheld has been recorded yet, and there
is no supported public release; see [Getting Started](getting-started.md).
Screenshots will be added once the interface is validated on a device.

### The controls in one place

| On the **Quick Access** tab | What happens |
|---|---|
| Tap **Y** on a button | Opens **Customize Quick Access**, where you choose a different button |
| Tap **Y** on an empty slot | Adds a button there |
| Hold **Y** | Starts moving cards: the cards wiggle and the selected one shows **MOVE** |

On the other tabs, holding **Y** moves cards; tapping **Y** does nothing. The
buttons available on those tabs do not change.

Step-by-step guides:

- [Change a Quick Access button](how-to/change-quick-access-button.md)
- [Move Quick Access buttons](how-to/rearrange-quick-access.md)
- [Reset Quick Access](how-to/reset-quick-access.md)

### Things to know

- Your layout is saved on this Steam client. Another device keeps its own.
- If saving fails you will see **Could not save this layout. Your saved layout
  is unchanged.** Nothing is lost; try again.
- Only buttons marked as supported can be added. A button that cannot act right
  now still shows, greyed out, with the reason.
- Removing a button from Quick Access does not remove the feature. It is still
  on its own tab.

## Technical details — for advanced users and contributors

The tap/hold split is `createCustomizeGestureRecognizer` in
`src/quick-access/expanded-command-center/customization-input.ts`
(`CUSTOMIZE_HOLD_MS = 550`), mounted by the expanded Command Center shell. The
native adapter binds the edit button to Y and persists layouts under
`regear.command-center-layout.v1`. Which controls can be added, moved or replaced
is declared per control in `control-registry.ts` (`quickEligible`, `reorder`,
`replace`).

| Evidence | What it establishes | Remaining limit |
|---|---|---|
| Merged source at `5ed1e3d`, 2026-09-24 | Labels, gestures, persistence and reset flow above | Source review is not native acceptance |
| Installed 0.3.129 test build (`e8ad848`) | The feature is present in an installed build | No customization-specific result recorded for it |

The earlier customization test build (PR329, 0.3.107) was closed without
merging; this feature reached main separately. Owning UI contract:
[UI design contract](../../UI_DESIGN_CONTRACT.md). Evidence summary:
[current state](../technical/current-state.md).
