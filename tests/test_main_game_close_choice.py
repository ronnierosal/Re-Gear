from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.delivery.game_close_preferences import (  # noqa: E402
    GameClosePreferenceStore,
)
from hdm.delivery.live_disconnect_runtime import DisconnectStatus  # noqa: E402
from hdm.delivery.live_disconnect_runtime import (  # noqa: E402
    DisconnectAvailability,
)
from hdm.domain.game_close_consent import (  # noqa: E402
    InterruptIntent,
    RunningGame,
    decide_game_close,
)
from hdm.domain.game_compatibility import GameSaveCapability  # noqa: E402


HADES = RunningGame("1145360", "Hades", GameSaveCapability.UNTESTED)
LOSES_PROGRESS = replace(
    HADES, save_capability=GameSaveCapability.MANUAL_SAVE_REQUIRED
)


class Logger:
    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


def load_main_module():
    decky = types.ModuleType("decky")
    decky.DECKY_VERSION = "test"
    decky.DECKY_USER_HOME = str(ROOT)
    decky.logger = Logger()
    previous = sys.modules.get("decky")
    sys.modules["decky"] = decky
    try:
        spec = importlib.util.spec_from_file_location(
            "hdm_test_main_game_close", ROOT / "main.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("decky", None)
        else:
            sys.modules["decky"] = previous


class FakeRuntime:
    def __init__(self, game: RunningGame | None) -> None:
        self._game = game

    def status(self) -> DisconnectStatus:
        return DisconnectStatus(
            DisconnectAvailability.ATTEMPTABLE,
            "removal_safety.clients_active_or_protected",
            close_prompt=decide_game_close(InterruptIntent.DISCONNECT, self._game),
        )


class RememberChoiceTests(unittest.TestCase):
    """What may be stored is re-derived here, never taken from the caller."""

    def setUp(self) -> None:
        self.module = load_main_module()
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self._patch = patch.object(self.module, "CATALOG_ROOT", self.root)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.plugin = self.module.Plugin()

    def remember(self, game, **kwargs):
        with patch.object(
            self.module.Plugin,
            "_live_disconnect_runtime",
            lambda _self: FakeRuntime(game),
        ):
            return asyncio.run(self.plugin.remember_game_close_choice(**kwargs))

    def stored(self):
        return GameClosePreferenceStore(self.root).load(
            "1145360", InterruptIntent.DISCONNECT
        )

    def test_an_answer_about_the_running_game_is_stored(self) -> None:
        result = self.remember(
            HADES, steam_app_id="1145360", skip_confirmation=True, relaunch_after=True
        )

        self.assertIs(result["ok"], True)
        preference = self.stored()
        self.assertIsNotNone(preference)
        self.assertTrue(preference.skip_confirmation)
        self.assertTrue(preference.relaunch_after)
        self.assertIs(preference.intent, InterruptIntent.DISCONNECT)

    def test_an_answer_about_another_game_is_refused(self) -> None:
        # A stale panel must not be able to file consent against whatever game
        # the player happens to be in now.
        result = self.remember(HADES, steam_app_id="220", skip_confirmation=True)

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.preference_game_mismatch")
        self.assertIsNone(
            GameClosePreferenceStore(self.root).load(
                "220", InterruptIntent.DISCONNECT
            )
        )

    def test_skipping_is_refused_for_a_game_known_to_lose_progress(self) -> None:
        result = self.remember(
            LOSES_PROGRESS, steam_app_id="1145360", skip_confirmation=True
        )

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.progress_at_risk")
        self.assertIsNone(self.stored())

    def test_a_relaunch_alone_is_still_allowed_for_such_a_game(self) -> None:
        # Reopening afterwards costs nothing; it is the unattended close that
        # the rule is about.
        result = self.remember(
            LOSES_PROGRESS,
            steam_app_id="1145360",
            skip_confirmation=False,
            relaunch_after=True,
        )

        self.assertIs(result["ok"], True)
        preference = self.stored()
        self.assertFalse(preference.skip_confirmation)
        self.assertTrue(preference.relaunch_after)

    def test_an_answer_with_no_game_running_is_refused(self) -> None:
        result = self.remember(None, steam_app_id="1145360", skip_confirmation=True)

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.identity_unverified")

    def test_an_unnamed_game_cannot_have_an_answer_filed_for_it(self) -> None:
        result = self.remember(
            replace(HADES, identity_exact=False),
            steam_app_id="1145360",
            skip_confirmation=True,
        )

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.identity_unverified")

    def test_a_malformed_app_id_never_reaches_the_store(self) -> None:
        result = asyncio.run(
            self.plugin.remember_game_close_choice(
                steam_app_id="../../etc/passwd", skip_confirmation=True
            )
        )

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.app_id_invalid")

    def test_forgetting_returns_the_game_to_being_asked(self) -> None:
        self.remember(HADES, steam_app_id="1145360", skip_confirmation=True)

        result = asyncio.run(self.plugin.forget_game_close_choice("1145360"))

        self.assertIs(result["ok"], True)
        self.assertIsNone(self.stored())

    def test_forgetting_needs_no_running_game(self) -> None:
        # Forgetting only ever results in the player being asked more often,
        # so it is not guarded the way storing is.
        result = asyncio.run(self.plugin.forget_game_close_choice("1145360"))

        self.assertIs(result["ok"], True)

    def test_forgetting_validates_the_app_id_too(self) -> None:
        result = asyncio.run(self.plugin.forget_game_close_choice("not-an-id"))

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.app_id_invalid")


if __name__ == "__main__":
    unittest.main()
