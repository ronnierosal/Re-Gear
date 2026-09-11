"""Performing the held release, and the promise that the session comes back.

The behaviour worth protecting here is not the happy path. It is that every
way out of `recover` -- a stop that failed, a link that never came, an
observation that raised -- still starts the session again, because the
alternative is leaving a player looking at nothing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.link_recovery import LinkRecoveryService  # noqa: E402
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

STOP = UserServiceOperation.STOP_GAMESCOPE_SESSION
START = UserServiceOperation.START_GAMESCOPE_SESSION


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


def service(commands, observations, *, gap=20.0):
    """`observations` is a list of pci_complete readings, consumed in order."""
    clock = Clock()
    remaining = list(observations)

    def observe():
        return remaining.pop(0) if remaining else False

    svc = LinkRecoveryService(
        commands, observe, now=clock.now, sleep=clock.sleep, gap_seconds=gap
    )
    return svc, clock


class TheMeasuredRecovery(unittest.TestCase):
    def test_link_appearing_in_the_gap_is_a_success_with_its_timing(self):
        commands = FakeCommands()
        # false, false, then the link: 2 polls at 0.5s = 1.0s
        svc, _ = service(commands, [False, False, True])
        outcome = svc.recover(USER)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.trained")
        self.assertAlmostEqual(outcome.seconds, 1.0)
        self.assertTrue(outcome.session_restored)

    def test_it_stops_before_it_starts(self):
        commands = FakeCommands()
        svc, _ = service(commands, [True])
        svc.recover(USER)
        self.assertEqual(commands.calls, [STOP, START])


class TheSessionAlwaysComesBack(unittest.TestCase):
    def test_a_link_that_never_trains_still_restores_the_session(self):
        commands = FakeCommands()
        svc, _ = service(commands, [], gap=2.0)
        outcome = svc.recover(USER)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.link_absent")
        self.assertTrue(outcome.session_restored)
        self.assertIn(START, commands.calls)

    def test_a_failed_stop_still_issues_a_start(self):
        commands = FakeCommands(failing={STOP})
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.stop_failed")
        self.assertEqual(commands.calls, [STOP, START])

    def test_an_observation_that_raises_still_restores_the_session(self):
        """The `finally` promise. Losing the eGPU beats a black screen."""
        commands = FakeCommands()
        clock = Clock()

        def observe():
            raise RuntimeError("sysfs read blew up")

        svc = LinkRecoveryService(
            commands, observe, now=clock.now, sleep=clock.sleep
        )
        with self.assertRaises(RuntimeError):
            svc.recover(USER)
        self.assertEqual(commands.calls, [STOP, START])

    def test_a_command_port_that_raises_is_a_failure_not_a_crash(self):
        commands = FakeCommands(raising={STOP})
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.stop_failed")

    def test_a_failed_restore_is_the_most_serious_outcome(self):
        commands = FakeCommands(failing={START})
        svc, _ = service(commands, [True])
        outcome = svc.recover(USER)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "link_recovery.session_restore_failed")
        self.assertFalse(outcome.session_restored)

    def test_a_failed_restore_outranks_a_trained_link(self):
        """Do not report success while the screen is still black."""
        commands = FakeCommands(failing={START})
        svc, _ = service(commands, [True])
        self.assertNotEqual(svc.recover(USER).code, "link_recovery.trained")


class TheGapIsBounded(unittest.TestCase):
    def test_it_gives_up_at_the_deadline_rather_than_waiting_forever(self):
        commands = FakeCommands()
        svc, clock = service(commands, [], gap=3.0)
        svc.recover(USER)
        self.assertLessEqual(clock.t, 3.5)


class TheLatch(unittest.TestCase):
    def test_recovering_spends_the_attachment_s_one_attempt(self):
        svc, _ = service(FakeCommands(), [True])
        self.assertFalse(svc.attempted)
        svc.recover(USER)
        self.assertTrue(svc.attempted)

    def test_a_failed_attempt_is_still_spent(self):
        svc, _ = service(FakeCommands(failing={STOP}), [])
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
