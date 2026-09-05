"""Power-control placement eligibility, independent of transition execution."""

from .control_plane import PlacementState
from .inference import infer_placement
from .models import EgpuPresence, ObservedSnapshot


def tdp_placement_readiness(snapshot: ObservedSnapshot, presence: EgpuPresence) -> str:
    """Explain current support without selecting a mode or granting write authority.

    Internal rendering on an external display is distinct from eGPU rendering.
    Neither has a validated power profile yet. Presence is checked independently
    even when the compositor still reports Portable during attachment.
    """
    placement = infer_placement(snapshot)
    if placement in (PlacementState.UNKNOWN, PlacementState.DEGRADED):
        return "tdp.placement_unverified"
    if presence is EgpuPresence.UNKNOWN:
        return "tdp.egpu_presence_unverified"
    if placement in (PlacementState.BOOSTED_HANDHELD, PlacementState.DOCKED_EGPU):
        return "tdp.egpu_power_profile_unavailable"
    if presence is not EgpuPresence.ABSENT:
        return "tdp.egpu_attached"
    if placement is PlacementState.DOCKED_IGPU:
        return "tdp.docked_power_profile_unavailable"
    return "tdp.ready"
