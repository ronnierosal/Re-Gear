"""Pure runtime revalidation for a bound presentation transition plan."""

from __future__ import annotations

from ..domain.control_plane import (
    CapabilitySupport,
    PlacementState,
    TransitionPlan,
)
from ..domain.inference import infer_placement
from ..domain.models import (
    Confidence,
    DisplayKind,
    GameState,
    GpuRole,
    ObservedSnapshot,
)
from ..profiles.registry import resolve_runtime_profiles


class StrictRuntimeTransitionPolicy:
    """Revalidate every identity and safety fact immediately before mutation."""

    def blockers(
        self,
        plan: TransitionPlan,
        snapshot: ObservedSnapshot,
        expected_placement: PlacementState,
    ) -> tuple[str, ...]:
        binding = plan.binding
        if binding is None:
            return ("identity.transition_binding_missing",)
        blockers: list[str] = []
        placement = infer_placement(snapshot)
        if placement is not expected_placement:
            blockers.append("placement.changed")
        if snapshot.game_state is not GameState.IDLE:
            blockers.append(
                "game.state_unknown"
                if snapshot.game_state is GameState.UNKNOWN
                else "game.running"
            )
        resolved = resolve_runtime_profiles(snapshot)
        if (
            not resolved.exact_host
            or resolved.capabilities.host_profile_id != binding.host_profile_id
            or snapshot.host_profile != binding.host_profile_id
        ):
            blockers.append("identity.host_changed")
        if (
            not resolved.exact_egpu
            or resolved.capabilities.egpu_profile_id != binding.egpu_profile_id
            or resolved.egpu_stable_id != binding.egpu_stable_id
        ):
            blockers.append("identity.egpu_changed")
        capability = resolved.capabilities.display_handoff
        if plan.experimental:
            if capability not in {
                CapabilitySupport.EXPERIMENTAL,
                CapabilitySupport.VERIFIED,
            }:
                blockers.append("capability.display_handoff_changed")
        elif capability is not CapabilitySupport.VERIFIED:
            blockers.append("capability.display_handoff_changed")

        if not self._exact_gpu(
            snapshot, binding.internal_gpu_stable_id, GpuRole.INTERNAL
        ):
            blockers.append("identity.internal_gpu_changed")
        if not self._exact_gpu(
            snapshot, binding.external_gpu_stable_id, GpuRole.EXTERNAL
        ):
            blockers.append("identity.external_gpu_changed")
        if not self._exact_display(
            snapshot, binding.internal_display_stable_id, DisplayKind.INTERNAL
        ):
            blockers.append("identity.internal_display_changed")
        if not self._exact_display(
            snapshot, binding.external_display_stable_id, DisplayKind.EXTERNAL
        ):
            blockers.append("identity.external_display_changed")
        external = tuple(
            display
            for display in snapshot.displays
            if display.stable_id == binding.external_display_stable_id
        )
        if (
            plan.target_placement is PlacementState.DOCKED_EGPU
            and (len(external) != 1 or external[0].edid_ready is not True)
        ):
            blockers.append("display.external_unready")
        return tuple(dict.fromkeys(blockers))

    @staticmethod
    def _exact_gpu(
        snapshot: ObservedSnapshot, stable_id: str, role: GpuRole
    ) -> bool:
        matches = tuple(gpu for gpu in snapshot.gpus if gpu.stable_id == stable_id)
        return bool(
            len(matches) == 1
            and matches[0].role is role
            and matches[0].present
            and matches[0].confidence is Confidence.VERIFIED
        )

    @staticmethod
    def _exact_display(
        snapshot: ObservedSnapshot, stable_id: str, kind: DisplayKind
    ) -> bool:
        matches = tuple(
            display for display in snapshot.displays if display.stable_id == stable_id
        )
        return bool(
            len(matches) == 1
            and matches[0].kind is kind
            and matches[0].connected is True
            and matches[0].confidence is Confidence.VERIFIED
        )
