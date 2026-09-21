> **Archived September 14, 2026.** Historical source at `9421c6f`; superseded by the [canonical Wiki](https://github.com/ronnierosal/Re-Gear/tree/main/docs/wiki). Do not use this as current instructions.

# Command Center

**Audience:** players and UI contributors<br>
**Reviewed:** 2026-09-13<br>
**Maturity:** implemented in source; native Decky/controller validation pending

Quick Access puts current state and immediate controls first. **Modules** opens deep configuration without leaving a long settings panel beneath the quick tiles.

> **Temporary UI mockup** — this is a documentation visual, not a final shipping screenshot. It will be replaced after native UI validation.

![Temporary Re-Gear Command Center mockup](https://github.com/ronnierosal/Re-Gear/blob/9421c6f4f33dd22a0fc55857fb544e36d0a43d7f/assets/wiki/mockups/command-center-overview.svg)

## Quick controls

| Tile | Behavior |
|---|---|
| FPS target | Unavailable until a verified frame-rate provider exists. This is separate from Auto TDP's target FPS. |
| TDP limit | Shows an observed configured limit, not measured power use. Opens device-reported choices and guarded Apply. |
| Auto TDP | Shows observed loop state independently of power-control enablement. Stop while running; Configure otherwise. |
| Display target | Opens the same guarded display action as the eGPU module, including return from either docked mode. |
| Safe Disconnect | Uses the backend's current offer and confirmation. A software-removal result does not authorize pulling the cable. |

Unavailable tiles keep their positions and explain why they cannot act. Unknown values remain unknown. Power controls use one shared state/request owner; opening a module does not add a second collector. Stop keeps the current power limit; Restore returns to saved settings. Saving a mode preference never starts Auto TDP.

## Modules and status

**Modules** contains eGPU docking controls, Auto TDP tuning and saved preferences, and Controller observations. Benchmark collection remains behind disclosure. The **eGPU status** and **Controller status** rows are read-only destinations. **Troubleshoot** is available from both Command Center and Modules.

Back returns to the invoking control; Back at Command Center delegates to Steam. Reopening Quick Access starts at Command Center. Native validation of those controller interactions is still required.

## Customize Quick Access

The player-facing customization guide is being expanded with visual walkthroughs for moving, changing and resetting Quick Access buttons. Temporary visuals are deliberately marked so they cannot be confused with native screenshots.

## Disconnect evidence

The current backend's unavailable eGPU status can also mean a failed observation or missing attachment identity. It does not prove that the device disappeared from the bus. The result view preserves reported software-removal outcomes but withholds physical cable clearance. Dock USB and Thunderbolt teardown is a separate outstanding check. Follow the shutdown-before-disconnect guidance in [Safety invariants](https://github.com/ronnierosal/Re-Gear/blob/main/docs/SAFETY_INVARIANTS.md).
[Issue #147](https://github.com/ronnierosal/Re-Gear/issues/147) tracks the separate contract decision; the UI does not decide it.

## Validation and remaining work

The [UI specification](https://github.com/ronnierosal/Re-Gear/blob/main/docs/UI_SPEC.md) and [validation record](https://github.com/ronnierosal/Re-Gear/blob/main/docs/COMMAND_CENTER_VALIDATION.md) identify implementation and evidence limits. Browser captures render actual TSX with synthetic readings and mocked Decky controls; they are not handheld photos or native focus proof. No installation or hardware-tested claim follows from source integration.

**Priority:** complete native D-pad, Back, focus and scrolling checks, then replace temporary mockups with real Decky screenshots. Game-close and sleep integration remains dependent on the owning eGPU flow work. See [Current State](Current-State.md).
