# Short tutorial cards

These short explanations are also the wording contract for the UI tutorial cards.
They link to the full guide rather than duplicating a manual inside the interface.

## For players — no technical background needed

### First connection

Follow the instructions for your installed build and test setup. Connect the
dock, then read Re-Gear's connection and display messages. Wait for the transition
to finish and check picture, audio and controls. A TV picture alone does not tell
you which graphics device a game uses. [More about connecting](egpu.md#first-connection).

### Safe disconnect

Follow the build's instructions about games and connected storage. Select
**Safely disconnect** once and read the result. Verify handheld picture, audio
and controls return. Physical unplugging needs separate clearance for your exact
supervised setup; a software result alone is not enough.
[Full disconnect guidance](egpu.md#safe-disconnect).

### Sleep and wake

Sleep with an eGPU is still being validated. **Disconnect eGPU and sleep** and
**Keep eGPU connected and sleep** are separate choices in the accepted design,
not a promise that your build supports them. If sleep is blocked, do not force it
or use software reconnect. [Current limits](egpu.md#sleep-and-wake).

### If you get stuck

Stop repeating the action. Note your Re-Gear version, the message shown, what you
expected and what happened. Include which screen you used and whether a game was
running. Use **Troubleshoot** if available and review a support preview before
sharing it. [Get help](troubleshooting.md).

## Technical details — for advanced users and contributors

Wording reviewed against merged source `9421c6f` and the
[0.3.98 lifecycle record](../technical/egpu-lifecycle.md). These cards do not grant
hardware authority or establish that their UI mount exists. The UI primary owns
card mounting, actual available labels and the complete button path. Reconcile
new mounted-build evidence before changing availability wording.
