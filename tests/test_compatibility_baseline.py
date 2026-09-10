from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.compatibility_baseline import (  # noqa: E402
    CompatibilityBaselineCollector,
)
from regear.domain.control_plane import PlacementState  # noqa: E402
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


def running(sample_id="a" * 64):
    return GameSessionObservation(GameState.RUNNING, "b" * 64, sample_id, IDENTITY)


def render(
    status=GameRenderActivityStatus.ACTIVE,
    placement=PlacementState.PORTABLE,
):
    known = status is not GameRenderActivityStatus.UNKNOWN
    return GameRenderActivityEvidence(
        status,
        GameRuntimeKind.PROTON if known else GameRuntimeKind.UNKNOWN,
        1 if status is GameRenderActivityStatus.ACTIVE else 0,
        f"render_activity.{status.value}",
        "c" * 64 if known else "",
        placement if known else PlacementState.UNKNOWN,
    )


class Sessions:
    def __init__(self, *values):
        self._values = iter(values)

    def observe(self):
        value = next(self._values)
        if isinstance(value, Exception):
            raise value
        return value


class Renderer:
    def __init__(self, value):
        self.value = value
        self.identity = None

    def observe(self, identity, *, user_uid):
        self.identity = identity
        self.user_uid = user_uid
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class CompatibilityBaselineCollectorTests(unittest.TestCase):
    def test_exact_active_internal_game_captures_private_baseline(self):
        renderer = Renderer(render())
        result = CompatibilityBaselineCollector(
            sessions=Sessions(running(), running("d" * 64)),
            internal_renderer=renderer,
        ).capture(user_uid=1000)

        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "compatibility.baseline_captured")
        self.assertEqual(result.baseline.steam_app_id, "1234")
        self.assertEqual(result.baseline.render_gpu.value, "internal")
        self.assertEqual(renderer.identity, IDENTITY)

    def test_idle_unknown_or_external_placement_never_records_baseline(self):
        idle = CompatibilityBaselineCollector(
            sessions=Sessions(GameSessionObservation(GameState.IDLE, "a" * 64, "b" * 64)),
            internal_renderer=Renderer(render()),
        ).capture(user_uid=1000)
        unknown = CompatibilityBaselineCollector(
            sessions=Sessions(running(), running("d" * 64)),
            internal_renderer=Renderer(render(GameRenderActivityStatus.UNKNOWN)),
        ).capture(user_uid=1000)
        external = CompatibilityBaselineCollector(
            sessions=Sessions(running(), running("d" * 64)),
            internal_renderer=Renderer(render(placement=PlacementState.DOCKED_EGPU)),
        ).capture(user_uid=1000)

        self.assertFalse(idle.accepted)
        self.assertEqual(unknown.code, "compatibility.baseline_internal_render_unverified")
        self.assertEqual(external.code, "compatibility.baseline_internal_placement_unverified")

    def test_changed_or_unavailable_session_fails_closed_after_sampling(self):
        changed = CompatibilityBaselineCollector(
            sessions=Sessions(running(), replace(running("d" * 64), generation="e" * 64)),
            internal_renderer=Renderer(render()),
        ).capture(user_uid=1000)
        unavailable = CompatibilityBaselineCollector(
            sessions=Sessions(running(), OSError("private")),
            internal_renderer=Renderer(render()),
        ).capture(user_uid=1000)

        self.assertEqual(changed.code, "compatibility.baseline_game_changed")
        self.assertEqual(unavailable.code, "compatibility.baseline_game_changed")


if __name__ == "__main__":
    unittest.main()
