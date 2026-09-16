"""Ordinary suspend dispatch boundary, with no device or real command use."""
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.commands import SystemSuspendCommandRunner  # noqa: E402


class DockSuspendCommandTests(unittest.TestCase):
    def test_construction_and_nonroot_never_dispatch(self):
        with patch("regear.adapters.steamos.commands.subprocess.run") as run:
            runner = SystemSuspendCommandRunner(effective_uid=lambda: 1000)
            run.assert_not_called()
            self.assertEqual(runner.request_suspend().code, "dock_power.root_required")
            run.assert_not_called()

    def test_exact_ordinary_suspend_once_without_inhibitor_bypass(self):
        with patch("regear.adapters.steamos.commands.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0)) as run:
            result = SystemSuspendCommandRunner(effective_uid=lambda: 0).request_suspend()
        self.assertTrue(result.requested)
        self.assertEqual(result.code, "dock_power.suspend_request_accepted_unverified")
        run.assert_called_once_with(
            ("/usr/bin/systemctl", "--no-block", "--no-ask-password",
             "--check-inhibitors=yes", "suspend"),
            capture_output=True, check=False, shell=False, text=False, timeout=5.0,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"})

    def test_an_inhibited_refusal_is_named_without_exposing_output(self):
        # The one refusal with an actionable cause: a block inhibitor was still
        # registered when the request was made. On device a completed disconnect
        # was followed by a sleep that never happened, and every refusal looked
        # the same. The category crosses; the command's output does not.
        with patch("regear.adapters.steamos.commands.subprocess.run",
                   return_value=subprocess.CompletedProcess(
                       [], 1, b"", b"Operation inhibited by \"Handheld Dock Mode\" (block).")):
            result = SystemSuspendCommandRunner(effective_uid=lambda: 0).request_suspend()
        self.assertFalse(result.requested)
        self.assertEqual(result.code, "dock_power.suspend_inhibited")
        self.assertNotIn("Handheld", result.code)
        self.assertNotIn("block", result.code)

    def test_failure_and_uncertain_submission_never_retry_or_expose_output(self):
        cases = [(subprocess.TimeoutExpired("private command", 5), "suspend_timeout"),
                 (OSError("private path"), "suspend_unavailable"),
                 (subprocess.SubprocessError("private output"), "suspend_unavailable"),
                 (subprocess.CompletedProcess([], 1, b"private", b"secret"), "suspend_failed")]
        for outcome, code in cases:
            with self.subTest(code=code), patch(
                    "regear.adapters.steamos.commands.subprocess.run") as run:
                if isinstance(outcome, Exception):
                    run.side_effect = outcome
                else:
                    run.return_value = outcome
                result = SystemSuspendCommandRunner(effective_uid=lambda: 0).request_suspend()
                self.assertFalse(result.requested)
                self.assertEqual(result.code, "dock_power." + code)
                self.assertNotIn("private", repr(result))
                run.assert_called_once()
