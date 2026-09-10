"""Conservative snapshot-to-sleep-context observation adapter."""

from __future__ import annotations

from collections.abc import Callable

from ..domain.game_compatibility import GameSaveCapability
from ..domain.inference import infer_placement
from ..domain.models import Confidence, EgpuPresence, GpuRole, ObservedSnapshot
from ..domain.sleep_workflow import SleepWorkflowContext
from ..ports.sleep_workflow import SleepWorkflowObservation
from ..ports.transition import TransitionObservationPort
from ..profiles.registry import resolve_runtime_profiles


class SnapshotSleepWorkflowObservationAdapter:
    """Build a typed sleep context without promoting ambiguous hardware."""

    def __init__(
        self,
        observations: TransitionObservationPort,
        *,
        save_capability: Callable[[ObservedSnapshot], GameSaveCapability] = (
            lambda _snapshot: GameSaveCapability.UNTESTED
        ),
        removal_readiness: Callable[[ObservedSnapshot], bool] = (
            lambda _snapshot: False
        ),
    ) -> None:
        self._observations = observations
        self._save_capability = save_capability
        self._removal_readiness = removal_readiness

    def observe(self) -> SleepWorkflowObservation:
        observed = self._observations.observe()
        snapshot = observed.snapshot
        profiles = resolve_runtime_profiles(snapshot)
        presence = self._egpu_presence(snapshot, exact=profiles.exact_egpu)
        exact_identity = (
            profiles.exact_egpu
            if presence is EgpuPresence.PRESENT
            else presence is EgpuPresence.ABSENT
        )
        context = SleepWorkflowContext(
            egpu_presence=presence,
            exact_egpu_identity_verified=exact_identity,
            capabilities=profiles.capabilities,
            game_state=snapshot.game_state,
            save_capability=self._save_capability(snapshot),
            disconnect_readiness=snapshot.disconnect_readiness,
            placement=infer_placement(snapshot),
            removal_readiness_verified=self._removal_readiness(snapshot),
        )
        return SleepWorkflowObservation(
            observed.generation,
            observed.sample_id,
            context,
            profiles.egpu_stable_id,
        )

    @staticmethod
    def _egpu_presence(
        snapshot: ObservedSnapshot, *, exact: bool
    ) -> EgpuPresence:
        if exact:
            return EgpuPresence.PRESENT
        if any(
            blocker.code in {"drm_inventory_unavailable", "egpu_identity_unverified"}
            for blocker in snapshot.blockers
        ):
            return EgpuPresence.UNKNOWN
        external = tuple(gpu for gpu in snapshot.gpus if gpu.role is GpuRole.EXTERNAL)
        if any(
            gpu.present is not False or gpu.confidence is not Confidence.VERIFIED
            for gpu in external
        ):
            return EgpuPresence.UNKNOWN
        return EgpuPresence.ABSENT
