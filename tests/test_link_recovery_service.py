"""Performing the bounce, choosing the mechanism, and giving the session back.

Two things are protected here.

**The session always comes back.** Not on the happy path -- on every path. A
disturbance that failed, a link that never came, an observation that raised:
each must still leave a command that starts the session as the last thing
issued, because the alternative is a player looking at nothing. That invariant
is asserted the same way for every strategy, so a new rung cannot quietly opt
out of it.

**The mechanism is chosen, not assumed.** The default is one plain restart. The
stop-and-hold rung is reachable only by asking for it by name, and the desktop
round trip is named but refuses. None of that is a claim about which one works.
"""

from __future__ import annotations

import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.link_recovery import (  # noqa: E402
    DEFAULT_STRATEGY,
    LinkRecoveryService,
    LinkRecoveryStrategy,
    strategy_is_implemented,
)
from regear.domain.models import GameState  # noqa: E402
from regear.ports.presentation_activation import (  # noqa: E402
    GamescopeUserContext,
    UserServiceOperation,
)


USER = GamescopeUserContext(
    username="deck",
    uid=1000,
    gid=1000,
    home=Path("/home/deck"),
    runtime_directory=Path("/run/user/1000"),
    bus_path=Path("/run/user/1000/bus"),
)

RESTART = UserServiceOperation.RESTART_GAMESCOPE_SESSION
STOP = UserServiceOperation.STOP_GAMESCOPE_SESSION
START = UserServiceOperation.START_GAMESCOPE_SESSION

#: Operations that leave the session running. The always-restore promise is
#: "one of these was the last thing issued", which holds however a strategy
#: chooses to keep it.
SESSION_STARTING = frozenset({RESTART, START})

#: The rungs that actually run something, and what each one's disturbance is.
IMPLEMENTED = {
    LinkRecoveryStrategy.SESSION_RESTART: RESTART,
    LinkRecoveryStrategy.SESSION_STOP_START: STOP,
}


class Outcome:
    def __init__(self, ok: bool) -> None:
        self.ok = ok


class FakeCommands:
    """Records the exact operations, in order, and can fail any of them."""

    def __init__(self, failing: set = frozenset(), raising: set = frozenset()):
        self.calls: list[UserServiceOperation] = []
        self._failing = set(failing)
        self._raising = set(raising)

    def run(self, operation, *, uid, username):
        self.calls.append(operation)
        assert uid == 1000 and username == "deck"
        if operation in self._raising:
            raise OSError("systemctl exploded")
        return Outcome(operation not in self._failing)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def service(commands, observations, *, watch=20.0):
    """`observations` is a list of pci_complete readings, consumed in order."""
    clock = Clock()
    remaining = list(observations)

    def observe():
        return remaining.pop(0) if remaining else False

    svc = LinkRecoveryService(
        commands, observe, now=clock.now, sleep=clock.sleep, watch_seconds=watch
    )
    return svc, clock


class SessionRestoredMixin:
    def assert_session_left_running(self, commands):
        """The promise, stated once: the last thing issued starts the session."""
        self.assertTrue(commands.calls, "nothing was issued at all")
        self.assertIn(
            commands.calls[-1],
            SESSION_STARTING,
            f"recovery ended on {commands.calls[-1]}, leaving the session down",
        )


