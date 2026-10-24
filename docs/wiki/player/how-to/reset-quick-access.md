# Reset the Command Center layout

In a development build, **Reset Layout** restores the original Quick Access
buttons, right-side buttons, and card order.

## For players — no technical background needed

This flow is implemented in development source and hidden in the production
profile. Read [Customize Re-Gear](../customize.md) before using these steps.

1. Open Re-Gear and use **LB** / **RB** to reach **Settings**.
2. Select **Reset Layout**. Its description is **Restore default card positions**.
3. Re-Gear asks: *Restore the default Quick Access buttons, right rail and tab
   order?*
4. Select **Reset layout** to confirm, or press **B** to keep your current layout.

After confirmation, the default layout should reappear. This does not reset
unrelated Re-Gear settings.

### If it does not work

If Re-Gear says **Could not save this layout. Your saved layout is unchanged.**,
the reset did not replace your saved layout. Retry once, then follow
[Troubleshooting](../troubleshooting.md) if the message returns.

## Technical details — for advanced users and contributors

The reset calls `commitLayout(normalizeLayout(null), 'reset-layout')` in
`src/quick-access/expanded-command-center/shell.tsx`, using the same guarded save
path as other edits. Evidence limits are on
[Customize Re-Gear](../customize.md#technical-details--for-advanced-users-and-contributors).
