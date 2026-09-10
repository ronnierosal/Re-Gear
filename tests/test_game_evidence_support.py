from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.game_evidence_support import (  # noqa: E402
    SupportGameEvidenceService,
)
from regear.application.game_render_activity import (  # noqa: E402
    GameRenderActivityComparison,
)
from regear.delivery.game_evidence_support import (  # noqa: E402
    game_evidence_to_event_details,
)
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_gpu_client import (  # noqa: E402
    GameEgpuClientEvidence,
    GameEgpuClientStatus,
)
from regear.domain.game_render_activity import (  # noqa: E402
    GameRenderActivityEvidence,
    GameRenderActivityStatus,
)
from regear.domain.game_runtime import GameRuntimeKind  # noqa: E402
from regear.domain.game_session import (  # noqa: E402
    ActiveGameIdentity,
    GameSessionObservation,
)
from regear.domain.models import GameState  # noqa: E402


IDENTITY = ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",))


class SessionPort:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def observe(self):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        if self.calls > 1 and self.value.state is GameState.RUNNING:
            return replace(self.value, sample_id="c" * 64)
        return self.value


class EvidencePort:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def observe(self, identity, *, user_uid):
        self.calls.append((identity, user_uid))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def running_session():
    return GameSessionObservation(
        GameState.RUNNING,
        "a" * 64,
        "b" * 64,
        IDENTITY,
    )


def render(status, *, placement=PlacementState.DOCKED_IGPU, count=0):
    known = status is not GameRenderActivityStatus.UNKNOWN
    return GameRenderActivityEvidence(
        status,
        GameRuntimeKind.PROTON if known else GameRuntimeKind.UNKNOWN,
        count,
        f"render_activity.{status.value}",
        "c" * 64 if known else "",
        placement if known else PlacementState.UNKNOWN,
    )


def make_service(
    *,
    session=None,
    clients=None,
    internal=None,
    external=None,
    comparison=None,
    verify_user=lambda uid: True,
):
    sessions = SessionPort(session or running_session())
    client_port = EvidencePort(
        clients
        or GameEgpuClientEvidence(
            GameEgpuClientStatus.ABSENT,
            GameRuntimeKind.PROTON,
            0,
            "game_gpu.egpu_render_client_absent",
        )
    )
    comparison_port = EvidencePort(
        comparison
        or GameRenderActivityComparison(
            internal or render(GameRenderActivityStatus.ACTIVE, count=1),
            external or render(GameRenderActivityStatus.NO_CLIENT),
        )
    )
    service = SupportGameEvidenceService(
        sessions=sessions,
        egpu_clients=client_port,
        render_comparison=comparison_port,
        user_uid=1000,
        verify_user=verify_user,
    )
    return service, sessions, client_port, comparison_port


class SupportGameEvidenceServiceTests(unittest.TestCase):
    def test_exact_running_game_collects_categorical_internal_and_external_evidence(self):
        service, _sessions, clients, comparison = make_service()

        result = service.observe()
        payload = game_evidence_to_event_details(result)

        self.assertTrue(result.identity_exact)
        self.assertEqual(result.internal_render.status, GameRenderActivityStatus.ACTIVE)
        self.assertEqual(result.external_render.status, GameRenderActivityStatus.NO_CLIENT)
        self.assertEqual(len(clients.calls), 1)
        self.assertEqual(len(comparison.calls), 1)
        encoded = json.dumps(payload, sort_keys=True).lower()
        for private in (
            "1234",
            "app-steam",
            "pid",
            "scope",
            "renderd",
            "0000:",
            "stable_id",
            "generation",
        ):
            self.assertNotIn(private, encoded)

    def test_idle_or_unknown_session_skips_all_deep_observers(self):
        idle = GameSessionObservation(GameState.IDLE, "a" * 64, "b" * 64)
        service, _sessions, clients, comparison = make_service(session=idle)

        result = service.observe()

        self.assertEqual(result.game_state, GameState.IDLE)
        self.assertFalse(result.identity_exact)
        self.assertEqual(clients.calls, [])
        self.assertEqual(comparison.calls, [])

    def test_observer_exceptions_fail_closed_without_losing_other_categories(self):
        service, *_ = make_service(
            clients=RuntimeError("private client failure"),
            comparison=RuntimeError("private render failure"),
        )

        result = service.observe()

        self.assertEqual(result.egpu_client_status, GameEgpuClientStatus.UNKNOWN)
        self.assertEqual(result.internal_render.status, GameRenderActivityStatus.UNKNOWN)
        self.assertEqual(result.external_render.status, GameRenderActivityStatus.UNKNOWN)

    def test_gamescope_user_change_discards_all_partial_evidence(self):
        checks = iter((True, False))
        service, *_ = make_service(verify_user=lambda uid: next(checks))

        result = service.observe()

        self.assertFalse(result.identity_exact)
        self.assertEqual(result.egpu_client_reason, "game_evidence.user_changed")
        self.assertEqual(result.internal_render.status, GameRenderActivityStatus.UNKNOWN)
        self.assertEqual(result.external_render.status, GameRenderActivityStatus.UNKNOWN)

    def test_cross_target_placement_change_discards_partial_evidence(self):
        service, *_ = make_service(
            internal=render(
                GameRenderActivityStatus.ACTIVE,
                placement=PlacementState.DOCKED_IGPU,
                count=1,
            ),
            external=render(
                GameRenderActivityStatus.ACTIVE,
                placement=PlacementState.DOCKED_EGPU,
                count=1,
            ),
        )

        result = service.observe()

        self.assertFalse(result.identity_exact)
        self.assertEqual(
            result.egpu_client_reason, "game_evidence.placement_changed"
        )


if __name__ == "__main__":
    unittest.main()