class TheMechanismIsChosen(unittest.TestCase):
    def test_the_default_is_the_plain_restart(self):
        self.assertIs(DEFAULT_STRATEGY, LinkRecoveryStrategy.SESSION_RESTART)

    def test_the_default_bounce_is_one_restart_and_nothing_else(self):
        """Rung 1 adds no operation: no stop, no start, no second command."""
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER)
        self.assertEqual(commands.calls, [RESTART])
        self.assertEqual(outcome.strategy, "session_restart")
        self.assertTrue(outcome.ok)

    def test_the_stop_start_rung_runs_only_when_it_is_asked_for(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        svc.recover(USER, strategy=LinkRecoveryStrategy.SESSION_STOP_START)
        self.assertEqual(commands.calls, [STOP, START])

    def test_a_strategy_may_be_selected_by_its_wire_name(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER, strategy="session_stop_start")
        self.assertEqual(commands.calls, [STOP, START])
        self.assertEqual(outcome.strategy, "session_stop_start")

    def test_every_outcome_names_the_rung_that_produced_it(self):
        """A timing without its rung is not evidence of anything."""
        for strategy in LinkRecoveryStrategy:
            with self.subTest(strategy=strategy):
                svc, _ = service(FakeCommands(), [True])
                self.assertEqual(
                    svc.recover(USER, strategy=strategy).strategy, strategy.value
                )


class TheDesktopRoundTripIsNamedButNotBuilt(unittest.TestCase):
    """The owner's hypothesis stays reachable; implementing it needs authority."""

    def test_it_exists_as_a_strategy(self):
        self.assertIn(
            "desktop_round_trip", {member.value for member in LinkRecoveryStrategy}
        )

    def test_it_reports_itself_as_not_implemented(self):
        self.assertFalse(
            strategy_is_implemented(LinkRecoveryStrategy.DESKTOP_ROUND_TRIP)
        )
        for strategy in IMPLEMENTED:
            self.assertTrue(strategy_is_implemented(strategy))

    def test_selecting_it_refuses_without_touching_the_session(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        outcome = svc.recover(
            USER, strategy=LinkRecoveryStrategy.DESKTOP_ROUND_TRIP
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.strategy_not_implemented")
        self.assertEqual(outcome.strategy, "desktop_round_trip")
        self.assertTrue(outcome.session_restored)
        self.assertEqual(commands.calls, [])

    def test_refusing_does_not_spend_the_attachment_s_attempt(self):
        """Nothing happened, so nothing was used up."""
        svc, _ = service(FakeCommands(), [True])
        svc.recover(USER, strategy=LinkRecoveryStrategy.DESKTOP_ROUND_TRIP)
        self.assertFalse(svc.attempted)


class AnUnknownStrategy(unittest.TestCase):
    def test_it_refuses_rather_than_falling_back_to_the_default(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER, strategy="switch_it_off_and_on")
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.strategy_unknown")
        self.assertEqual(commands.calls, [])
        self.assertFalse(svc.attempted)

    def test_a_value_that_is_not_even_a_name_refuses_rather_than_raising(self):
        """It arrives over an RPC, so it can be any shape at all."""
        for junk in ([], {}, 7, b"session_restart", object()):
            with self.subTest(strategy=type(junk).__name__):
                commands = FakeCommands()
                svc, _ = service(commands, [True])
                outcome = svc.recover(USER, strategy=junk)
                self.assertEqual(outcome.code, "link_recovery.strategy_unknown")
                self.assertEqual(commands.calls, [])


class TheMeasuredRecovery(unittest.TestCase):
    def test_a_link_that_appears_is_a_success_with_its_timing(self):
        for strategy in IMPLEMENTED:
            with self.subTest(strategy=strategy):
                commands = FakeCommands()
                # false, false, then the link: 2 polls at 0.5s = 1.0s
                svc, _ = service(commands, [False, False, True])
                outcome = svc.recover(USER, strategy=strategy)
                self.assertTrue(outcome.ok)
                self.assertEqual(outcome.code, "link_recovery.trained")
                self.assertAlmostEqual(outcome.seconds, 1.0)
                self.assertTrue(outcome.session_restored)

    def test_the_watch_starts_after_the_disturbance_not_before(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        svc.recover(USER)
        self.assertEqual(commands.calls[0], RESTART)


class TheSessionAlwaysComesBack(SessionRestoredMixin, unittest.TestCase):
    def test_a_link_that_never_trains_still_leaves_the_session_running(self):
        for strategy in IMPLEMENTED:
            with self.subTest(strategy=strategy):
                commands = FakeCommands()
                svc, _ = service(commands, [], watch=2.0)
                outcome = svc.recover(USER, strategy=strategy)
                self.assertFalse(outcome.ok)
                self.assertEqual(outcome.code, "link_recovery.link_absent")
                self.assertTrue(outcome.session_restored)
                self.assert_session_left_running(commands)

    def test_a_failed_disturbance_still_leaves_the_session_running(self):
        for strategy, disturbance in IMPLEMENTED.items():
            with self.subTest(strategy=strategy):
                commands = FakeCommands(failing={disturbance})
                svc, _ = service(commands, [True])
                outcome = svc.recover(USER, strategy=strategy)
                self.assertFalse(outcome.ok)
                self.assert_session_left_running(commands)

    def test_an_observation_that_raises_still_leaves_the_session_running(self):
        """The `finally` promise. Losing the eGPU beats a black screen."""
        for strategy in IMPLEMENTED:
            with self.subTest(strategy=strategy):
                commands = FakeCommands()
                clock = Clock()

                def observe():
                    raise RuntimeError("sysfs read blew up")

                svc = LinkRecoveryService(
                    commands, observe, now=clock.now, sleep=clock.sleep
                )
                with self.assertRaises(RuntimeError):
                    svc.recover(USER, strategy=strategy)
                self.assert_session_left_running(commands)

    def test_a_clock_that_raises_still_leaves_the_session_running(self):
        for strategy in IMPLEMENTED:
            with self.subTest(strategy=strategy):
                commands = FakeCommands()

                def now():
                    raise RuntimeError("the clock blew up")

                svc = LinkRecoveryService(
                    commands, lambda: True, now=now, sleep=lambda _s: None
                )
                with self.assertRaises(RuntimeError):
                    svc.recover(USER, strategy=strategy)
                self.assert_session_left_running(commands)

    def test_a_command_port_that_raises_is_a_failure_not_a_crash(self):
        for strategy, disturbance in IMPLEMENTED.items():
            with self.subTest(strategy=strategy):
                commands = FakeCommands(raising={disturbance})
                svc, _ = service(commands, [True])
                outcome = svc.recover(USER, strategy=strategy)
                self.assertFalse(outcome.ok)
                self.assert_session_left_running(commands)

    def test_a_failed_stop_reports_the_stop_and_still_starts(self):
        commands = FakeCommands(failing={STOP})
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER, strategy=LinkRecoveryStrategy.SESSION_STOP_START)
        self.assertEqual(outcome.code, "link_recovery.stop_failed")
        self.assertEqual(commands.calls, [STOP, START])

    def test_a_failed_restart_reports_the_restart_and_retries_it(self):
        """Rung 1's restore is another restart, so it needs no extra operation."""
        commands = FakeCommands(failing={RESTART})
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER, strategy=LinkRecoveryStrategy.SESSION_RESTART)
        self.assertEqual(outcome.code, "link_recovery.restart_failed")
        self.assertEqual(commands.calls, [RESTART, RESTART])
        self.assertFalse(outcome.session_restored)

    def test_a_failed_restore_is_the_most_serious_outcome(self):
        commands = FakeCommands(failing={START})
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER, strategy=LinkRecoveryStrategy.SESSION_STOP_START)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.session_restore_failed")
        self.assertFalse(outcome.session_restored)

    def test_a_failed_restore_outranks_a_trained_link(self):
        """Do not report success while the screen is still black."""
        commands = FakeCommands(failing={START})
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER, strategy=LinkRecoveryStrategy.SESSION_STOP_START)
        self.assertNotEqual(outcome.code, "link_recovery.trained")


