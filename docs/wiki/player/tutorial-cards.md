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
**Safe Disconnect** once and read every status message. A shown control or a
**Pending**, **Unavailable** or **Refused** result is not permission to unplug.
Verify handheld picture, audio and controls return. Unplug only when Re-Gear
explicitly clears the physical unplug for your exact supervised setup; a
software result alone is not enough.
[Full disconnect guidance](egpu.md#safe-disconnect).

### Sleep and wake

Sleep with an eGPU is still being validated. The two choices have different
jobs:

- **Disconnect + Sleep** starts the guarded disconnect. Follow the messages,
  unplug only when Re-Gear asks, and expect sleep only after absence is verified.
- **Sleep — Keep eGPU Connected** opens a confirmation. **Sleep connected** uses
  normal sleep without running **Safe Disconnect**.

The controls can be **Ready**, **Pending**, **Unavailable** or **Refused** in the
current runtime state. If an action is unavailable or refused, stop and follow
the message. Do not force sleep or use software reconnect.
[Current limits](egpu.md#sleep-and-wake).

### If you get stuck

Stop repeating the action. Note your Re-Gear version, the message shown, what you
expected and what happened. Include which screen you used and whether a game was
running. Use **Troubleshoot** if available and review a support preview before
sharing it. [Get help](troubleshooting.md).

## Technical details — for advanced users and contributors

Wording reviewed against merged source `36cabc3` and the
[0.3.98 lifecycle record](../technical/egpu-lifecycle.md). The mounted control
contract also includes the separate **Shutdown** and **Safe Disconnect +
Shutdown** actions. A control's presence does not establish runtime readiness,
unplug clearance or hardware qualification. The UI primary owns card mounting,
the exact in-app copy and the complete button path. Update the Wiki contract and
the in-app tutorial together when those labels or semantics change.
