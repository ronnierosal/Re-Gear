from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.game_session import (  # noqa: E402
    GameScopeSessionObservationAdapter,
    UserBoundGameScopeScanAdapter,
)
from regear.adapters.steamos.game_scopes import GameScopeScan  # noqa: E402
from regear.domain.game_session import ActiveGameIdentity  # noqa: E402
from regear.domain.models import GameState  # noqa: E402


class Discovery:
    def __init__(self, scan):
        self.value = scan

    def scan(self):
        return self.value


class UserDiscovery:
    def __init__(self, scan):
        self.value = scan
        self.calls = []

    def scan(self, user_uid=None):
        self.calls.append(user_uid)
        return self.value


class GameSessionObservationTests(unittest.TestCase):
    def test_user_bound_scan_uses_only_the_backend_resolved_uid(self):
        scan = GameScopeScan(GameState.IDLE)
        discovery = UserDiscovery(scan)
        adapter = UserBoundGameScopeScanAdapter(discovery, 1000)

        self.assertIs(adapter.scan(), scan)
        self.assertEqual(discovery.calls, [1000])
        with self.assertRaisesRegex(ValueError, "user"):
            UserBoundGameScopeScanAdapter(discovery, 0)

    def test_exact_single_appid_scopes_get_semantic_and_sample_identity(self):
        scan = GameScopeScan(
            GameState.RUNNING,
            (
                "app-steam-app1234-one.scope",
                "app-steam-app1234-two.scope",
            ),
            ("1234",),
        )
        adapter = GameScopeSessionObservationAdapter(Discovery(scan))
        first = adapter.observe()
        second = adapter.observe()
        self.assertTrue(first.exact)
        self.assertEqual(first.identity.steam_app_id, "1234")
        self.assertEqual(first.identity.scopes, scan.scopes)
        self.assertEqual(first.generation, second.generation)
        self.assertNotEqual(first.sample_id, second.sample_id)

    def test_ambiguous_or_unparsed_running_scope_is_unknown(self):
        cases = (
            GameScopeScan(
                GameState.RUNNING,
                ("app-steam-app123-one.scope", "app-steam-app456-two.scope"),
                ("123", "456"),
            ),
            GameScopeScan(
                GameState.RUNNING,
                ("app-steam-appfuture.scope",),
                (),
                ("app-steam-appfuture.scope",),
            ),
        )
        for scan in cases:
            with self.subTest(scopes=scan.scopes):
                result = GameScopeSessionObservationAdapter(
                    Discovery(scan)
                ).observe()
                self.assertEqual(result.state, GameState.UNKNOWN)
                self.assertFalse(result.exact)
                self.assertIsNone(result.identity)

    def test_identity_rejects_unbounded_or_non_scope_input(self):
        with self.assertRaisesRegex(ValueError, "scope"):
            ActiveGameIdentity("1234", ("../../private",))
        with self.assertRaisesRegex(ValueError, "AppID"):
            ActiveGameIdentity("0", ("app-steam-app0-test.scope",))

    def test_unbounded_scope_scan_fails_closed_instead_of_escaping(self):
        scan = GameScopeScan(
            GameState.RUNNING,
            tuple(
                f"app-steam-app1234-{index}.scope" for index in range(17)
            ),
            ("1234",),
        )
        result = GameScopeSessionObservationAdapter(Discovery(scan)).observe()
        self.assertEqual(result.state, GameState.UNKNOWN)
        self.assertFalse(result.exact)
        self.assertIsNone(result.identity)


if __name__ == "__main__":
    unittest.main()
