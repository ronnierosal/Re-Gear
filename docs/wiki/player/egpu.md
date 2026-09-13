# eGPU & Docking

Re-Gear's eGPU tools are intended to make moving between handheld and docked play feel more like using a console.

> ### 🖼️ UI MOCKUP — eGPU menu
> **TEMPORARY IMAGE PLACEHOLDER**
>
> Show eGPU connection state, current play/display mode, a clear primary action, and safe-disconnect status using player-friendly language.
>
> Suggested asset: `assets/wiki/mockups/egpu-menu.png`

## Understanding status

The player interface should focus on what you need to know next rather than exposing raw hardware diagnostics.

Typical states may communicate ideas such as:

- **Not connected** — no supported external GPU is currently available.
- **Connecting / Switching** — Re-Gear is preparing the external setup.
- **Connected** — the external setup is active.
- **Preparing to disconnect** — Re-Gear is working to release the external setup.
- **Ready to disconnect** — Re-Gear has completed the supported disconnect preparation.
- **Needs attention** — Re-Gear cannot safely complete the requested action automatically.

> ### 🖼️ UI MOCKUP — eGPU state examples
> **TEMPORARY IMAGE PLACEHOLDER**
>
> A small visual strip showing several status states and their icons.
>
> Suggested asset: `assets/wiki/mockups/egpu-status-states.png`

## Safe disconnect

Do not treat unplugging an active eGPU like unplugging a simple USB accessory. Follow the status and instructions Re-Gear presents for the current build.

The safe-disconnect experience is still being actively validated. This Player Guide will only document a disconnect workflow as supported once that workflow has appropriate hardware validation.

## Want the engineering details?

The low-level eGPU lifecycle, hardware evidence, display behavior, and disconnect research are intentionally kept out of this player page. See the [Technical Guide](../technical/README.md) if you want to dig into them.