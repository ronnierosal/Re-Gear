# eGPU and docking

An eGPU is an external graphics device. Re-Gear helps explain whether it is
detected, whether your display is ready, and what action is available next.

## For players — no technical background needed

### What is available

Re-Gear is still a development project. There is no supported public release.
Everything below describes development build **0.3.154**, which has been built
and passed its software checks but has **not yet been installed or tested on a
handheld**. Its exact status is in the
[0.3.154 lifecycle record](../technical/egpu-lifecycle.md#development-build-03154-built-not-yet-hardware-tested).

The ordinary **Safe Disconnect** journey has already worked on the maintainer's
single recorded test setup: return to the handheld, disconnect, physically unplug,
plug back in, and get the TV picture back. That earlier result is the baseline
0.3.154 must preserve. It does not prove the journey is repeatable, or that it
works on other handhelds, docks or graphics cards. It is not general permission
to unplug a powered eGPU. Outside a supervised test, shut down before unplugging.

### Where the controls are

Open Re-Gear and use **LB** / **RB** to reach the **eGPU** tab. Actions appear
when Re-Gear can confirm they are safe to offer:

| Action | What it does |
|---|---|
| **eGPU Status** | Read-only status. Nothing changes when you open it |
| **Switch to TV** / **Switch to Handheld** | Moves the picture between the TV and the handheld screen. The button shows whichever switch makes sense right now |
| **Safe Disconnect** | Returns to the handheld and stops using the eGPU, then tells you to unplug it |
| **Disconnect + Sleep** | Safe Disconnect, then waits for you to unplug before the handheld sleeps |
| **Safe Disconnect + Shutdown** | Safe Disconnect, then shuts the handheld down |

A greyed-out or **Unavailable** action means Re-Gear cannot confirm it is safe
to act. That is not a fault on its own.

### First connection

1. Plug in the eGPU while in Gaming Mode. Keep the cable connected while a
   connection is in progress.
2. **New devices may ask for permission.** The first time a device is plugged
   in, Re-Gear can show an authorization popup:
   - **Allow once** — trust this device for the current connection only. You
     are asked again next time.
   - **Always trust** — remember this device. It only appears when your build
     supports remembering devices.
   - **Not now** — do nothing; the device stays blocked.

   Only approve hardware you own or trust. "Approved" appears only after
   Re-Gear reads back that approval took effect. Approval alone does not mean
   the GPU, TV or audio is ready yet.
3. **Watch the progress popup.** It shows each step in turn — the USB4 link, the
   GPU, the external display, audio, and Gaming Mode readiness. If a step is
   blocked, it shows **Needs attention** with the reason.
4. When everything is ready, Re-Gear can switch to the TV automatically if you
   turned that on, with a small number of retries. Otherwise use **Switch to TV**.
   Then check the picture, audio and controls. If the display does not return,
   stop and report the message and build version.

A detected device, an active TV picture and the GPU drawing a game are different
facts. Do not assume a game uses the eGPU just because the TV shows a picture.
An **Unknown** or **Unavailable** result means Re-Gear cannot confirm that item
right now; it does not automatically mean the device is broken.

### Safe disconnect

1. Close your game and any dock-connected storage first.
2. Select **Safe Disconnect** once and confirm. Re-Gear moves the picture back to
   the handheld, releases the eGPU, and switches the dock connection off.
3. Keep the cable connected until Re-Gear tells you to **unplug the eGPU**. Then
   unplug it. If Gaming Mode restarts during the disconnect, the result comes
   back on its own — it is not a reason to press again.
4. Check that the handheld picture, audio and controls work.

After Safe Disconnect, a remembered eGPU is **not** turned back on while the cable
is still plugged in. Re-Gear holds it off until it sees the cable has been
removed, so the dock cannot quietly reconnect itself.

If the operation is refused or unfinished, keep the evidence and use
[troubleshooting](troubleshooting.md). Do not repeatedly retry or clear its
state to make the status look successful.

**Getting the TV back.** Plugging the eGPU back in is how you reconnect. The
normal connection and automatic TV switch then run again. There is no
"reconnect" button: software reconnection was removed after an incident on the
test setup, and Re-Gear refuses it.

### Sleep and wake

- **Disconnect + Sleep** returns to the handheld, runs Safe Disconnect, then
  tells you to unplug the eGPU. Unplug **only after that prompt appears**. Sleep
  starts only once Re-Gear confirms the cable is gone, and only if that happens
  before the request expires. Otherwise the handheld stays awake.
- **Sleeping with the eGPU still connected is not offered.** Disconnect first,
  or shut down.

Disconnect + Sleep has not yet been tested on a handheld with 0.3.154. If sleep
is blocked, do not force it or dismiss the blocker as harmless. Do not assume
charging continues or wake is healthy without checking.

### Shutdown

**Safe Disconnect + Shutdown** returns to the handheld, runs the guarded
disconnect, then shuts down. Re-Gear does not switch off USB-C charging, so the
dock is expected to keep charging the handheld. Charging and the full one-button
shutdown have not yet been tested on a handheld with 0.3.154.

## Technical details — for advanced users and contributors

The [lifecycle guide](../technical/egpu-lifecycle.md) separates what is
implemented in source, what is in the 0.3.154 package, what was previously
observed on hardware, and what still awaits 0.3.154 hardware validation. It also
records the exact archive, hash and exclusions. [Current state](../technical/current-state.md)
lists earlier installed trials. [Scripts and CI](../technical/scripts-and-ci.md)
explains why read-only readiness probes and CI are not hardware tests. The
[safety invariants](../../SAFETY_INVARIANTS.md) remain release-gate authority.
