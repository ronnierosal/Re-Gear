# Move Command Center cards

In a development build, hold **Y** to move cards without activating them.

## For players — no technical background needed

This flow is implemented in development source and hidden in the production
profile. Read [Customize Re-Gear](../customize.md) before using these steps.

1. Open Re-Gear and go to the development tab you want to rearrange.
2. Move to a card, then hold **Y** for about half a second.
3. When the cards wiggle and the selected card shows **MOVE**, release **Y**.
4. Use the **D-pad** to move the card.
5. Press **A** to place it, or **B** to cancel and restore its earlier position.

On **Quick Access**, you can also change which buttons appear. See
[Change a Quick Access button](change-quick-access-button.md). On other tabs,
you can move existing cards but cannot change tab membership.

### If it does not work

- A picker opens: you tapped Y too quickly. Press **B**, then hold **Y** until
  the cards start moving.
- Nothing happens: confirm the build displays Y editing hints. The production
  profile does not include layout editing.
- The new position does not persist: if Re-Gear reported a save error, your
  previous saved layout remains unchanged.

## Technical details — for advanced users and contributors

The hold threshold is `CUSTOMIZE_HOLD_MS = 550` in
`src/quick-access/expanded-command-center/customization-input.ts`. Move targets
come from `moveTargetIndex` in `layout-customization.tsx`, and the draft is
committed only after **A**. Evidence limits are on
[Customize Re-Gear](../customize.md#technical-details--for-advanced-users-and-contributors).
