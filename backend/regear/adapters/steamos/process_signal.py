"""Exact-instance Linux signal adapter for approved process release."""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from pathlib import Path

from ...domain.process_release import ProcessReleaseTarget
from ...ports.process_signal import (
    ProcessSignalAction,
    ProcessSignalResult,
)


PidfdOpen = Callable[[int, int], int]
PidfdSendSignal = Callable[[int, int, object | None, int], None]


def _read_process_start_time(pid: int) -> str:
    value = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    closing = value.rfind(")")
    if closing < 0:
        raise ValueError("process stat is malformed")
    fields = value[closing + 1 :].split()
    if len(fields) <= 19 or not fields[19].isdigit():
        raise ValueError("process start time is unavailable")
    return fields[19]


class PosixProcessSignalAdapter:
    """Signal one verified process instance through a Linux pidfd.

    The pidfd is opened before the process start time is checked. This binds the
    eventual signal to the kernel process object while the start-time check
    proves it is the exact instance captured by the approval. There is no
    numeric-PID fallback because PID reuse would weaken the mutation boundary.
    """

    def __init__(
        self,
        *,
        pidfd_open: PidfdOpen | None = getattr(os, "pidfd_open", None),
        pidfd_send_signal: PidfdSendSignal | None = getattr(
            signal, "pidfd_send_signal", None
        ),
        close: Callable[[int], None] = os.close,
        read_start_time: Callable[[int], str] = _read_process_start_time,
        platform_name: str = os.name,
    ) -> None:
        self._pidfd_open = pidfd_open
        self._pidfd_send_signal = pidfd_send_signal
        self._close = close
        self._read_start_time = read_start_time
        self._platform_name = platform_name

    def capability_code(self) -> str:
        if self._platform_name != "posix":
            return "signal.platform_unsupported"
        if self._pidfd_open is None or self._pidfd_send_signal is None:
            return "signal.pidfd_unsupported"
        return ""

    def signal(
        self, target: ProcessReleaseTarget, action: ProcessSignalAction
    ) -> ProcessSignalResult:
        capability_code = self.capability_code()
        if capability_code:
            return ProcessSignalResult(False, capability_code)
        signal_number = {
            ProcessSignalAction.GRACEFUL_TERMINATE: int(
                getattr(signal, "SIGTERM", 15)
            ),
            ProcessSignalAction.FORCE_TERMINATE: int(
                getattr(signal, "SIGKILL", 9)
            ),
        }[action]
        try:
            descriptor = self._pidfd_open(target.pid, 0)
        except ProcessLookupError:
            return ProcessSignalResult(True, "signal.process_absent")
        except PermissionError:
            return ProcessSignalResult(False, "signal.permission_denied")
        except OSError:
            return ProcessSignalResult(False, "signal.pidfd_open_failed")
        try:
            try:
                start_time = self._read_start_time(target.pid)
            except FileNotFoundError:
                return ProcessSignalResult(True, "signal.process_absent")
            except (OSError, ValueError):
                return ProcessSignalResult(False, "signal.identity_unavailable")
            if start_time != target.process_start_time:
                return ProcessSignalResult(False, "signal.identity_changed")
            try:
                self._pidfd_send_signal(descriptor, signal_number, None, 0)
            except ProcessLookupError:
                return ProcessSignalResult(True, "signal.process_absent")
            except PermissionError:
                return ProcessSignalResult(False, "signal.permission_denied")
            except OSError:
                return ProcessSignalResult(False, "signal.os_error")
            return ProcessSignalResult(True, "signal.accepted")
        finally:
            try:
                self._close(descriptor)
            except OSError:
                pass
