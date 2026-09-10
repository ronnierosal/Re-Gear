# Game developer compatibility notes

Games do not need an Re-Gear-specific SDK. The most compatible behavior comes from
standard Linux graphics, process, and save practices that tolerate a different
GPU being selected on the next process launch.

## Graphics-device selection

- Enumerate Vulkan/graphics devices on every launch instead of permanently
  binding to the first device ever observed.
- Respect standard explicit device-selection mechanisms provided by the Linux
  graphics stack and compatibility runtime.
- Do not persist DRM node numbers, PCI addresses, device enumeration indexes, or
  connector suffixes as durable identity. They can change after boot, hot-plug,
  driver reload, or resume.
- Treat a changed or missing previously selected GPU as a recoverable launch
  condition. Re-enumerate and select a valid device or present a clear error.
- Release graphics, compute, and video contexts completely on process exit.
  Background launchers should not retain render-node ownership after the game
  closes.

Re-Gear does not migrate a live rendering context between GPUs. A game that was
started on the iGPU may remain there for its lifetime; a later launch can select
the eGPU after the system has verified the docked state.

## SteamOS, Gamescope, launchers, and Proton

- Test under the actual SteamOS Gamescope session, not only a desktop compositor.
- Keep launcher/child ownership understandable: the launcher should exit or
  clearly track the real game process, and all children should terminate on a
  requested game exit.
- Avoid helper processes that open a render device indefinitely when no game or
  UI needs it.
- Do not assume a Proton or native executable name uniquely identifies the Steam
  game. Steam AppID and process ancestry are separate evidence.
- Re-test device selection across Proton and game updates; a result for one
  runtime version is not universal.

## Save and shutdown behavior

- Implement a documented graceful shutdown path and finish pending save writes
  before the process exits.
- If save-on-exit is supported, make its completion observable and resilient to
  a bounded shutdown request.
- Prefer explicit, deterministic save APIs or in-game save points over simulated
  keyboard/controller input.
- Flush and close save files before releasing the final process. Steam Cloud
  synchronization is not proof that the current session was saved.
- If progress cannot be safely preserved during external shutdown, expose that
  limitation clearly so Re-Gear can require a manual-save warning.

## Compatibility reporting

Re-Gear tracks eGPU handoff and save/sleep behavior independently. A game is not
marked Verified from launch success, passive telemetry, or simulation. An
intentional reviewed hardware test must record the exact handheld/eGPU profile,
Re-Gear and SteamOS versions, Proton/runtime version where applicable, observed
rendering GPU, and the exact save/exit outcome.

See [Game compatibility catalog](GAME_COMPATIBILITY.md) for the current status
vocabulary and evidence gate.
