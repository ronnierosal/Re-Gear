"""Pure description of the supported display-target/render-GPU combinations.

Two different player requests are routinely confused:

1. keep the same render GPU and move only the **display**, and
2. drive the external display from the **internal** GPU while an eGPU is
   attached.

They are different operations with different consequences, yet the existing
capability vocabulary exposes a single `display_handoff` axis and the existing
planner exposes a single pair of placement targets. This module makes the
distinction explicit and testable *without* granting any new authority.

What this module is:

- a read-only classification of the four observable placements against the one
  supported output route (the boot-scoped Gamescope launch configuration), and
- a classifier that reports whether a requested change moves the display, moves
  the renderer, or both, and therefore whether the current game must be closed.

What this module is **not**: it owns no mechanism, approval, planning,
persistence or transition authority; it observes nothing; it cannot relax the
running-game, identity or capability guards; and it never asserts that a
workload can be migrated between GPUs. `plan_manual_transition` and
`SupervisedTransitionService` remain the authority on what may actually be
planned — `tests/test_display_render_modes.py` asserts this module agrees with
the planner instead of becoming a second, drifting source of truth.

Every entry in this table is a statement about *code*, not about hardware. A
combination marked representable has an expressible launch configuration; it is
not a claim that the certified hardware presents it correctly. See
`docs/DISPLAY_RENDER_MODE_CONTRACT.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .control_plane import PlacementState
from .models import GameState, OperatingMode


class DisplayTarget(StrEnum):
    """Which panel the compositor is asked to scan out to."""

    INTERNAL_PANEL = "internal_panel"
    EXTERNAL_DISPLAY = "external_display"
    UNKNOWN = "unknown"


class RenderGpu(StrEnum):
    """Which GPU the compositor is asked to render on."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class RouteSupport(StrEnum):
    """How far a combination gets through the one supported output route."""

    #: A boot-scoped launch target exists and the planner accepts it as a
    #: destination, so a guarded request can be made for it today.
    PLANNABLE = "plannable"
    #: A boot-scoped launch target exists and the shim honours it, but no
    #: planner/facade destination reaches it. It is currently reachable only as
    #: the restore of a placement that was already observed.
    LAUNCH_ROUTE_ONLY = "launch_route_only"
    #: No boot-scoped launch target can express this combination at all.
    UNREPRESENTABLE = "unrepresentable"


@dataclass(frozen=True, slots=True)
class DisplayRenderCombination:
    """One observable placement described against the supported route."""

    placement: PlacementState
    display: DisplayTarget
    render: RenderGpu
    #: `GamescopeLaunchConfig.target` that expresses it, or "" when none does.
    launch_config_target: str
    #: Whether `plan_manual_transition` accepts it as a destination today.
    planner_target: bool
    #: The public `OperatingMode` a player would be shown in this placement.
    public_mode: OperatingMode
    #: Whether the current representation structurally requires a verified
    #: attached eGPU, because the external connector and its launch binding are
    #: owned by that eGPU.
    requires_attached_egpu: bool
    support: RouteSupport

    def __post_init__(self) -> None:
        representable = bool(self.launch_config_target)
        if self.planner_target and not representable:
            raise ValueError("a planner target must be representable")
        if self.support is RouteSupport.UNREPRESENTABLE and representable:
            raise ValueError("an unrepresentable combination cannot name a target")
        if self.support is RouteSupport.PLANNABLE and not self.planner_target:
            raise ValueError("a plannable combination requires a planner target")


