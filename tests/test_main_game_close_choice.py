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
from hdm.application.live_disconnect import (  # noqa: E402
    LiveDisconnectResult,
    LiveDisconnectStage,
)
from hdm.delivery.relaunch_intent_store import RelaunchIntentStore  # noqa: E402
from hdm.domain.relaunch_intent import RelaunchClock  # noqa: E402


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
            "regear_test_main_game_close", ROOT / "main.py"
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


BOOT = "b" * 64


class DisconnectRuntime:
    """Just enough of the runtime to exercise the delivery around it."""

    def __init__(self, *, disturbed: bool = False) -> None:
        self.disturbed = disturbed
        self.calls: list[bool] = []

    def status(self):
        raise AssertionError("status is not part of this path")

    def execute(self, *, release_display: bool):
        # Real stages, because ok and device_disturbed are derived from them
        # and a fake that sets them directly would test nothing.
        self.calls.append(release_display)
        if self.disturbed:
            return LiveDisconnectResult(
                LiveDisconnectStage.REMOVAL_UNRECOVERABLE,
                "live_disconnect.removal_unrecoverable",
                restored=("0000:08:00.1",),
            )
        return LiveDisconnectResult(
            LiveDisconnectStage.REMOVED,
            "live_disconnect.removed",
            removed=("0000:08:00.1", "0000:08:00.0"),
        )


