"""Read-only evidence collector for a player-initiated graceful game exit.

This collector does not close a game and cannot prove saved progress. It merely
proves that the exact Steam game armed by a Compatibility Test session was later
observed idle through a fresh game-session sample. The result maps only to the
catalog's Graceful Exit Verified outcome, never a save-on-exit or autosave claim.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ..domain.compatibility_test import CompatibilityTestSession, CompatibilityTestStage
from ..domain.game_compatibility import SaveTestOutcome
from ..domain.game_session import ActiveGameIdentity, GameSessionObservation
from ..domain.models import GameState
from ..ports.game_session import GameSessionObservationPort


@dataclass(frozen=True, slots=True)
class CompatibilitySaveExitWatch:
    identity: ActiveGameIdentity
    generation: str
    sample_id: str


@dataclass(frozen=True, slots=True)
class CompatibilitySaveExitCapture:
    accepted: bool
    code: str
    outcome: SaveTestOutcome = SaveTestOutcome.NOT_TESTED
    observation_generation: str = ""

    def __post_init__(self) -> None:
        if self.accepted != bool(self.observation_generation):
            raise ValueError("save-exit capture identity is invalid")
        if self.accepted != (
            self.outcome is SaveTestOutcome.GRACEFUL_EXIT_VERIFIED
        ):
            raise ValueError("save-exit capture outcome is invalid")


class CompatibilitySaveExitCollector:
    """Bracket one player-initiated exit using exact private session identity."""

    def __init__(self, sessions: GameSessionObservationPort) -> None:
        self._sessions = sessions

    def arm(self, session: CompatibilityTestSession) -> CompatibilitySaveExitWatch | None:
        if not self._eligible(session):
            return None
        observed = self._observe()
        if (
            observed is None
            or not observed.exact
            or observed.state is not GameState.RUNNING
            or observed.identity is None
            or observed.identity.steam_app_id != session.baseline.steam_app_id
        ):
            return None
        return CompatibilitySaveExitWatch(
            observed.identity, observed.generation, observed.sample_id
        )

    def capture(
        self, session: CompatibilityTestSession, watch: CompatibilitySaveExitWatch
    ) -> CompatibilitySaveExitCapture:
        if not self._eligible(session):
            return CompatibilitySaveExitCapture(False, "compatibility.save_exit_out_of_order")
        if watch.identity.steam_app_id != session.baseline.steam_app_id:
            return CompatibilitySaveExitCapture(False, "compatibility.save_exit_identity_changed")
        observed = self._observe()
        if observed is None or not observed.exact:
            return CompatibilitySaveExitCapture(False, "compatibility.save_exit_unverified")
        if observed.state is GameState.RUNNING:
            return CompatibilitySaveExitCapture(
                False,
                (
                    "compatibility.save_exit_different_game_started"
                    if observed.identity != watch.identity
                    else "compatibility.save_exit_still_running"
                ),
            )
        if (
            observed.state is not GameState.IDLE
            or observed.generation == watch.generation
            or observed.sample_id == watch.sample_id
        ):
            return CompatibilitySaveExitCapture(False, "compatibility.save_exit_unverified")
        return CompatibilitySaveExitCapture(
            True,
            "compatibility.save_exit_observed",
            SaveTestOutcome.GRACEFUL_EXIT_VERIFIED,
            self._generation(session, watch, observed),
        )

    @staticmethod
    def _eligible(session: CompatibilityTestSession) -> bool:
        return bool(
            session.stage is CompatibilityTestStage.ACTIVE
            and session.options.test_save_exit
            and session.baseline is not None
            and session.baseline.steam_app_id
        )

    def _observe(self) -> GameSessionObservation | None:
        try:
            return self._sessions.observe()
        except Exception:
            return None

    @staticmethod
    def _generation(
        session: CompatibilityTestSession,
        watch: CompatibilitySaveExitWatch,
        observed: GameSessionObservation,
    ) -> str:
        material = "|".join(
            (
                session.session_id,
                session.baseline.generation,
                watch.identity.steam_app_id,
                *watch.identity.scopes,
                watch.generation,
                watch.sample_id,
                observed.generation,
                observed.sample_id,
            )
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()
