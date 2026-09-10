"""Dormant mechanism boundary for unexpected-undock recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.event_policy import TopologyEvent
from ..domain.models import ObservedSnapshot
from .transition import MechanismResult


@dataclass(frozen=True, slots=True)
class UnexpectedUndockBinding:
    """Exact, ephemeral recovery identities that never enter public results."""

    event: TopologyEvent
    host_profile_id: str
    egpu_profile_id: str
    egpu_stable_id: str
    internal_gpu_stable_id: str
    internal_display_stable_id: str
    lost_resource_stable_id: str

    def __post_init__(self) -> None:
        if self.event not in {
            TopologyEvent.EGPU_REMOVED,
            TopologyEvent.EXTERNAL_DISPLAY_LOST,
        }:
            raise ValueError("unexpected-undock binding requires a loss event")
        if not all(
            (
                self.host_profile_id,
                self.egpu_profile_id,
                self.egpu_stable_id,
                self.internal_gpu_stable_id,
                self.internal_display_stable_id,
                self.lost_resource_stable_id,
            )
        ):
            raise ValueError("unexpected-undock binding requires exact identities")


class UnexpectedUndockRecoveryMechanismPort(Protocol):
    def restore_portable(
        self,
        binding: UnexpectedUndockBinding,
        observation: ObservedSnapshot,
        deadline_ms: int,
    ) -> MechanismResult:
        """Attempt restoration within the supplied application deadline."""

    def preserve_portable_path(
        self,
        binding: UnexpectedUndockBinding,
        observation: ObservedSnapshot | None,
        deadline_ms: int,
    ) -> MechanismResult:
        """Undo partial work and retain Portable within the supplied deadline."""
