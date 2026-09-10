"""Immutable process-release values shared by policy and future mechanisms."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import EgpuClientKind, EgpuResourceKind


class ReleasePhase(StrEnum):
    GRACEFUL = "graceful"
    FORCE = "force"


@dataclass(frozen=True, slots=True)
class ProcessReleaseTarget:
    instance_id: str
    pid: int
    name: str
    resources: tuple[EgpuResourceKind, ...]
    process_start_time: str

    def __post_init__(self) -> None:
        if not self.instance_id or self.pid <= 1:
            raise ValueError("process release target identity is invalid")
        if not self.name or len(self.name) > 64:
            raise ValueError("process release target name is invalid")
        if not self.resources or len(self.resources) != len(set(self.resources)):
            raise ValueError("process release target resources are invalid")
        if not self.process_start_time.isdigit() or int(self.process_start_time) <= 0:
            raise ValueError("process release target start-time identity is invalid")


@dataclass(frozen=True, slots=True)
class ProcessClientFact:
    instance_id: str
    pid: int
    name: str
    kind: EgpuClientKind
    resources: tuple[EgpuResourceKind, ...]
    close_eligible: bool
    process_start_time: str


@dataclass(frozen=True, slots=True)
class ProcessReleaseApproval:
    operation_id: str
    phase: ReleasePhase
    egpu_stable_id: str
    observed_generation: str
    client_fingerprint: str
    targets: tuple[ProcessReleaseTarget, ...]
    observed_clients: tuple[ProcessClientFact, ...]
    prior_graceful_operation_id: str = ""
    parent_operation_id: str = ""


@dataclass(frozen=True, slots=True)
class ProcessReleasePreviewRow:
    name: str
    resources: tuple[EgpuResourceKind, ...]


@dataclass(frozen=True, slots=True)
class ProcessReleasePreview:
    token: str
    phase: ReleasePhase
    expires_in_seconds: int
    targets: tuple[ProcessReleasePreviewRow, ...]
    protected_client_count: int