#: The four observable placements. `PlacementState.UNKNOWN` and `DEGRADED` are
#: deliberately absent: they are not combinations, they are refusals.
COMBINATIONS: dict[PlacementState, DisplayRenderCombination] = {
    PlacementState.PORTABLE: DisplayRenderCombination(
        placement=PlacementState.PORTABLE,
        display=DisplayTarget.INTERNAL_PANEL,
        render=RenderGpu.INTERNAL,
        launch_config_target="portable",
        planner_target=True,
        public_mode=OperatingMode.PORTABLE,
        requires_attached_egpu=False,
        support=RouteSupport.PLANNABLE,
    ),
    PlacementState.DOCKED_EGPU: DisplayRenderCombination(
        placement=PlacementState.DOCKED_EGPU,
        display=DisplayTarget.EXTERNAL_DISPLAY,
        render=RenderGpu.EXTERNAL,
        launch_config_target="docked_egpu",
        planner_target=True,
        public_mode=OperatingMode.TV_DOCKED,
        requires_attached_egpu=True,
        support=RouteSupport.PLANNABLE,
    ),
    PlacementState.DOCKED_IGPU: DisplayRenderCombination(
        placement=PlacementState.DOCKED_IGPU,
        display=DisplayTarget.EXTERNAL_DISPLAY,
        render=RenderGpu.INTERNAL,
        launch_config_target="docked_igpu",
        planner_target=False,
        # `infer_operating_mode` has no internal-renderer/external-display case,
        # so a player in this placement is shown Unknown today.
        public_mode=OperatingMode.UNKNOWN,
        requires_attached_egpu=True,
        support=RouteSupport.LAUNCH_ROUTE_ONLY,
    ),
    PlacementState.BOOSTED_HANDHELD: DisplayRenderCombination(
        placement=PlacementState.BOOSTED_HANDHELD,
        display=DisplayTarget.INTERNAL_PANEL,
        render=RenderGpu.EXTERNAL,
        launch_config_target="",
        planner_target=False,
        public_mode=OperatingMode.BOOSTED_HANDHELD,
        requires_attached_egpu=True,
        support=RouteSupport.UNREPRESENTABLE,
    ),
}


@dataclass(frozen=True, slots=True)
class DisplayRenderChange:
    """What a requested placement change actually changes, and what it costs."""

    current: PlacementState
    target: PlacementState
    display_changes: bool
    render_gpu_changes: bool
    #: The only supported output route is applied when Gamescope execs, so any
    #: real change needs a Gamescope session restart.
    gamescope_restart_required: bool
    #: A Gamescope session restart ends the current session, so the running
    #: game must be closed first. This is never waived by this module.
    game_close_required: bool
    #: True only when the renderer itself changes, so the relaunched game runs
    #: on a different GPU. Re-Gear never moves a running workload.
    relaunch_lands_on_a_different_gpu: bool
    #: Refusal codes the existing planner/facade emit for this request, in the
    #: planner's own vocabulary. Empty does not mean "permitted": identity,
    #: capability, readiness and recovery evidence are still evaluated by the
    #: planner against a live observation.
    refusals: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_no_op(self) -> bool:
        return self.current is self.target

    @property
    def is_display_only(self) -> bool:
        """The display moves and the renderer does not."""
        return self.display_changes and not self.render_gpu_changes

    @property
    def is_render_handoff(self) -> bool:
        """The renderer changes, whether or not the display also moves."""
        return self.render_gpu_changes


def combination_for(placement: PlacementState) -> DisplayRenderCombination | None:
    """Return the described combination, or None for a non-combination state."""
    return COMBINATIONS.get(placement)


def classify_change(
    *,
    current: PlacementState,
    target: PlacementState,
    game_state: GameState | None = None,
) -> DisplayRenderChange:
    """Describe a requested display/render change and the refusals it meets.

    `game_state` is optional so the vocabulary can be used for documentation and
    UI copy without an observation. Supplying it adds the planner's own
    running-game and unknown-game refusals; omitting it never implies the game
    state is safe.
    """
    refusals: list[str] = []
    source = combination_for(current)
    destination = combination_for(target)
    if source is None:
        refusals.append("placement.current_unverified")
    if destination is None or not destination.planner_target:
        refusals.append("placement.target_unsupported")

    no_op = current is target and source is not None
    display_changes = (
        source is not None
        and destination is not None
        and source.display is not destination.display
    )
    render_gpu_changes = (
        source is not None
        and destination is not None
        and source.render is not destination.render
    )
    restart_required = not no_op and source is not None and destination is not None

    if restart_required and game_state is not None:
        if game_state is GameState.UNKNOWN:
            refusals.append("game.state_unknown")
        elif game_state is GameState.RUNNING:
            refusals.append("game.running")

    return DisplayRenderChange(
        current=current,
        target=target,
        display_changes=display_changes,
        render_gpu_changes=render_gpu_changes,
        gamescope_restart_required=restart_required,
        game_close_required=restart_required,
        relaunch_lands_on_a_different_gpu=restart_required and render_gpu_changes,
        refusals=tuple(dict.fromkeys(refusals)),
    )
