# eGPU and docking

An eGPU is an external graphics device. Re-Gear helps explain whether it is
detected, whether your display is ready, and what action is available next.

## For players — no technical background needed

### What is available

Re-Gear is still a development project. There is no supported public release,
and everything below was observed on the maintainer's single recorded test setup
in supervised sessions.

On that setup, the ordinary disconnect journey has now worked on three test
builds between September 13 and September 22: return to the handheld, select
**Safe Disconnect**, physically unplug the dock, plug it back in, and get the TV
picture back. That is encouraging, but it does not prove the journey is
repeatable every time, or that it works on other handhelds, docks or graphics
cards. The disconnect-and-sleep journey has **not** worked on an installed build
yet. See [current evidence](../technical/current-state.md) for exact builds and
dates.

It is not general permission to unplug a powered eGPU. Outside that supervised
configuration, shut down before unplugging.

### Where the controls are

Open Re-Gear with your shortcut, then use **LB** / **RB** to reach the **eGPU**
tab. Current development builds show these actions when they are available:

| Action | What it does |
|---|---|
| **Switch to Handheld** | Moves the picture back to the handheld screen |
| **Safe Disconnect** | Stops using the eGPU in software. On its own it is not permission to unplug |
| **Disconnect + Sleep** | Safe Disconnect, then waits for you to unplug before the handheld sleeps |
| **Shutdown** | Shuts the handheld down fully, so you can unplug with the power off. From the TV it first asks you to return to the handheld |
| **eGPU Status** | Read-only status; nothing changes when you open it |

A greyed-out or **Unavailable** action is Re-Gear refusing to act because it
cannot confirm it is safe. That is not a fault on its own.

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

1. Follow your build's instructions about closing games and dock-connected
   storage before starting.
2. Select **Safe Disconnect** once. Re-Gear asks you to confirm; the TV turns off
   and Gaming Mode may restart.
3. Keep the cable connected until the result is shown, then check that the
   handheld picture, audio and controls work. A restart or a closed result
   window is not a reason to press again.
4. Physical unplugging needs separate clearance for the exact supervised setup.
   A button name, blank screen or software-removed message alone is not enough.

If the operation is refused or unfinished, keep the evidence and use
[troubleshooting](troubleshooting.md). Do not repeatedly retry or clear its state
to make the status look successful.

**Getting the TV back.** Plugging the dock back in is how you reconnect. There is
no "reconnect" button: software reconnection was removed after an incident on
the test setup and Re-Gear now refuses it. If a message says the eGPU is
**blocked by an unfinished disconnect**, unplug the eGPU as it asks; do not work
around it.

### Sleep and wake

There are two sleep choices, and they behave very differently:

- **Sleep connected** keeps the eGPU attached and asks for normal sleep. It does
  not disconnect anything. Healthy wake with the eGPU attached has not yet been
  confirmed.
- **Disconnect + Sleep** returns to the handheld, runs Safe Disconnect, then shows
  an urgent prompt. Unplug **only after that prompt appears**; sleep starts only
  once Re-Gear sees the cable is gone. This replaced an earlier design that tried
  to sleep before you unplugged. It has not yet completed successfully on an
  installed build and is being fixed in supervised testing.

If sleep is blocked, do not force it, dismiss the blocker as harmless or use a
developer reconnect command. Do not assume charging continues or wake is healthy
without checking.

## Technical details — for advanced users and contributors

The [lifecycle acceptance matrix](../technical/egpu-lifecycle.md) records exact
entry points, required evidence, the 0.3.98 artifact/configuration, failure paths,
owners and remaining gaps. [Current state](../technical/current-state.md) lists
the later installed trials with their builds, dates and limits.
[Scripts and CI](../technical/scripts-and-ci.md) explains why read-only readiness
probes are not execution or button-path tests. The
[safety invariants](../../SAFETY_INVARIANTS.md) remain release-gate authority.

Merged source changes behind this page, none of which is a hardware result by
itself:

- Software reconnect is removed from the interface and refused at the backend
  RPC boundary ([PR #335](https://github.com/ronnierosal/Re-Gear/pull/335)).
- Disconnect-before-sleep was withdrawn
  ([PR #344](https://github.com/ronnierosal/Re-Gear/pull/344),
  [PR #345](https://github.com/ronnierosal/Re-Gear/pull/345)) and replaced by
  sleep gated on verified physical absence
  ([PR #367](https://github.com/ronnierosal/Re-Gear/pull/367)). A failure before
  software-down now retires only its own unsubmitted sleep intent
  ([PR #383](https://github.com/ronnierosal/Re-Gear/pull/383)).
- **Switch to TV** is offered again after a verified successful return to the
  handheld; uncertain or failed returns stay blocked
  ([PR #366](https://github.com/ronnierosal/Re-Gear/pull/366)). The mounted UI
  path for this still needs supervised validation.
- Safe Disconnect status now carries read-only eGPU cooling evidence
  ([PR #350](https://github.com/ronnierosal/Re-Gear/pull/350)); it does not
  change when a disconnect is admitted.
- The production Command Center wires these actions directly
  ([PR #353](https://github.com/ronnierosal/Re-Gear/pull/353)).

**Safe Disconnect + Shutdown** exists in source, but its own confirmation states
that shutdown is not yet hardware-verified and is not permission to unplug.
