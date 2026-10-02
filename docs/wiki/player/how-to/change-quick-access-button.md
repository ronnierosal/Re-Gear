# Change a Quick Access button

In a development build, tap **Y** to replace a Quick Access button, fill an
empty slot, or leave a slot empty.

## For players — no technical background needed

This flow is implemented in development source and hidden in the production
profile. Read [Customize Re-Gear](../customize.md) before using these steps.

### Replace a button

1. Open Re-Gear and stay on **Quick Access**.
2. Move to the button you want to replace and tap **Y**.
3. In **Change _button name_**, optionally choose a filter such as **All**,
   **eGPU**, or **Display**.
4. Select the replacement with **A**.
5. Press **B** to return to Quick Access.

The chosen button should take the old button's place.

### Add a button

Move to a dimmed, dashed **Empty slot**, tap **Y**, and select a button from the
picker. The new button should fill that slot.

### Remove a button

Tap **Y** on the button, then select **Remove button**. The slot should become
empty. The feature remains available on its own tab.

### If it does not work

- Nothing happens when you tap **Y**: confirm that the build shows Y editing
  hints and that you are on **Quick Access**. Tapping Y on other tabs does
  nothing by design.
- A button is missing from the picker: only controls marked for Quick Access can
  be added.
- **Could not save this layout. Your saved layout is unchanged.**: the previous
  layout was kept. Retry once, then follow [Troubleshooting](../troubleshooting.md).

## Technical details — for advanced users and contributors

The picker is rendered by
`src/quick-access/expanded-command-center/shell.tsx`. Eligibility and grouping
come from `quickEligible`, `replace`, and `domain` in `control-registry.ts`.
Availability and evidence limits are on
[Customize Re-Gear](../customize.md#technical-details--for-advanced-users-and-contributors).
