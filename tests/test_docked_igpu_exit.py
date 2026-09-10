from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.docked_igpu_exit import (  # noqa: E402
    DockedIgpuExitStage,
    DockedIgpuGameExitWatcher,
)
from regear.delivery.docked_igpu_exit import arm_result_to_payload  # noqa: E402
from regear.domain.control_plane import PlacementState  # noqa: E402
from regear.domain.game_session import (  # noqa: E402
    ActiveGameIdentity,
    GameSessionObservation,
)
from regear.domain.gamescope_session import GamescopeSessionObservation  # noqa: E402
from regear.domain.models import GameState  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.ports.transition import VersionedObservation  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"
GAME = ActiveGameIdentity("1234", ("app-steam-app1234-test.scope",))
SESSION_A = GamescopeSessionObservation(
    True, "gamescope.session_observed", "a" * 64
)
SESSION_B = GamescopeSessionObservation(
    True, "gamescope.session_observed", "b" * 64
)


def docked_igpu(*, game_state=GameState.RUNNING):
    value = json.loads((FIXTURES / "tv-docked.json").read_text(encoding="utf-8"))
    value["game_state"] = game_state.value
    for gpu in value["gpus"]:
        gpu["selected_for_render"] = gpu["role"] == "internal"
        if gpu["role"] == "external":
            gpu["stable_id"] = "gpd-g1:0123456789abcdef"
    value["gamescope"]["render_gpu_stable_id"] = "internal-gpu"
    value["gamescope"]["render_vendor_device"] = "1002:0000"
    return snapshot_from_dict(value)


def game_running(*, sample):
    return GameSessionObservation(
        GameState.RUNNING, "game-running-generation", sample, GAME
    )


def game_idle(*, sample):
    return GameSessionObservation(
        GameState.IDLE, "game-idle-generation", sample
    )


class Scripted:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        return self.values.pop(0) if self.values else None


class CountingScripted(Scripted):
    def __init__(self, *values):
        super().__init__(*values)
        self.calls = 0

    def observe(self):
        self.calls += 1
        return super().observe()


class Clock:
    def __init__(self, value=100):
        self.value = value

    def now_ms(self):
        return self.value


def watcher(*, snapshots, games, sessions=None, clock=None, ttl_ms=1000):
    return DockedIgpuGameExitWatcher(
        snapshots=Scripted(*snapshots),
        games=Scripted(*games),
        gamescope_sessions=Scripted(
            *(sessions or (SESSION_A,) * 8)
        ),
        clock=clock or Clock(),
        ttl_ms=ttl_ms,
        watch_id_factory=lambda: "docked-igpu-watch-test-1",
    )


