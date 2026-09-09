from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.commands import UserServiceCommandRunner  # noqa: E402
from hdm.adapters.steamos.session_restart import (  # noqa: E402
    APPROVED_RESTARTS,
    SessionUnitRestart,
    await_units_released,
)
from hdm.domain.filter_arm_sequence import (  # noqa: E402
    APPROVED_HOLDER_UNITS,
    SESSION_TARGET,
)
from hdm.ports.presentation_activation import UserServiceOperation  # noqa: E402


UID = 1000
USER = "deck"
AUDIO = "wireplumber.service"
SESSION_MEMBER = "gamescope-session.service"


class Clock:
    def __init__(self) -> None:
        self.value = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.value += seconds


class FakeCommands:
    def __init__(self, *, ok=True) -> None:
        self._ok = ok
        self.calls: list[tuple] = []

    def run(self, operation, *, uid, username):
        self.calls.append((operation, uid, username))
        return SimpleNamespace(ok=self._ok)


def build(holders, *, ok=True, timeout=60.0):
    """A restarter whose holder scan yields each value in turn."""
    remaining = list(holders)
    clock = Clock()
    commands = FakeCommands(ok=ok)

    def observe():
        return tuple(remaining.pop(0) if len(remaining) > 1 else remaining[0])

    restarter = SessionUnitRestart(
        commands=commands,
        uid=UID,
        username=USER,
        observe_holders=observe,
        now=clock.now,
        sleep=clock.sleep,
        timeout_seconds=timeout,
    )
    restarter.commands = commands  # type: ignore[attr-defined]
    restarter.clock = clock  # type: ignore[attr-defined]
    return restarter


class ApprovalTests(unittest.TestCase):
    """The executor's half of the approval, which must agree with the domain."""

    def test_only_units_the_domain_approves_can_be_restarted(self) -> None:
        for unit in APPROVED_RESTARTS:
            if unit == SESSION_TARGET:
                continue
            with self.subTest(unit=unit):
                self.assertIn(unit, APPROVED_HOLDER_UNITS)

    def test_every_approved_unit_maps_to_a_command_the_runner_will_build(
        self,
    ) -> None:
        """An operation with no fixed suffix would raise at execution time."""
        for unit, operation in APPROVED_RESTARTS.items():
            with self.subTest(unit=unit):
                argv = UserServiceCommandRunner.argv(
                    operation, uid=UID, username=USER
                )
                self.assertIn("restart", argv)
                self.assertIn(unit, argv)
                self.assertEqual(argv[-3:], ("--no-block", "restart", unit))

    def test_an_unapproved_unit_is_refused_without_running_anything(self) -> None:
        restarter = build([("init.scope",)])

        self.assertFalse(restarter.restart("init.scope"))
        self.assertEqual(restarter.commands.calls, [])

    def test_the_audio_units_are_the_ones_the_session_target_cannot_reach(
        self,
    ) -> None:
        self.assertEqual(
            APPROVED_RESTARTS["wireplumber.service"],
            UserServiceOperation.RESTART_WIREPLUMBER,
        )
        self.assertEqual(
            APPROVED_RESTARTS[SESSION_TARGET],
            UserServiceOperation.RESTART_GAMESCOPE_SESSION,
        )


class RestartTests(unittest.TestCase):
    def test_a_restart_succeeds_only_when_the_holder_actually_lets_go(self) -> None:
        """systemctl returning success means it was asked, not that it released."""
        restarter = build([(AUDIO,), (AUDIO,), ()])

        self.assertTrue(restarter.restart(AUDIO))
        self.assertEqual(
            restarter.commands.calls,
            [(UserServiceOperation.RESTART_WIREPLUMBER, UID, USER)],
        )

    def test_a_unit_that_restarts_and_keeps_holding_reports_failure(self) -> None:
        restarter = build([(AUDIO,)], timeout=10.0)

        self.assertFalse(restarter.restart(AUDIO))
        self.assertLessEqual(restarter.clock.value, 10.0)

    def test_a_command_that_fails_reports_failure_without_waiting(self) -> None:
        restarter = build([(AUDIO,)], ok=False)

        self.assertFalse(restarter.restart(AUDIO))
        self.assertEqual(restarter.clock.slept, [])

    def test_the_session_target_waits_for_its_members_not_its_own_name(self) -> None:
        """A target has no cgroup, so its own name never appears in a scan."""
        restarter = build([(SESSION_MEMBER,), (SESSION_MEMBER,), ()])

        self.assertTrue(restarter.restart(SESSION_TARGET))
        self.assertEqual(restarter.clock.slept, [2.0])

    def test_a_unit_holding_nothing_passes_without_waiting(self) -> None:
        restarter = build([("steam-launcher.service",)])

        self.assertTrue(restarter.restart(AUDIO))
        self.assertEqual(restarter.clock.slept, [])
        # The command still runs: the plan named it, and restarting a unit that
        # is not currently a holder is harmless.
        self.assertEqual(len(restarter.commands.calls), 1)


class AwaitTests(unittest.TestCase):
    def test_every_named_unit_has_to_let_go(self) -> None:
        clock = Clock()
        scans = [(AUDIO, SESSION_MEMBER), (SESSION_MEMBER,), ()]

        released = await_units_released(
            (AUDIO, SESSION_MEMBER),
            lambda: scans.pop(0) if len(scans) > 1 else scans[0],
            deadline=60.0,
            now=clock.now,
            sleep=clock.sleep,
        )

        self.assertTrue(released)
        self.assertEqual(clock.slept, [2.0, 2.0])

    def test_nothing_to_wait_for_passes_immediately(self) -> None:
        clock = Clock()
        self.assertTrue(
            await_units_released(
                (), lambda: (AUDIO,), deadline=60.0, now=clock.now, sleep=clock.sleep
            )
        )
        self.assertEqual(clock.slept, [])

    def test_the_wait_never_runs_past_the_deadline(self) -> None:
        clock = Clock()

        await_units_released(
            (AUDIO,),
            lambda: (AUDIO,),
            deadline=3.0,
            now=clock.now,
            sleep=clock.sleep,
        )

        self.assertEqual(clock.slept, [2.0, 1.0])


if __name__ == "__main__":
    unittest.main()
