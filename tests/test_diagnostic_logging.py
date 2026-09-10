from __future__ import annotations

import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.diagnostic_logging import (  # noqa: E402
    DiagnosticLoggingController,
    DiagnosticLoggingDuration,
    DiagnosticLoggingMode,
    DiagnosticVerbosity,
)
from regear.application.support_bundle import BoundedEventLog  # noqa: E402


class DiagnosticLoggingTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.boot = ["boot-session-1"]
        self.log = BoundedEventLog(
            max_events=3,
            clock=lambda: datetime(2026, 8, 31, tzinfo=timezone.utc),
            correlation_id=lambda: "event001",
        )
        self.controller = DiagnosticLoggingController(
            self.log,
            monotonic=lambda: self.now[0],
            boot_session_id=lambda: self.boot[0],
        )

    def append(self, verbosity: DiagnosticVerbosity, code: str):
        return self.controller.append(
            verbosity=verbosity,
            severity="info",
            code=code,
            component="test",
            stage="observe",
        )

    def test_verbose_is_off_by_default_but_normal_events_remain(self):
        self.assertFalse(self.controller.status().enabled)
        self.assertIsNone(self.append(DiagnosticVerbosity.VERBOSE, "test.verbose"))
        self.assertIsNotNone(self.append(DiagnosticVerbosity.NORMAL, "test.normal"))
        self.assertEqual(len(self.controller.snapshot()), 1)

    def test_enable_requires_explicit_confirmation_and_defaults_to_two_hours(self):
        with self.assertRaisesRegex(ValueError, "explicit"):
            self.controller.enable(user_confirmed=False)
        status = self.controller.enable(user_confirmed=True)
        self.assertEqual(status.mode, DiagnosticLoggingMode.TTL)
        self.assertEqual(status.duration, DiagnosticLoggingDuration.HOURS_2)
        self.assertEqual(status.remaining_seconds, 7200)

    def test_ttl_expires_exactly_and_returns_to_normal_logging(self):
        self.controller.enable(
            DiagnosticLoggingDuration.MINUTES_30,
            user_confirmed=True,
        )
        self.now[0] += 1799
        self.assertTrue(self.controller.status().enabled)
        self.now[0] += 1
        status = self.controller.status()
        self.assertFalse(status.enabled)
        self.assertEqual(status.reason_code, "diagnostics.verbose_expired")
        self.assertIsNone(self.append(DiagnosticVerbosity.VERBOSE, "test.verbose"))
        self.assertIsNotNone(self.append(DiagnosticVerbosity.NORMAL, "test.normal"))

    def test_until_reboot_is_cleared_when_boot_identity_changes(self):
        status = self.controller.enable(
            DiagnosticLoggingDuration.UNTIL_REBOOT,
            user_confirmed=True,
        )
        self.assertEqual(status.mode, DiagnosticLoggingMode.UNTIL_REBOOT)
        self.assertIsNone(status.remaining_seconds)
        self.boot[0] = "boot-session-2"
        status = self.controller.status()
        self.assertFalse(status.enabled)
        self.assertEqual(status.reason_code, "diagnostics.verbose_boot_changed")

    def test_unreadable_boot_identity_disables_existing_verbose_session(self):
        self.controller.enable(user_confirmed=True)
        self.boot[0] = ""
        self.assertFalse(self.controller.status().enabled)
        self.assertIsNone(self.append(DiagnosticVerbosity.VERBOSE, "test.verbose"))

    def test_new_controller_does_not_inherit_consent(self):
        self.controller.enable(user_confirmed=True)
        replacement = DiagnosticLoggingController(
            self.log,
            monotonic=lambda: self.now[0],
            boot_session_id=lambda: self.boot[0],
        )
        self.assertFalse(replacement.status().enabled)

    def test_rotation_remains_bounded_during_verbose_session(self):
        self.controller.enable(user_confirmed=True)
        for index in range(5):
            self.append(DiagnosticVerbosity.VERBOSE, f"test.verbose_{index}")
        self.assertEqual(len(self.controller.snapshot()), 3)
        self.assertEqual(self.controller.snapshot()[0].code, "test.verbose_2")

    def test_verbose_details_are_sanitized_before_memory_retention(self):
        self.controller.enable(user_confirmed=True)
        event = self.controller.append(
            verbosity=DiagnosticVerbosity.VERBOSE,
            severity="info",
            code="test.private",
            component="test",
            stage="observe",
            details={
                "path": "/home/deck/private",
                "pid": 1234,
                "message": "C:\\Users\\Private\\secret",
            },
        )
        self.assertIsNotNone(event)
        retained = repr(self.controller.snapshot()[0].details)
        self.assertNotIn("1234", retained)
        self.assertNotIn("/home/deck", retained)
        self.assertNotIn("C:\\Users\\Private", retained)

    def test_invalid_duration_and_clock_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duration"):
            self.controller.enable("forever", user_confirmed=True)  # type: ignore[arg-type]
        broken = DiagnosticLoggingController(
            self.log,
            monotonic=lambda: float("nan"),
            boot_session_id=lambda: self.boot[0],
        )
        with self.assertRaisesRegex(ValueError, "clock"):
            broken.enable(user_confirmed=True)

    def test_later_disable_cannot_be_overtaken_by_delayed_enable(self):
        entered = threading.Event()
        release = threading.Event()
        boot_calls = 0

        def boot_session():
            nonlocal boot_calls
            boot_calls += 1
            if boot_calls == 1:
                entered.set()
                self.assertTrue(release.wait(1))
            return "boot-session-1"

        controller = DiagnosticLoggingController(
            self.log,
            monotonic=lambda: self.now[0],
            boot_session_id=boot_session,
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            enabled = executor.submit(controller.enable, user_confirmed=True)
            self.assertTrue(entered.wait(1))
            disabled = executor.submit(controller.disable)
            self.assertFalse(disabled.done())
            release.set()
            self.assertTrue(enabled.result(timeout=1).enabled)
            self.assertFalse(disabled.result(timeout=1).enabled)

        self.assertFalse(controller.status().enabled)


if __name__ == "__main__":
    unittest.main()
