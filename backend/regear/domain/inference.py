"""Derive player-facing modes without hiding incomplete evidence."""

from __future__ import annotations

from .models import (
    Confidence,
    DisplayKind,
    GpuRole,
    ModeInference,
    ObservedSnapshot,
    OperatingMode,
)
from .control_plane import PlacementState


def infer_placement(snapshot: ObservedSnapshot) -> PlacementState:
    """Derive target placement while retaining the legacy public mode schema."""
    if snapshot.gamescope.running is not True:
        return PlacementState.DEGRADED
    if snapshot.gamescope.confidence is not Confidence.VERIFIED:
        return PlacementState.UNKNOWN

    renderers = [gpu for gpu in snapshot.gpus if gpu.selected_for_render is True]
    active_displays = [display for display in snapshot.displays if display.active is True]
    if len(renderers) != 1 or len(active_displays) != 1:
        return PlacementState.UNKNOWN

    renderer = renderers[0]
    display = active_displays[0]
    if (
        not renderer.present
        or renderer.confidence is not Confidence.VERIFIED
        or snapshot.gamescope.render_gpu_stable_id != renderer.stable_id
        or display.connected is not True
        or display.confidence is not Confidence.VERIFIED
        or display.connector not in snapshot.gamescope.output_order
    ):
        return PlacementState.UNKNOWN

    if renderer.role is GpuRole.INTERNAL and display.kind is DisplayKind.INTERNAL:
        return PlacementState.PORTABLE
    if renderer.role is GpuRole.EXTERNAL and display.kind is DisplayKind.INTERNAL:
        return PlacementState.BOOSTED_HANDHELD
    if renderer.role is GpuRole.INTERNAL and display.kind is DisplayKind.EXTERNAL:
        return PlacementState.DOCKED_IGPU
    if renderer.role is GpuRole.EXTERNAL and display.kind is DisplayKind.EXTERNAL:
        return PlacementState.DOCKED_EGPU
    return PlacementState.UNKNOWN


def infer_operating_mode(snapshot: ObservedSnapshot) -> ModeInference:
    if snapshot.gamescope.running is not True:
        return ModeInference(
            OperatingMode.DEGRADED,
            ("Gamescope is not verified as running.",),
        )
    if snapshot.gamescope.confidence is not Confidence.VERIFIED:
        return ModeInference(
            OperatingMode.UNKNOWN,
            ("Gamescope state is not verified.",),
        )

    renderers = [gpu for gpu in snapshot.gpus if gpu.selected_for_render is True]
    if len(renderers) != 1:
        return ModeInference(
            OperatingMode.UNKNOWN,
            (f"Expected one verified render GPU; observed {len(renderers)}.",),
        )

    active_displays = [display for display in snapshot.displays if display.active is True]
    if len(active_displays) != 1:
        return ModeInference(
            OperatingMode.UNKNOWN,
            (f"Expected one verified active display; observed {len(active_displays)}.",),
        )

    renderer = renderers[0]
    display = active_displays[0]

    if not renderer.present or renderer.confidence is not Confidence.VERIFIED:
        return ModeInference(
            OperatingMode.UNKNOWN,
            ("The selected render GPU is not verified as present.",),
        )
    if snapshot.gamescope.render_gpu_stable_id != renderer.stable_id:
        return ModeInference(
            OperatingMode.UNKNOWN,
            ("Gamescope render identity conflicts with the selected GPU.",),
        )
    if (
        display.connected is not True
        or display.confidence is not Confidence.VERIFIED
    ):
        return ModeInference(
            OperatingMode.UNKNOWN,
            ("The active display is not verified as connected.",),
        )
    if display.connector not in snapshot.gamescope.output_order:
        return ModeInference(
            OperatingMode.UNKNOWN,
            ("Gamescope output order conflicts with the active display.",),
        )

    if renderer.role is GpuRole.INTERNAL and display.kind is DisplayKind.INTERNAL:
        return ModeInference(OperatingMode.PORTABLE, ())
    if renderer.role is GpuRole.EXTERNAL and display.kind is DisplayKind.INTERNAL:
        return ModeInference(OperatingMode.BOOSTED_HANDHELD, ())
    if renderer.role is GpuRole.EXTERNAL and display.kind is DisplayKind.EXTERNAL:
        return ModeInference(OperatingMode.TV_DOCKED, ())

    return ModeInference(
        OperatingMode.UNKNOWN,
        ("The render-GPU/display combination is not a supported user-facing mode.",),
    )
