# Steam handoff trial: resource findings

Installed Re-Gear 0.3.54 received a supervised idle TV-to-Portable trial.
Late G1 enumeration initially exceeded the readiness window, but docking
subsequently completed about three minutes after attachment. The player
confirmed TV display, audio and controller readiness before the trial, then
normal Ally display, audio and controls afterward. The cable stayed attached.

The new Steam process received both internal-GPU Vulkan selector variables.
The Gamescope argv selected the observed internal GPU and panel. Gamescope
environment remains unreadable from the unprivileged SSH account. All four
trial record/receipt/consumption files exist; retain them and the explicit
result hold. Do not replay this trial.

The installed privileged scanner still reports three G1 holders: Gamescope
and Steam render resources, plus WirePlumber audio control. The scan is complete,
storage count is zero, and disconnect readiness remains false. Before/after
captures are in ignored `out/054-trial-before.json` and `out/054-trial-after.json`.

Read-only Steam fdinfo exposed one G1 DRM client duplicated across four
descriptors, with 4,892 KiB resident VRAM and 4,112 KiB resident GTT at that
sample. These are allocated buffers, not just an empty descriptor. Do not sum
duplicated descriptors or the deprecated memory aliases. No engine counters
were exported for this client; that is unknown utilization, not proof of idle.
Steam mappings showed Mesa OpenGL/GLX libraries and no Vulkan library in that
capture. Delivering Vulkan settings therefore does not establish control of
every graphics path, nor does this observation alone identify the opener.

The parser follows the [kernel DRM fdinfo contract](https://docs.kernel.org/gpu/drm-usage-stats.html).
The bounded standalone probe `scripts/probe_egpu_allocations.py` reads the exact
profile-matched G1 nodes for Steam, Gamescope and WirePlumber. It takes two
samples, compares process/device identity, deduplicates DRM client descriptors,
reports resident/total memory and engine counter deltas, and separately observes
audio PCM states. It writes only redacted JSON to stdout, uses no device writes,
service commands or process signals, and never grants disconnect clearance.
Its scope is these three processes, not a complete system-wide release scan.

Gamescope descriptor details need root on this OS. Noninteractive sudo is not
available. A privileged probe must be run by the operator through SSH from
Windows, preserving the live Steam session. Do not switch to Desktop mode to
run it, because that would replace the session being investigated. Never ask
for the sudo password in chat. Keep the G1 attached during the capture.
