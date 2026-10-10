"""Ordinary suspend dispatch boundary, with no device or real command use."""
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.steamos.commands import SystemSuspendCommandRunner  # noqa: E402


class DockSuspendCommandTests(unittest.TestCase):
    def test_supported_block_refusals_use_production_retry_path(self):
        from tests.test_main_process_delivery import load_main_module
        module = load_main_module(real_dock_gate=True)
        for wording in (
            b"Call failed: Access denied to root due to active block inhibitor",
            b"Call failed: Access denied due to active block inhibitor",
            b"Call failed: Operation denied due to active block inhibitor",
        ):
            with self.subTest(wording=wording):
                plugin = module.Plugin.__new__(module.Plugin)
                runner = SystemSuspendCommandRunner(effective_uid=lambda: 0)
                with patch.object(module, "SystemSuspendCommandRunner", return_value=runner), \
                        patch.object(module.time, "sleep"), patch(
                            "regear.adapters.steamos.commands.subprocess.run",
                            side_effect=[subprocess.CompletedProcess([], 1, b"", wording),
                                         subprocess.CompletedProcess([], 0, b"", b"")]) as run:
                    self.assertTrue(plugin._submit_suspend(None))
                self.assertEqual(run.call_count, 2)
                self.assertEqual(plugin._whole_dock_suspend_result, {
                    "requested": True,
                    "code": "dock_power.suspend_request_accepted_unverified",
                    "attempts": 2,
                })

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
            ("/usr/bin/busctl", "--system", "--allow-interactive-authorization=no",
             "call", "org.freedesktop.login1", "/org/freedesktop/login1",
             "org.freedesktop.login1.Manager", "SuspendWithFlags", "t", "1"),
            capture_output=True, check=False, shell=False, text=False, timeout=5.0,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"})

    def test_an_inhibited_refusal_is_named_without_exposing_output(self):
        # The one refusal with an actionable cause: a block inhibitor was still
        # registered when the request was made. On device a completed disconnect
        # was followed by a sleep that never happened, and every refusal looked
        # the same. The category crosses; the command's output does not.
        with patch("regear.adapters.steamos.commands.subprocess.run",
                   return_value=subprocess.CompletedProcess(
                       [], 1, b"", b"Call failed: Access denied due to active block inhibitor\n")):
            result = SystemSuspendCommandRunner(effective_uid=lambda: 0).request_suspend()
        self.assertFalse(result.requested)
        self.assertEqual(result.code, "dock_power.suspend_inhibited")
        self.assertNotIn("Handheld", result.code)
        self.assertNotIn("block", result.code)

    def test_only_exact_block_refusal_is_retryable(self):
        for stderr in (
            b"User deck is logged in. Please close inhibitors and log out other users.",
            b"Call failed: Access denied",
            b"Call failed: Unknown method SuspendWithFlags",
            b"Call failed: Invalid flags",
            b"Failed to connect to bus: No such file or directory",
            b"Call failed: Access denied due to active block inhibitor; unknown extra error",
        ):
            with self.subTest(stderr=stderr), patch(
                    "regear.adapters.steamos.commands.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 1, b"", stderr)) as run:
                result = SystemSuspendCommandRunner(effective_uid=lambda: 0).request_suspend()
                self.assertFalse(result.requested)
                self.assertEqual(result.code, "dock_power.suspend_failed")
                run.assert_called_once()

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