class PendingRelaunchTests(unittest.TestCase):
    """The panel that asks for a relaunch does not survive to perform it.

    Freeing the eGPU restarts the Steam session, and a running game is exactly
    the case that makes that necessary. So the wish is written down here.
    """

    def setUp(self) -> None:
        self.module = load_main_module()
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        for name, value in (("CATALOG_ROOT", self.root),):
            patcher = patch.object(self.module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        boot = patch.object(self.module, "read_boot_hash", lambda: BOOT)
        boot.start()
        self.addCleanup(boot.stop)
        self.plugin = self.module.Plugin()
        self.runtime = DisconnectRuntime()

    def disconnect(self, **kwargs):
        with patch.object(
            self.module.Plugin,
            "_live_disconnect_runtime",
            lambda _self: self.runtime,
        ):
            return asyncio.run(self.plugin.execute_egpu_disconnect(**kwargs))

    def stored(self):
        return RelaunchIntentStore(self.root).peek()

    def test_a_requested_relaunch_is_written_before_the_removal(self) -> None:
        self.disconnect(release_display=False, relaunch_app_id="1145360")

        intent = self.stored()
        self.assertIsNotNone(intent)
        self.assertEqual(intent.steam_app_id, "1145360")
        self.assertEqual(intent.boot_hash, BOOT)

    def test_no_relaunch_asked_for_writes_nothing(self) -> None:
        self.disconnect(release_display=False)

        self.assertIsNone(self.stored())

    def test_a_malformed_app_id_is_never_written(self) -> None:
        self.disconnect(release_display=False, relaunch_app_id="../../etc")

        self.assertIsNone(self.stored())

    def test_a_disturbed_device_clears_the_wish(self) -> None:
        # A half-detached eGPU needs a person, not a game launching into it.
        self.runtime.disturbed = True

        self.disconnect(release_display=False, relaunch_app_id="1145360")

        self.assertIsNone(self.stored())

    def test_the_game_is_claimed_once_and_only_once(self) -> None:
        self.disconnect(release_display=False, relaunch_app_id="1145360")

        first = asyncio.run(self.plugin.take_pending_relaunch())
        second = asyncio.run(self.plugin.take_pending_relaunch())

        self.assertEqual(first["steam_app_id"], "1145360")
        self.assertEqual(first["code"], "relaunch.approved")
        self.assertEqual(second["steam_app_id"], "")
        self.assertEqual(second["code"], "relaunch.nothing_recorded")

    def test_nothing_pending_reads_as_nothing_rather_than_an_error(self) -> None:
        result = asyncio.run(self.plugin.take_pending_relaunch())

        self.assertEqual(result["steam_app_id"], "")
        self.assertEqual(result["code"], "relaunch.nothing_recorded")

    def test_a_reboot_between_the_wish_and_the_claim_refuses_it(self) -> None:
        self.disconnect(release_display=False, relaunch_app_id="1145360")

        with patch.object(self.module, "read_boot_hash", lambda: "c" * 64):
            result = asyncio.run(self.plugin.take_pending_relaunch())

        self.assertEqual(result["steam_app_id"], "")
        self.assertEqual(result["code"], "relaunch.different_boot")

    def test_a_refused_wish_is_still_consumed(self) -> None:
        # An intent that could not be honoured now is not one to keep offering.
        self.disconnect(release_display=False, relaunch_app_id="1145360")

        with patch.object(self.module, "read_boot_hash", lambda: "c" * 64):
            asyncio.run(self.plugin.take_pending_relaunch())

        self.assertIsNone(self.stored())

    def test_an_unidentifiable_boot_refuses_rather_than_launching(self) -> None:
        self.disconnect(release_display=False, relaunch_app_id="1145360")

        with patch.object(self.module, "read_boot_hash", lambda: ""):
            result = asyncio.run(self.plugin.take_pending_relaunch())

        self.assertEqual(result["steam_app_id"], "")

    def test_a_wish_that_cannot_be_written_does_not_refuse_the_disconnect(
        self,
    ) -> None:
        # It costs a manual relaunch, not the action the player pressed for.
        with patch.object(
            self.module.RelaunchIntentStore,
            "record",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read-only")),
        ):
            result = self.disconnect(
                release_display=False, relaunch_app_id="1145360"
            )

        self.assertIs(result["ok"], True)
        self.assertEqual(self.runtime.calls, [False])


class IntentKeyedChoiceTests(unittest.TestCase):
    """The action is part of the key, not a detail.

    Agreeing that a game may be closed for sleep is not agreeing that it may
    be closed for a disconnect. The two cost the player different things.
    """

    def setUp(self) -> None:
        self.module = load_main_module()
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        patcher = patch.object(self.module, "CATALOG_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.plugin = self.module.Plugin()

    def remember(self, **kwargs):
        with patch.object(
            self.module.Plugin,
            "_live_disconnect_runtime",
            lambda _self: FakeRuntime(HADES),
        ):
            return asyncio.run(self.plugin.remember_game_close_choice(**kwargs))

    def stored(self, intent):
        return GameClosePreferenceStore(self.root).load("1145360", intent)

    def test_a_sleep_answer_is_filed_under_sleep(self) -> None:
        result = self.remember(
            steam_app_id="1145360", intent="sleep", skip_confirmation=True
        )

        self.assertIs(result["ok"], True)
        self.assertEqual(result["intent"], "sleep")
        self.assertIsNotNone(self.stored(InterruptIntent.SLEEP))
        self.assertIsNone(self.stored(InterruptIntent.DISCONNECT))

    def test_an_unknown_action_is_refused_rather_than_defaulted(self) -> None:
        # Filing an answer against the wrong action files an answer the player
        # did not give.
        result = self.remember(
            steam_app_id="1145360", intent="shutdown", skip_confirmation=True
        )

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.intent_invalid")
        self.assertIsNone(self.stored(InterruptIntent.SLEEP))
        self.assertIsNone(self.stored(InterruptIntent.DISCONNECT))

    def test_both_actions_can_be_answered_for_one_game(self) -> None:
        self.remember(steam_app_id="1145360", intent="sleep", skip_confirmation=True)
        self.remember(
            steam_app_id="1145360", intent="disconnect", relaunch_after=True
        )

        sleep = self.stored(InterruptIntent.SLEEP)
        disconnect = self.stored(InterruptIntent.DISCONNECT)
        self.assertTrue(sleep.skip_confirmation)
        self.assertFalse(disconnect.skip_confirmation)
        self.assertTrue(disconnect.relaunch_after)

    def test_forgetting_one_action_leaves_the_other_answered(self) -> None:
        self.remember(steam_app_id="1145360", intent="sleep", skip_confirmation=True)
        self.remember(
            steam_app_id="1145360", intent="disconnect", skip_confirmation=True
        )

        result = asyncio.run(
            self.plugin.forget_game_close_choice("1145360", "sleep")
        )

        self.assertIs(result["ok"], True)
        self.assertIsNone(self.stored(InterruptIntent.SLEEP))
        self.assertIsNotNone(self.stored(InterruptIntent.DISCONNECT))

    def test_forgetting_an_unknown_action_is_refused(self) -> None:
        result = asyncio.run(
            self.plugin.forget_game_close_choice("1145360", "shutdown")
        )

        self.assertIs(result["ok"], False)
        self.assertEqual(result["code"], "game_close.intent_invalid")


class RelaunchClockChoiceTests(unittest.TestCase):
    """A sleep is meant to outlive the suspend; a disconnect is not."""

    def setUp(self) -> None:
        self.module = load_main_module()
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        for name, value in (("CATALOG_ROOT", self.root),):
            patcher = patch.object(self.module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        boot = patch.object(self.module, "read_boot_hash", lambda: BOOT)
        boot.start()
        self.addCleanup(boot.stop)
        self.plugin = self.module.Plugin()
        self.runtime = DisconnectRuntime()

    def disconnect(self, **kwargs):
        with patch.object(
            self.module.Plugin,
            "_live_disconnect_runtime",
            lambda _self: self.runtime,
        ):
            return asyncio.run(self.plugin.execute_egpu_disconnect(**kwargs))

    def stored(self):
        return RelaunchIntentStore(self.root).peek()

    def test_a_disconnect_reopen_is_aged_across_a_suspend(self) -> None:
        self.disconnect(relaunch_app_id="1145360", relaunch_intent="disconnect")

        self.assertIs(self.stored().clock, RelaunchClock.BOOTTIME)

    def test_a_sleep_reopen_is_aged_on_awake_time_only(self) -> None:
        # The player who ticked "reopen afterwards" before sleeping meant when
        # they come back, not within five minutes of pressing sleep.
        self.disconnect(relaunch_app_id="1145360", relaunch_intent="sleep")

        self.assertIs(self.stored().clock, RelaunchClock.MONOTONIC)

    def test_the_default_is_the_stricter_of_the_two(self) -> None:
        self.disconnect(relaunch_app_id="1145360")

        self.assertIs(self.stored().clock, RelaunchClock.BOOTTIME)

    def test_an_unknown_action_records_no_wish_at_all(self) -> None:
        # Rather than guessing which clock ages it, and therefore when a game
        # might start itself.
        result = self.disconnect(
            relaunch_app_id="1145360", relaunch_intent="shutdown"
        )

        self.assertIs(result["ok"], True)
        self.assertIsNone(self.stored())

    def test_a_sleep_reopen_is_claimable_after_a_long_suspend(self) -> None:
        # MONOTONIC does not advance while suspended, so the record survives.
        self.disconnect(relaunch_app_id="1145360", relaunch_intent="sleep")

        result = asyncio.run(self.plugin.take_pending_relaunch())

        self.assertEqual(result["steam_app_id"], "1145360")
        self.assertEqual(result["code"], "relaunch.approved")


if __name__ == "__main__":
    unittest.main()