class TheWatchIsBounded(unittest.TestCase):
    def test_it_gives_up_at_the_deadline_rather_than_waiting_forever(self):
        for strategy in IMPLEMENTED:
            with self.subTest(strategy=strategy):
                commands = FakeCommands()
                svc, clock = service(commands, [], watch=3.0)
                svc.recover(USER, strategy=strategy)
                self.assertLessEqual(clock.t, 3.5)


class TheLatch(unittest.TestCase):
    def test_two_preassessed_callers_issue_one_restart(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        barrier = Barrier(2)

        def caller():
            self.assertTrue(svc.assess(
                readiness_exhausted=True, transport_present=True,
                pci_complete=False, game_state=GameState.IDLE,
            ).offered)
            barrier.wait(timeout=5)
            return svc.recover(USER).code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: caller(), range(2)))
        self.assertCountEqual(results, [
            "link_recovery.trained", "link_recovery.already_attempted",
        ])
        self.assertEqual(commands.calls, [RESTART])

    def test_transport_loss_does_not_release_an_in_flight_restart(self):
        entered, release = Event(), Event()
        commands = FakeCommands()
        clock = Clock()

        def observe():
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return True

        svc = LinkRecoveryService(commands, observe, now=clock.now, sleep=clock.sleep)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(svc.recover, USER)
            try:
                self.assertTrue(entered.wait(timeout=5))
                svc.observe_transport(False)
                self.assertTrue(svc.attempted)
                self.assertEqual(svc.recover(USER).code, "link_recovery.already_attempted")
                self.assertEqual(commands.calls, [RESTART])
            finally:
                release.set()
            self.assertTrue(first.result(timeout=5).ok)
        self.assertFalse(svc.attempted)

    def test_direct_repeated_call_cannot_bypass_assessment(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        svc.recover(USER)
        self.assertEqual(svc.recover(USER).code, "link_recovery.already_attempted")
        self.assertEqual(commands.calls, [RESTART])

    def test_recovering_spends_the_attachment_s_one_attempt(self):
        svc, _ = service(FakeCommands(), [True])
        self.assertFalse(svc.attempted)
        svc.recover(USER)
        self.assertTrue(svc.attempted)

    def test_a_failed_attempt_is_still_spent(self):
        svc, _ = service(FakeCommands(failing={RESTART}), [])
        svc.recover(USER)
        self.assertTrue(svc.attempted)

    def test_the_egpu_going_away_re_arms_it(self):
        svc, _ = service(FakeCommands(), [True])
        svc.recover(USER)
        svc.observe_transport(False)
        self.assertFalse(svc.attempted)

    def test_the_egpu_staying_put_does_not_re_arm_it(self):
        svc, _ = service(FakeCommands(), [True])
        svc.recover(USER)
        svc.observe_transport(True)
        self.assertTrue(svc.attempted)

    def test_the_latch_belongs_to_the_attachment_not_the_strategy(self):
        """Trying the next rung needs a replug, deliberately."""
        svc, _ = service(FakeCommands(), [True])
        svc.recover(USER, strategy=LinkRecoveryStrategy.SESSION_RESTART)
        facts = dict(
            readiness_exhausted=True,
            transport_present=True,
            pci_complete=False,
            game_state=GameState.IDLE,
        )
        self.assertEqual(
            svc.assess(**facts).code, "link_recovery.already_attempted"
        )

    def test_assess_reflects_the_latch(self):
        svc, _ = service(FakeCommands(), [True])
        facts = dict(
            readiness_exhausted=True,
            transport_present=True,
            pci_complete=False,
            game_state=GameState.IDLE,
        )
        self.assertTrue(svc.assess(**facts).offered)
        svc.recover(USER)
        self.assertEqual(
            svc.assess(**facts).code, "link_recovery.already_attempted"
        )
        svc.observe_transport(False)
        self.assertTrue(svc.assess(**facts).offered)


if __name__ == "__main__":
    unittest.main()
