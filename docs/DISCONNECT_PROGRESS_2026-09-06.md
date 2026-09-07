# Disconnect resource-release progress, September 6, 2026

This public summary records the hardware driver's dated return-run evidence.
It does not replace deployment contracts or establish support for other devices.

## Recorded hardware run

- Configuration: ASUS ROG Ally X with GPD G1; installed Re-Gear **0.3.54 / e765fad4b928**.
- Cable remained attached; no new plugin, filter, or service was installed during the run.
- The player observed Steam on TV, then used Prepare to disconnect to return to the handheld and confirmed normal display, controls, and audio.
- After return, Steam retained external render descriptors and mappings with resident allocations; Mesa OpenGL was present.
- A privileged read-only follow-up also found Gamescope retained external descriptors and resident allocations; Vulkan/device-selection libraries were present.
- WirePlumber retained an audio-control descriptor although playback endpoints were closed.
- GPU engine activity was unknown. Retained allocations do not prove active rendering. The allocation follow-up inspected only these three processes; it was not a complete clearance scan. There was no live-phase capture during TV output.

**Result:** visible return succeeded; resource release did not. No physical-unplug clearance was granted.

## Changed experiment and review boundary

The next hypothesis is that internal GPU selection must cover Steam's OpenGL use as well as Vulkan. A local extension to the existing one-shot recoverable launch trial is under development. It is not installed or hardware validated. The supervised experiment keeps the cable attached and checks picture, controls, audio, and remaining ownership before deciding the next fix. Selection itself does not prove that clients cannot reopen the external GPU.

[Issue #51](https://github.com/ronnierosal/Re-Gear/issues/51) owns the experiment and its observed outcome. [Issue #52](https://github.com/ronnierosal/Re-Gear/issues/52) owns remaining audio release and recovery. Local recovery and preparation tests are prerequisites, not proof of a usable resource-release session. Software removal and eventual live-disconnect validation remain unfinished.

The return-button state mismatch was fixed locally after the observed confusing control flow; that local patch is not evidence of installed behavior. Sleep, shutdown, delayed detection, and startup controller symptoms remain separately tracked rather than assigned a speculative common cause.

Follow the existing [deployment rules](DEPLOYMENT_VALIDATION.md), [safety invariants](SAFETY_INVARIANTS.md), and [reviewed diagnostics](DIAGNOSTICS.md). Under the current tested policy, fully shut down before disconnecting the eGPU.
