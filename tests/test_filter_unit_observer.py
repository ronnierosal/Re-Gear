from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.regear.adapters.steamos.filter_unit_observer import FilterUnitObserver
from backend.regear.adapters.steamos.commands import UserServiceCommandRunner
from backend.regear.ports.presentation_activation import UserServiceOperation


class FilterUnitObserverTests(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(uid=1000, username="deck")
        self.output = "MainPID=123\nInvocationID=" + "a" * 32 + "\nActiveState=activating\nControlGroup=/fixture"
        self.runner = Mock()
        self.runner.run.return_value = SimpleNamespace(ok=True, output=self.output)
        self.observer = FilterUnitObserver(self.user, deadline=15, commands=self.runner, clock=lambda: 10)

    def test_exact_fixed_service_operations_only(self):
        for unit, operation in self.observer.OPERATIONS.items():
            value = self.observer(unit)
            self.assertEqual(value["MainPID"], "123")
            self.runner.run.assert_called_with(operation, uid=1000, username="deck", timeout_seconds=1.0)
        count = self.runner.run.call_count
        for unit in ("foreign.service", "gamescope-session.service; reboot", None):
            with self.assertRaises(ValueError): self.observer(unit)
        self.assertEqual(self.runner.run.call_count, count)

    def test_duplicate_missing_unknown_nonascii_and_failed_outputs_rejected(self):
        for output in (self.output + "\nMainPID=456", self.output.split("\n", 1)[1],
                       self.output + "\nExtra=1", "x" * 2049, self.output + "\u00e9", ""):
            self.runner.run.return_value = SimpleNamespace(ok=True, output=output)
            with self.assertRaises(ValueError): self.observer("gamescope-session.service")
        self.runner.run.return_value = SimpleNamespace(ok=False, output=self.output)
        with self.assertRaises(ValueError): self.observer("gamescope-session.service")

    def test_expired_observation_does_not_run_and_late_result_is_rejected(self):
        self.observer.deadline = 10
        with self.assertRaises(ValueError): self.observer("gamescope-session.service")
        self.runner.run.assert_not_called()
        self.observer.deadline = 15
        self.observer.clock = Mock(side_effect=[14.8, 15])
        with self.assertRaises(ValueError): self.observer("gamescope-session.service")
        self.assertAlmostEqual(self.runner.run.call_args.kwargs["timeout_seconds"], 0.2)

    def test_real_command_shape_is_read_only_and_bounded(self):
        runner = UserServiceCommandRunner(effective_uid=lambda: 0)
        with patch("backend.regear.adapters.steamos.commands.subprocess.run",
                   return_value=SimpleNamespace(returncode=0, stdout=self.output.encode(), stderr=b"")) as run:
            observer = FilterUnitObserver(self.user, deadline=15, commands=runner, clock=lambda: 10)
            observer("steam-launcher.service")
            argv = run.call_args.args[0]
            self.assertEqual(argv[-7:], ("show", "steam-launcher.service", "--property=MainPID",
                "--property=InvocationID", "--property=ActiveState", "--property=ControlGroup", "--no-pager"))
            self.assertFalse(run.call_args.kwargs["shell"])
            self.assertEqual(run.call_args.kwargs["timeout"], 1)

    def test_runner_invalid_deadline_prevents_subprocess(self):
        runner = UserServiceCommandRunner(effective_uid=lambda: 0)
        with patch("backend.regear.adapters.steamos.commands.subprocess.run") as run:
            for timeout in (True, 0, -1, float("nan"), float("inf")):
                result = runner.run(UserServiceOperation.OBSERVE_FILTER_GAMESCOPE,
                    uid=1000, username="deck", timeout_seconds=timeout)
                self.assertFalse(result.ok)
            run.assert_not_called()
