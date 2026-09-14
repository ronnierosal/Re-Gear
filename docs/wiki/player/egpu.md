# eGPU and docking

An eGPU is an external graphics device. Re-Gear helps explain whether it is
detected, whether your display is ready, and what action is available next.

## For players — no technical background needed

### What is available

One supervised v0.3.98 trial successfully used **Safely disconnect**, returned to
the handheld, physically unplugged and replugged, then restored TV picture, audio
and controls. That result applies to the exact configuration in the
[evidence table](../technical/egpu-lifecycle.md). Repeatability, other hardware
and sleep were not established. It is not general permission to unplug a powered
eGPU. Outside that supervised configuration, shut down before unplugging.

### First connection

1. Follow the connection instructions for your installed build and approved test
   setup. Keep the cable connected while a transition is in progress.
2. Open Re-Gear and read the connection and display messages.
3. Wait for the transition to finish, then check the picture, audio and controls.
   If the display does not return, stop and report the message and build version.

A detected device, an active TV picture and the GPU drawing a game are different
facts. Do not assume a game uses the eGPU just because the TV shows a picture.
An **Unknown** or **Unavailable** result means Re-Gear cannot establish or offer
that item; it does not automatically mean the device is broken.

### Safe disconnect

1. Follow your exact build's instructions about closing games and dock-connected
   storage before starting.
2. If **Safely disconnect** is offered in your supervised build, select it once.
3. Read the result and verify the handheld picture, audio and controls return.
   A session restart or closed result window is not a reason to press again.
4. Physical unplugging needs separate clearance for the exact supervised setup.
   A button name, blank screen or software-removed message alone is insufficient.

If the operation is refused or unfinished, keep the evidence and use
[troubleshooting](troubleshooting.md). Do not repeatedly retry or clear its state
to make the status look successful.

### Sleep and wake

The accepted design offers **Disconnect eGPU and sleep** and **Keep eGPU connected
and sleep**. These are distinct choices. The automated combined journey has not
been hardware-qualified by the 0.3.98 checkpoint; manual sleep after its disconnect
was blocked. Do not force sleep, dismiss a blocker as harmless, or assume healthy
wake or charging. Follow the current build's supervised instructions.

Software reconnect after intentional disconnection is out of scope. Do not use
a developer reconnect command to turn a still-cabled dock back on. Physical
reconnection and normal attachment recovery are separate from software reconnect.

## Technical details — for advanced users and contributors

The [lifecycle acceptance matrix](../technical/egpu-lifecycle.md) records exact
entry points, required evidence, the 0.3.98 artifact/configuration, failure paths,
owners and remaining gaps. [Scripts and CI](../technical/scripts-and-ci.md)
explains why read-only readiness probes are not execution or button-path tests.
The [safety invariants](../../SAFETY_INVARIANTS.md) remain release-gate authority.
