"""Pure state for the bounded G1 connection-readiness window.

The lifecycle consumes facts collected elsewhere.  It performs no discovery and
does not authorize or execute a transition.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import time

from ..domain.models import GameState


WINDOW_TIMEOUT_SECONDS = 120.0
TOPOLOGY_STABILITY_SAMPLES = 4
PERIPHERAL_STABILITY_SAMPLES = 2


class ConnectionReadinessStage(StrEnum):
    DISCONNECTED = "disconnected"
    TRANSPORT_DETECTED = "transport_detected"
    WAITING_FOR_PCI = "waiting_for_pci"
    WAITING_FOR_DRIVER = "waiting_for_driver"
    WAITING_FOR_LINK = "waiting_for_link"
    WAITING_FOR_HDMI = "waiting_for_hdmi"
    WAITING_FOR_AUDIO = "waiting_for_audio"
    WAITING_FOR_SESSION = "waiting_for_session"
    GAME_RUNNING = "game_running"
    STABILIZING = "stabilizing"
    READY_IDLE = "ready_idle"
    LINK_TRAINING_FAILED = "link_training_failed"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"


@dataclass(frozen=True, slots=True)
class ConnectionReadinessObservation:
    """One complete, read-only discovery sample.

    Identities are opaque adapter-issued tokens. ``transport_absent_verified``
    distinguishes proven absence from an incomplete transport observation.
    """

    sample_id: str
    transport_identity: str = ""
    transport_present: bool = False
    transport_absent_verified: bool = False
    g1_identity: str = ""
    pci_complete: bool = False
    driver_ready: bool = False
    link_up: bool = False
    hdmi_ready: bool = False
    audio_ready: bool = False
    session_ready: bool = False
    game_state: GameState = GameState.UNKNOWN

    def __post_init__(self) -> None:
        if not self.sample_id:
            raise ValueError("connection readiness sample identity is required")
        if self.transport_present and not self.transport_identity:
            raise ValueError("present transport requires an opaque identity")
        if self.transport_present and self.transport_absent_verified:
            raise ValueError("transport cannot be present and verified absent")
        if self.g1_identity and not self.pci_complete:
            raise ValueError("exact G1 identity requires a complete PCI subtree")


@dataclass(frozen=True, slots=True)
class ConnectionReadinessStatus:
    stage: ConnectionReadinessStage
    code: str
    poll_after_ms: int
    window_age_ms: int = 0
    topology_samples: int = 0
    hdmi_samples: int = 0
    audio_samples: int = 0


class ConnectionReadinessLifecycle:
    """Track one transport generation and its independent readiness facts."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._transport_identity = ""
        self._g1_identity = ""
        self._started_at: float | None = None
        self._last_sample_id = ""
        self._topology_samples = 0
        self._hdmi_samples = 0
        self._audio_samples = 0
        self._failure_requires_absence = False
        self._readiness_established = False
        self._status = self._make_status(
            ConnectionReadinessStage.DISCONNECTED, "connection.disconnected", 0.0
        )

    def status(self) -> ConnectionReadinessStatus:
        return self._status

    def update(self, observation: ConnectionReadinessObservation) -> ConnectionReadinessStatus:
        now = self._clock()

        if observation.transport_absent_verified:
            self._reset_window()
            self._failure_requires_absence = False
            self._status = self._make_status(
                ConnectionReadinessStage.DISCONNECTED, "connection.disconnected", 0.0
            )
            return self._status

        if not observation.transport_present:
            self._reset_stability()
            self._last_sample_id = ""
            if self._started_at is not None and not self._g1_identity:
                self._failure_requires_absence = True
                self._status = self._make_status(
                    ConnectionReadinessStage.LINK_TRAINING_FAILED,
                    "connection.transport_dropped_before_pci",
                    now,
                )
            elif self._started_at is not None:
                self._status = self._make_status(
                    ConnectionReadinessStage.ACTION_REQUIRED,
                    "connection.transport_unknown", now,
                )
            return self._status

        if self._failure_requires_absence:
            self._status = self._make_status(
                ConnectionReadinessStage.ACTION_REQUIRED,
                "connection.verified_absence_required",
                now,
            )
            return self._status

        if observation.transport_identity != self._transport_identity:
            self._transport_identity = observation.transport_identity
            self._g1_identity = ""
            self._started_at = now
            self._readiness_established = False
            self._last_sample_id = ""
            self._reset_stability()

        assert self._started_at is not None
        age = max(0.0, now - self._started_at)
        if not self._readiness_established and age >= WINDOW_TIMEOUT_SECONDS:
            # One late first enumeration may open a fresh readiness window.
            # Bind its identity immediately so repeated events/failed settling
            # cannot renew the deadline or re-arm the transition coordinator.
            if (
                self._status.stage is ConnectionReadinessStage.TIMED_OUT
                and not self._g1_identity
                and observation.pci_complete
                and observation.g1_identity
                and observation.sample_id != self._last_sample_id
            ):
                self._g1_identity = observation.g1_identity
                self._started_at = now
                self._last_sample_id = observation.sample_id
                self._reset_stability()
                self._status = self._make_status(
                    ConnectionReadinessStage.STABILIZING,
                    "connection.late_enumeration_detected", now,
                )
                return self._status
            self._reset_stability()
            self._status = self._make_status(
                ConnectionReadinessStage.TIMED_OUT, "connection.readiness_timed_out", now
            )
            return self._status

        if observation.sample_id == self._last_sample_id:
            return self._status
        self._last_sample_id = observation.sample_id

        if not observation.pci_complete or not observation.g1_identity:
            self._reset_stability()
            stage = (
                ConnectionReadinessStage.TRANSPORT_DETECTED
                if age == 0.0
                else ConnectionReadinessStage.WAITING_FOR_PCI
            )
            self._status = self._make_status(stage, "connection.waiting_for_pci", now)
            return self._status

        if self._g1_identity and observation.g1_identity != self._g1_identity:
            self._reset_stability()
            self._readiness_established = False
            self._started_at = now
        self._g1_identity = observation.g1_identity

        topology_ready = observation.driver_ready and observation.link_up
        self._topology_samples = self._topology_samples + 1 if topology_ready else 0
        self._hdmi_samples = self._hdmi_samples + 1 if observation.hdmi_ready else 0
        self._audio_samples = self._audio_samples + 1 if observation.audio_ready else 0

        # The initial readiness deadline excludes waiting for the player to
        # finish a game or acknowledge a result. Every later sample still gates
        # action on fresh topology, peripherals, session, and idle game state.
        if (
            self._topology_samples >= TOPOLOGY_STABILITY_SAMPLES
            and self._hdmi_samples >= PERIPHERAL_STABILITY_SAMPLES
            and self._audio_samples >= PERIPHERAL_STABILITY_SAMPLES
            and observation.session_ready
        ):
            self._readiness_established = True

        if not observation.driver_ready:
            self._status = self._make_status(
                ConnectionReadinessStage.WAITING_FOR_DRIVER, "connection.waiting_for_driver", now
            )
        elif not observation.link_up:
            self._status = self._make_status(
                ConnectionReadinessStage.WAITING_FOR_LINK, "connection.waiting_for_link", now
            )
        elif not observation.hdmi_ready:
            self._status = self._make_status(
                ConnectionReadinessStage.WAITING_FOR_HDMI, "connection.waiting_for_hdmi", now
            )
        elif not observation.audio_ready:
            self._status = self._make_status(
                ConnectionReadinessStage.WAITING_FOR_AUDIO, "connection.waiting_for_audio", now
            )
        elif not observation.session_ready:
            self._status = self._make_status(
                ConnectionReadinessStage.WAITING_FOR_SESSION, "connection.waiting_for_session", now
            )
        elif observation.game_state is GameState.UNKNOWN:
            self._status = self._make_status(
                ConnectionReadinessStage.ACTION_REQUIRED, "connection.game_state_unknown", now
            )
        elif observation.game_state is GameState.RUNNING:
            self._status = self._make_status(
                ConnectionReadinessStage.GAME_RUNNING, "connection.game_running", now
            )
        elif (
            self._topology_samples >= TOPOLOGY_STABILITY_SAMPLES
            and self._hdmi_samples >= PERIPHERAL_STABILITY_SAMPLES
            and self._audio_samples >= PERIPHERAL_STABILITY_SAMPLES
        ):
            self._status = self._make_status(
                ConnectionReadinessStage.READY_IDLE, "connection.ready_idle", now
            )
        else:
            self._status = self._make_status(
                ConnectionReadinessStage.STABILIZING, "connection.stabilizing", now
            )
        return self._status

    def _reset_window(self) -> None:
        self._transport_identity = ""
        self._g1_identity = ""
        self._started_at = None
        self._readiness_established = False
        self._last_sample_id = ""
        self._reset_stability()

    def _reset_stability(self) -> None:
        self._topology_samples = 0
        self._hdmi_samples = 0
        self._audio_samples = 0

    def _make_status(
        self, stage: ConnectionReadinessStage, code: str, now: float
    ) -> ConnectionReadinessStatus:
        age = 0.0 if self._started_at is None else max(0.0, now - self._started_at)
        return ConnectionReadinessStatus(
            stage=stage,
            code=code,
            poll_after_ms=poll_after_ms(age, self._started_at is not None),
            window_age_ms=round(age * 1000),
            topology_samples=self._topology_samples,
            hdmi_samples=self._hdmi_samples,
            audio_samples=self._audio_samples,
        )


def poll_after_ms(window_age_seconds: float, active: bool = True) -> int:
    """Return the deterministic adaptive cadence for a window age."""
    if not active:
        return 5_000
    if window_age_seconds < 10.0:
        return 500
    if window_age_seconds < 30.0:
        return 1_000
    return 5_000
