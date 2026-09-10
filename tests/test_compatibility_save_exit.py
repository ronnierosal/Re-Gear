from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.application.compatibility_save_exit import (  # noqa: E402
    CompatibilitySaveExitCollector,
)
from hdm.domain.compatibility_test import (  # noqa: E402
    CompatibilityBaseline,
    CompatibilityTestOptions,
    record_compatibility_baseline,
    start_compatibility_test,
)
from hdm.domain.control_plane import PlacementState  # noqa: E402
from hdm.domain.game_compatibility import (  # noqa: E402
    CompatibilityEvidenceKind,
    ObservedRenderGpu,
    SaveTestOutcome,
)
from hdm.domain.game_session import ActiveGameIdentity, GameSessionObservation  # noqa: E402
from hdm.domain.models import GameState  # noqa: E402


IDENTITY = ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",))


def active_session():
    started = start_compatibility_test(
        session_id="compat-save-exit-0001",
        options=CompatibilityTestOptions(test_egpu_handoff=False, test_save_exit=True),
        evidence_kind=CompatibilityEvidenceKind.SIMULATION,
        game_catalog_id="steam-1234",
        host_profile_id="host",
        egpu_profile_id="egpu",
        regear_version="0.2.0",
        steamos_version="20260831",
        user_confirmed=True,
        now_ms=1,
    )
    return record_compatibility_baseline(
        started,
        CompatibilityBaseline(
            "baseline-generation",
            PlacementState.PORTABLE,
            GameState.RUNNING,
            "1234",
            ObservedRenderGpu.INTERNAL,
        ),
        now_ms=2,
    )


def running(*, generation="run-generation", sample="run-sample", identity=IDENTITY):
    return GameSessionObservation(GameState.RUNNING, generation, sample, identity)


def idle(*, generation="idle-generation", sample="idle-sample"):
    return GameSessionObservation(GameState.IDLE, generation, sample)


class Sessions:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class CompatibilitySaveExitCollectorTests(unittest.TestCase):
    def test_exact_player_exit_records_only_graceful_exit_evidence(self):
        collector = CompatibilitySaveExitCollector(
            Sessions(running(), idle())
        )
        session = active_session()

        watch = collector.arm(session)
        captured = collector.capture(session, watch)

        self.assertTrue(captured.accepted)
        self.assertEqual(captured.outcome, SaveTestOutcome.GRACEFUL_EXIT_VERIFIED)
        self.assertEqual(captured.code, "compatibility.save_exit_observed")
        self.assertEqual(len(captured.observation_generation), 64)

    def test_unknown_running_or_same_sample_never_claims_exit(self):
        session = active_session()
        unknown = GameSessionObservation(GameState.UNKNOWN, "unknown", "sample")
        self.assertIsNone(CompatibilitySaveExitCollector(Sessions(unknown)).arm(session))

        watch = CompatibilitySaveExitCollector(Sessions(running())).arm(session)
        for after, code in (
            (running(sample="next-sample"), "compatibility.save_exit_still_running"),
            (idle(generation="run-generation", sample="next-sample"), "compatibility.save_exit_unverified"),
            (idle(sample="run-sample"), "compatibility.save_exit_unverified"),
        ):
            with self.subTest(code=code):
                result = CompatibilitySaveExitCollector(Sessions(after)).capture(session, watch)
                self.assertFalse(result.accepted)
                self.assertEqual(result.code, code)

    def test_different_game_or_invalid_session_fails_closed(self):
        session = active_session()
        watch = CompatibilitySaveExitCollector(Sessions(running())).arm(session)
        other = ActiveGameIdentity("5678", ("app-steam-app5678-test.scope",))
        result = CompatibilitySaveExitCollector(
            Sessions(running(identity=other, sample="next-sample"))
        ).capture(session, watch)
        self.assertEqual(result.code, "compatibility.save_exit_different_game_started")

        no_save = start_compatibility_test(
            session_id="compat-save-exit-0002",
            options=CompatibilityTestOptions(test_egpu_handoff=True, test_save_exit=False),
            evidence_kind=CompatibilityEvidenceKind.SIMULATION,
            game_catalog_id="steam-1234",
            host_profile_id="host",
            egpu_profile_id="egpu",
            regear_version="0.2.0",
            steamos_version="20260831",
            user_confirmed=True,
            now_ms=1,
        )
        self.assertIsNone(CompatibilitySaveExitCollector(Sessions(running())).arm(no_save))


if __name__ == "__main__":
    unittest.main()
