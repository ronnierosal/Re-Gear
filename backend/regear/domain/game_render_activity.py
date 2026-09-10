"""Pure private DRM engine evidence for one exact game's GPU activity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .control_plane import PlacementState
from .game_runtime import GameRuntimeKind


BDF_RE = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$")
GPU_ID_RE = re.compile(r"^[a-z0-9_.:-]{1,96}$")
RENDER_NODE_RE = re.compile(r"^/dev/dri/renderD[0-9]+$")
ENGINE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
ERROR_RE = re.compile(r"^[a-z0-9_.-]{1,96}$")
MAX_ENGINE_CLIENTS = 128
MAX_ENGINES_PER_CLIENT = 32


class GameRenderActivityStatus(StrEnum):
    ACTIVE = "active"
    IDLE_WINDOW = "idle_window"
    NO_CLIENT = "no_client"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DrmRenderBinding:
    gpu_stable_id: str
    pci_bdf: str
    render_node: str

    def __post_init__(self) -> None:
        if not GPU_ID_RE.fullmatch(self.gpu_stable_id):
            raise ValueError("DRM render binding GPU identity is invalid")
        if not BDF_RE.fullmatch(self.pci_bdf):
            raise ValueError("DRM render binding PCI identity is invalid")
        if not RENDER_NODE_RE.fullmatch(self.render_node):
            raise ValueError("DRM render binding node is invalid")


@dataclass(frozen=True, slots=True)
class DrmEngineClientCounters:
    pid: int
    process_start_time_ticks: int
    drm_client_id: int
    counters_ns: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if (
            self.pid <= 0
            or self.process_start_time_ticks <= 0
            or self.drm_client_id < 0
        ):
            raise ValueError("DRM engine client identity is invalid")
        if not self.counters_ns or len(self.counters_ns) > MAX_ENGINES_PER_CLIENT:
            raise ValueError("DRM engine counter set is invalid")
        names = tuple(name for name, _value in self.counters_ns)
        if len(names) != len(set(names)) or any(
            not ENGINE_RE.fullmatch(name) for name in names
        ):
            raise ValueError("DRM engine names are invalid")
        if any(value < 0 for _name, value in self.counters_ns):
            raise ValueError("DRM engine counter is invalid")

    @property
    def identity(self) -> tuple[int, int, int]:
        return self.pid, self.process_start_time_ticks, self.drm_client_id


@dataclass(frozen=True, slots=True)
class DrmEngineCounterSample:
    clients: tuple[DrmEngineClientCounters, ...]
    complete: bool
    error_code: str = ""

    def __post_init__(self) -> None:
        if len(self.clients) > MAX_ENGINE_CLIENTS:
            raise ValueError("DRM engine client count is invalid")
        identities = tuple(client.identity for client in self.clients)
        if len(identities) != len(set(identities)):
            raise ValueError("DRM engine client identity is duplicated")
        if self.complete and self.error_code:
            raise ValueError("complete DRM engine evidence cannot have an error")
        if not self.complete:
            if self.clients or not ERROR_RE.fullmatch(self.error_code):
                raise ValueError("incomplete DRM engine evidence must fail closed")


@dataclass(frozen=True, slots=True)
class GameRenderActivityEvidence:
    status: GameRenderActivityStatus
    runtime_kind: GameRuntimeKind
    active_engine_count: int
    reason_code: str
    evidence_generation: str = ""
    placement: PlacementState = PlacementState.UNKNOWN

    def __post_init__(self) -> None:
        if not 0 <= self.active_engine_count <= (
            MAX_ENGINE_CLIENTS * MAX_ENGINES_PER_CLIENT
        ):
            raise ValueError("active DRM engine count is invalid")
        if not ERROR_RE.fullmatch(self.reason_code):
            raise ValueError("render activity reason must be categorical")
        known = self.status is not GameRenderActivityStatus.UNKNOWN
        if known and (
            not re.fullmatch(r"[0-9a-f]{64}", self.evidence_generation)
            or self.placement in {PlacementState.UNKNOWN, PlacementState.DEGRADED}
        ):
            raise ValueError("known render activity requires exact observation identity")
        if not known and (
            self.evidence_generation or self.placement is not PlacementState.UNKNOWN
        ):
            raise ValueError("unknown render activity cannot carry partial identity")
        if self.status is GameRenderActivityStatus.ACTIVE:
            if self.active_engine_count <= 0:
                raise ValueError("active render evidence requires a counter delta")
            if self.runtime_kind is GameRuntimeKind.UNKNOWN:
                raise ValueError("active render evidence requires exact runtime")
        elif self.active_engine_count:
            raise ValueError("non-active render evidence cannot carry deltas")
        if (
            self.status
            in {
                GameRenderActivityStatus.IDLE_WINDOW,
                GameRenderActivityStatus.NO_CLIENT,
            }
            and self.runtime_kind is GameRuntimeKind.UNKNOWN
        ):
            raise ValueError("known render evidence requires exact runtime")

    @property
    def proves_active_rendering(self) -> bool:
        return self.status is GameRenderActivityStatus.ACTIVE
