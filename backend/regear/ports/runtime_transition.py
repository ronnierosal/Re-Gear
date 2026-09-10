"""Runtime-only boundaries for durable transition execution."""

from __future__ import annotations

from typing import Protocol

from ..domain.control_plane import (
    PlacementState,
    PlannedStep,
    TransitionBinding,
)
from ..domain.models import ObservedSnapshot
from .transition import MechanismResult


class RuntimeTransitionMechanismPort(Protocol):
    def apply(
        self,
        step: PlannedStep,
        binding: TransitionBinding,
        observation: ObservedSnapshot,
    ) -> MechanismResult:
        """Attempt one typed step using the exact freshly validated binding."""

    def recover(
        self,
        source: PlacementState,
        binding: TransitionBinding | None,
        observation: ObservedSnapshot | None,
    ) -> MechanismResult:
        """Idempotently attempt to restore the known-good source placement."""


class DeadlineWaitPort(Protocol):
    def wait_ms(self, milliseconds: int) -> None:
        """Yield briefly before the next bounded verification observation."""
