from __future__ import annotations

import signal
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.process_signal import PosixProcessSignalAdapter  # noqa: E402
from regear.domain.models import EgpuResourceKind  # noqa: E402
from regear.domain.process_release import ProcessReleaseTarget  # noqa: E402
from regear.ports.process_signal import ProcessSignalAction  # noqa: E402


def target(pid: int = 100) -> ProcessReleaseTarget:
    return ProcessReleaseTarget(
        instance_id="ephemeral-instance",
        pid=pid,
        name="test-client",
        resources=(EgpuResourceKind.DRM_RENDER,),
        process_start_time="12345",
    )


class PosixProcessSignalAdapterTests(unittest.TestCase):
    def test_maps_only_typed_graceful_and_force_actions(self):
        calls: list[tuple[int, int, object | None, int]] = []
        opened: list[tuple[int, int]] = []
        closed: list[int] = []
        adapter = PosixProcessSignalAdapter(
            pidfd_open=lambda pid, flags: opened.append((pid, flags)) or 41,
            pidfd_send_signal=lambda *args: calls.append(args),
            close=closed.append,
            read_start_time=lambda _pid: "12345",
            platform_name="posix",
        )
        graceful = adapter.signal(target(), ProcessSignalAction.GRACEFUL_TERMINATE)
        force = adapter.signal(target(), ProcessSignalAction.FORCE_TERMINATE)
        self.assertEqual(
            calls,
            [
                (41, int(getattr(signal, "SIGTERM", 15)), None, 0),
                (41, int(getattr(signal, "SIGKILL", 9)), None, 0),
            ],
        )
        self.assertEqual(opened, [(100, 0), (100, 0)])
        self.assertEqual(closed, [41, 41])
        self.assertTrue(graceful.accepted)
        self.assertTrue(force.accepted)

    def test_missing_process_is_rescannable_not_a_success_claim(self):
        def missing(_pid, _flags):
            raise ProcessLookupError

        result = PosixProcessSignalAdapter(
            pidfd_open=missing,
            pidfd_send_signal=lambda *_args: None,
            platform_name="posix",
        ).signal(
            target(), ProcessSignalAction.GRACEFUL_TERMINATE
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, "signal.process_absent")

    def test_permission_and_os_errors_are_categorical(self):
        def denied(_pid, _flags):
            raise PermissionError("private detail")

        def failed(_pid, _flags):
            raise OSError("private detail")

        for operation, expected in (
            (denied, "signal.permission_denied"),
            (failed, "signal.pidfd_open_failed"),
        ):
            with self.subTest(expected=expected):
                result = PosixProcessSignalAdapter(
                    pidfd_open=operation,
                    pidfd_send_signal=lambda *_args: None,
                    platform_name="posix",
                ).signal(
                    target(), ProcessSignalAction.GRACEFUL_TERMINATE
                )
                self.assertFalse(result.accepted)
                self.assertEqual(result.code, expected)
                self.assertNotIn("private", result.code)

    def test_non_posix_platform_fails_closed_without_opening_pidfd(self):
        calls = []
        result = PosixProcessSignalAdapter(
            pidfd_open=lambda pid, flags: calls.append((pid, flags)) or 41,
            pidfd_send_signal=lambda *_args: None,
            platform_name="nt",
        ).signal(target(), ProcessSignalAction.GRACEFUL_TERMINATE)
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "signal.platform_unsupported")
        self.assertEqual(calls, [])

    def test_pid_one_empty_resources_and_duplicate_resources_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            target(1)
        with self.assertRaisesRegex(ValueError, "resources"):
            ProcessReleaseTarget("instance", 100, "client", (), "12345")
        with self.assertRaisesRegex(ValueError, "resources"):
            ProcessReleaseTarget(
                "instance",
                100,
                "client",
                (EgpuResourceKind.DRM_RENDER, EgpuResourceKind.DRM_RENDER),
                "12345",
            )

    def test_pidfd_or_exact_start_time_is_required(self):
        unsupported = PosixProcessSignalAdapter(
            pidfd_open=None,
            pidfd_send_signal=None,
            platform_name="posix",
        ).signal(target(), ProcessSignalAction.GRACEFUL_TERMINATE)
        self.assertFalse(unsupported.accepted)
        self.assertEqual(unsupported.code, "signal.pidfd_unsupported")

        calls = []
        changed = PosixProcessSignalAdapter(
            pidfd_open=lambda _pid, _flags: 41,
            pidfd_send_signal=lambda *args: calls.append(args),
            close=lambda _descriptor: None,
            read_start_time=lambda _pid: "99999",
            platform_name="posix",
        ).signal(target(), ProcessSignalAction.GRACEFUL_TERMINATE)
        self.assertFalse(changed.accepted)
        self.assertEqual(changed.code, "signal.identity_changed")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
