# Reset Quick Access

Put Quick Access back to the way Re-Gear started, then customize it again from
there.

## For players — no technical background needed

This is in current development builds; see [Customize Re-Gear](../customize.md)
for availability and limits.

1. Open Re-Gear with your shortcut and use **LB** / **RB** to reach **Settings**.
2. Select **Reset Layout** (*Restore default card positions*).
3. Re-Gear asks: *Restore the default Quick Access buttons, right rail and tab
   order?* Select **Reset layout** to confirm, or press **B** to keep your
   layout.

This resets the layout only. It does not change any other Re-Gear setting.

### If it does not work

If you see **Could not save this layout. Your saved layout is unchanged.**, the
reset did not happen and your current layout is kept. Try again, then report it
through [troubleshooting](../troubleshooting.md) if it keeps happening.

## Technical details — for advanced users and contributors

The reset writes the normalized default layout through the same save path as
other layout edits (`commitLayout(normalizeLayout(null), 'reset-layout')` in
`shell.tsx`). Evidence and limits are on
[Customize Re-Gear](../customize.md#technical-details--for-advanced-users-and-contributors).
