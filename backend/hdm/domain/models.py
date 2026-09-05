"""Immutable, I/O-free contracts for observed HDM state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Confidence(StrEnum):
    UNKNOWN = "unknown"
    OBSERVED = "observed"
    VERIFIED = "verified"


class GpuRole(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class DisplayKind(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class GameState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    UNKNOWN = "unknown"


class SupportTier(StrEnum):
    CERTIFIED = "certified"
    COMPATIBLE = "compatible"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class OperatingMode(StrEnum):
    PORTABLE = "portable"
    BOOSTED_HANDHELD = "boosted_handheld"
    TV_DOCKED = "tv_docked"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"


class EgpuClientKind(StrEnum):
    GAME = "game"
    USER = "user"
    PROTECTED = "protected"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class EgpuResourceKind(StrEnum):
    DRM_CARD = "drm_card"
    DRM_RENDER = "drm_render"
    DRM_CONTROL = "drm_control"
    AUDIO_PCM = "audio_pcm"
    AUDIO_CONTROL = "audio_control"
    AUDIO_HARDWARE = "audio_hardware"


class EgpuPresence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class EgpuLinkState(StrEnum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class SleepGuardAction(StrEnum):
    ACQUIRE = "acquire"
    RELEASE = "release"
    HOLD = "hold"


class TransitionPhase(StrEnum):
    IDLE = "idle"
    DETECTING = "detecting"
    VALIDATING = "validating"
    PLANNING = "planning"
    PREPARING = "preparing"
    APPLYING = "applying"
    VERIFYING = "verifying"
    COMMITTING = "committing"
    BLOCKED = "blocked"
    ROLLING_BACK = "rolling_back"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Evidence:
    source: str
    confidence: Confidence
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GpuObservation:
    stable_id: str
    role: GpuRole
    vendor_device: str
    present: bool
    selected_for_render: bool | None
    confidence: Confidence
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
    model_name: str = field(default="", compare=False)


@dataclass(frozen=True, slots=True)
class DisplayObservation:
    stable_id: str
    kind: DisplayKind
    connector: str
    connected: bool | None
    active: bool | None
    edid_ready: bool | None
    confidence: Confidence
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GamescopeObservation:
    running: bool | None
    pid: int | None
    output_order: tuple[str, ...] = field(default_factory=tuple)
    render_gpu_stable_id: str = ""
    render_vendor_device: str = ""
    confidence: Confidence = Confidence.UNKNOWN
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Blocker:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class EgpuClientObservation:
    instance_id: str
    pid: int
    name: str
    kind: EgpuClientKind
    resources: tuple[EgpuResourceKind, ...]
    close_eligible: bool
    reason: str
    process_start_time: str = ""


@dataclass(frozen=True, slots=True)
class DisconnectReadinessObservation:
    applicable: bool
    scan_complete: bool
    ready: bool
    egpu_stable_id: str = ""
    clients: tuple[EgpuClientObservation, ...] = field(default_factory=tuple)
    storage_devices: int = 0
    storage_in_use: bool = False
    error: str = ""


@dataclass(frozen=True, slots=True)
class SleepGuardObservation:
    required: bool
    active: bool
    confidence: Confidence
    reason: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class EgpuLinkObservation:
    applicable: bool
    state: EgpuLinkState
    confidence: Confidence
    reason: str = ""
    error: str = ""
    speed_gtps: float | None = None
    width_lanes: int | None = None


@dataclass(frozen=True, slots=True)
class ObservedSnapshot:
    schema_version: int
    observed_at: str
    host_profile: str
    support_tier: SupportTier
    game_state: GameState
    gpus: tuple[GpuObservation, ...]
    displays: tuple[DisplayObservation, ...]
    gamescope: GamescopeObservation
    disconnect_readiness: DisconnectReadinessObservation = field(
        default_factory=lambda: DisconnectReadinessObservation(False, True, True)
    )
    sleep_guard: SleepGuardObservation = field(
        default_factory=lambda: SleepGuardObservation(
            False, False, Confidence.UNKNOWN
        )
    )
    egpu_link: EgpuLinkObservation = field(
        default_factory=lambda: EgpuLinkObservation(
            False, EgpuLinkState.UNKNOWN, Confidence.UNKNOWN
        )
    )
    blockers: tuple[Blocker, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ModeInference:
    mode: OperatingMode
    reasons: tuple[str, ...]
