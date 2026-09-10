"""Observation boundary for canonical sleep workflow orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.models import EgpuPresence
from ..domain.sleep_workflow import SleepWorkflowContext


@dataclass(frozen=True, slots=True)
class SleepWorkflowObservation:
    generation: str
    sample_id: str
    context: SleepWorkflowContext
    egpu_stable_id: str = ""

    def __post_init__(self) -> None:
        if not self.generation or not self.sample_id:
            raise ValueError("sleep workflow observation identity is required")
        if (
            self.context.egpu_presence is EgpuPresence.PRESENT
            and self.context.exact_egpu_identity_verified
            and not self.egpu_stable_id
        ):
            raise ValueError("exact present eGPU identity is required")


class SleepWorkflowObservationPort(Protocol):
    def observe(self) -> SleepWorkflowObservation:
        """Return one current, exact, independently freshness-tagged context."""
