# Mid-game docking research

## Question

Can an existing game continue rendering on the Ally iGPU while its current
Gamescope session is presented on the G1-connected TV, without restarting
Gamescope or migrating the workload?

This is an experiment, not committed product behavior.

## Read-only discovery phase

Capture, without changing state:

- Gamescope version, PID, full arguments, active connector, and render device
- `gamescopectl` version, advertised features, and available commands
- DRM connector state, EDID readiness, and card-to-connector ownership
- Steam game scope, game PID, and exact DRM nodes opened by the workload
- GPU utilization evidence tied to exact devices
- USB4/PCIe AER and recovery baseline

## Required proof

A successful future experiment must show:

- unchanged Gamescope PID
- unchanged game scope and process
- render GPU remains the iGPU
- TV becomes the actual active presentation target
- stable input and visible output
- no GPU device loss or materially worse recovery record
- a verified return to the internal panel

If any condition is unknown, the result is inconclusive. If the platform lacks a
runtime connector-selection mechanism, Re-Gear should report that docking will be
available after the game exits rather than restarting the session.

## Prohibited assumptions

- Hotplug detection implies live output switching.
- Connector `connected` implies active presentation.
- Suspending a game makes its graphics device migratable.
- A Gamescope restart preserves a running game.
