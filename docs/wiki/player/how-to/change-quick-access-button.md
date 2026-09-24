# Change a Quick Access button

Swap a Quick Access button you rarely use for one you want, add a button to an
empty slot, or leave a slot empty.

## For players — no technical background needed

This is in current development builds; see [Customize Re-Gear](../customize.md)
for availability and limits.

### Replace a button

1. Open Re-Gear with your shortcut. It opens on the **Quick Access** tab.
2. Move to the button you want to replace and tap **Y**. A **Change** window
   opens, named after that button.
3. Optionally pick a filter at the top, such as **All**, **eGPU** or **Display**,
   to narrow the list.
4. Select the button you want with **A**. It takes the old button's place.
5. Press **B** to finish.

### Add a button to an empty slot

Empty slots appear as dimmed boxes with a dashed border. Move to one, tap **Y**,
and choose a button as above.

### Remove a button

Tap **Y** on the button, then choose **Remove button**. The slot is left empty.
The feature itself is still available on its own tab.

### If it does not work

- Nothing happens when you tap **Y**: check you are on the **Quick Access** tab.
  On other tabs, tapping **Y** does nothing by design.
- The button you want is not in the list: only supported buttons can be added.
- **Could not save this layout. Your saved layout is unchanged.**: nothing was
  lost. Try again, then report it through [troubleshooting](../troubleshooting.md)
  with your Re-Gear version if it keeps happening.

## Technical details — for advanced users and contributors

The picker is rendered by the expanded Command Center shell
(`src/quick-access/expanded-command-center/shell.tsx`); eligibility comes from
`quickEligible` and `replace` in `control-registry.ts`. Evidence and limits are
on [Customize Re-Gear](../customize.md#technical-details--for-advanced-users-and-contributors).
