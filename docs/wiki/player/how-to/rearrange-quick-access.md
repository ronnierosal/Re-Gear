# Move Quick Access buttons

Put the actions you use most where they are easiest to reach.

## For players — no technical background needed

This is in current development builds; see [Customize Re-Gear](../customize.md)
for availability and limits.

1. Open Re-Gear with your shortcut and go to the tab you want to rearrange.
2. Move to the card you want to move, then **hold Y** for about half a second.
   The cards start to wiggle and the one you picked shows **MOVE**.
3. Use the **D-pad** to move it.
4. Press **A** to place it, or **B** to cancel and put it back.

On the **Quick Access** tab you can also change which buttons appear; see
[Change a Quick Access button](change-quick-access-button.md). On other tabs you
can only reorder the cards that are already there.

### If it does not work

- It changes a button instead of moving it: you tapped **Y** rather than holding
  it. Press **B** to back out and hold **Y** a little longer.
- Your layout did not stick: if you saw **Could not save this layout**, your
  previous layout is unchanged. Try again.

## Technical details — for advanced users and contributors

The hold threshold is `CUSTOMIZE_HOLD_MS = 550` in
`src/quick-access/expanded-command-center/customization-input.ts`; move targets
come from `moveTargetIndex` in `layout-customization.tsx`. Evidence and limits
are on [Customize Re-Gear](../customize.md#technical-details--for-advanced-users-and-contributors).