class DockedIgpuExitWatcherTests(unittest.TestCase):
    def test_exact_natural_exit_emits_one_non_mutating_promotion_ready_result(self):
        value = watcher(
            snapshots=(
                VersionedObservation("snapshot-running", docked_igpu(), "sample-1"),
                VersionedObservation(
                    "snapshot-idle",
                    docked_igpu(game_state=GameState.IDLE),
                    "sample-2",
                ),
            ),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
                game_idle(sample="game-3"),
                game_idle(sample="game-4"),
            ),
        )
        armed = value.arm()
        ready = value.poll(armed.watch)

        self.assertTrue(armed.accepted)
        self.assertEqual(ready.stage, DockedIgpuExitStage.PROMOTION_READY)
        self.assertEqual(ready.target, PlacementState.DOCKED_EGPU)
        self.assertTrue(ready.terminal)
        self.assertEqual(value.poll(ready), ready)

    def test_partial_order_waits_for_fresh_snapshot_without_guessing(self):
        running_snapshot = VersionedObservation(
            "snapshot-running", docked_igpu(), "sample-1"
        )
        value = watcher(
            snapshots=(running_snapshot, running_snapshot),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
                game_idle(sample="game-3"),
            ),
        )
        watch = value.arm().watch
        pending = value.poll(watch)

        self.assertEqual(pending.stage, DockedIgpuExitStage.WATCHING)
        self.assertEqual(
            pending.reason_code, "docked_igpu.exit_seen_waiting_snapshot"
        )

    def test_different_game_or_changed_placement_cancels_promotion(self):
        other = ActiveGameIdentity(
            "9999", ("app-steam-app9999-other.scope",)
        )
        different = GameSessionObservation(
            GameState.RUNNING, "other-generation", "game-3", other
        )
        value = watcher(
            snapshots=(
                VersionedObservation("snapshot-running", docked_igpu(), "sample-1"),
            ),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
                different,
            ),
        )
        cancelled = value.poll(value.arm().watch)
        self.assertEqual(cancelled.stage, DockedIgpuExitStage.CANCELLED)
        self.assertEqual(cancelled.reason_code, "docked_igpu.different_game_started")

        portable = json.loads(
            (FIXTURES / "connected-internal.json").read_text(encoding="utf-8")
        )
        for gpu in portable["gpus"]:
            if gpu["role"] == "external":
                gpu["stable_id"] = "gpd-g1:0123456789abcdef"
        value = watcher(
            snapshots=(
                VersionedObservation("snapshot-running", docked_igpu(), "sample-1"),
                VersionedObservation(
                    "snapshot-portable",
                    snapshot_from_dict(portable),
                    "sample-2",
                ),
            ),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
                game_idle(sample="game-3"),
            ),
        )
        changed = value.poll(value.arm().watch)
        self.assertEqual(changed.stage, DockedIgpuExitStage.CANCELLED)
        self.assertEqual(changed.reason_code, "docked_igpu.placement_changed")

    def test_expiry_and_unknown_game_fail_closed(self):
        clock = Clock()
        value = watcher(
            snapshots=(
                VersionedObservation("snapshot-running", docked_igpu(), "sample-1"),
            ),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
            ),
            clock=clock,
            ttl_ms=10,
        )
        watch = value.arm().watch
        clock.value = 110
        expired = value.poll(watch)
        self.assertEqual(expired.stage, DockedIgpuExitStage.CANCELLED)
        self.assertEqual(expired.reason_code, "docked_igpu.watch_expired")

    def test_idle_arm_short_circuits_expensive_snapshot_and_session_scans(self):
        snapshots = CountingScripted(
            VersionedObservation("unused", docked_igpu(), "unused")
        )
        games = CountingScripted(game_idle(sample="idle-1"))
        sessions = CountingScripted(SESSION_A)
        value = DockedIgpuGameExitWatcher(
            snapshots=snapshots,
            games=games,
            gamescope_sessions=sessions,
            clock=Clock(),
            watch_id_factory=lambda: "docked-igpu-watch-test-1",
        )

        result = value.arm()

        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "docked_igpu.game_not_running")
        self.assertEqual(games.calls, 1)
        self.assertEqual(snapshots.calls, 0)
        self.assertEqual(sessions.calls, 0)

    def test_gamescope_restart_cancels_exact_watch(self):
        value = watcher(
            snapshots=(
                VersionedObservation("snapshot-running", docked_igpu(), "sample-1"),
            ),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
            ),
            sessions=(SESSION_A, SESSION_A, SESSION_B),
        )

        changed = value.poll(value.arm().watch)

        self.assertEqual(changed.stage, DockedIgpuExitStage.CANCELLED)
        self.assertEqual(changed.reason_code, "docked_igpu.gamescope_changed")

    def test_unverified_gamescope_identity_refuses_to_arm(self):
        unknown = GamescopeSessionObservation(
            False, "gamescope.session_identity_unverified"
        )
        value = watcher(
            snapshots=(
                VersionedObservation("snapshot-running", docked_igpu(), "sample-1"),
            ),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
            ),
            sessions=(unknown, unknown),
        )

        result = value.arm()

        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "docked_igpu.gamescope_identity_unverified")

    def test_public_payload_excludes_game_profiles_and_generations(self):
        value = watcher(
            snapshots=(
                VersionedObservation("snapshot-running", docked_igpu(), "sample-1"),
            ),
            games=(
                game_running(sample="game-1"),
                game_running(sample="game-2"),
            ),
        )
        result = value.arm()
        payload = json.dumps(arm_result_to_payload(result), sort_keys=True)

        self.assertNotIn("1234", payload)
        self.assertNotIn("app-steam", payload)
        self.assertNotIn("asus", payload)
        self.assertNotIn("snapshot-running", payload)
        self.assertNotIn("gpd-g1:", payload)


if __name__ == "__main__":
    unittest.main()
