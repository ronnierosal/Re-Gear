"""Ephemeral opt-in policy for bounded verbose Re-Gear diagnostic events."""

from __future__ import annotations

import threading
import time
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .support_bundle import BoundedEventLog, SupportEvent, sanitize_value


class DiagnosticVerbosity(StrEnum):
    NORMAL = "normal"
    VERBOSE = "verbose"


class DiagnosticLoggingDuration(StrEnum):
    MINUTES_30 = "30_minutes"
    HOUR_1 = "1_hour"
    HOURS_2 = "2_hours"
    UNTIL_REBOOT = "until_reboot"


class DiagnosticLoggingMode(StrEnum):
    OFF = "off"
    TTL = "ttl"
    UNTIL_REBOOT = "until_reboot"


_DURATION_SECONDS = {
    DiagnosticLoggingDuration.MINUTES_30: 30 * 60,
    DiagnosticLoggingDuration.HOUR_1: 60 * 60,
    DiagnosticLoggingDuration.HOURS_2: 2 * 60 * 60,
}


@dataclass(frozen=True, slots=True)
class DiagnosticLoggingStatus:
    enabled: bool
    mode: DiagnosticLoggingMode
    duration: DiagnosticLoggingDuration | None
    remaining_seconds: int | None
    reason_code: str


class DiagnosticLoggingController:
    """Gate verbose events without persisting consent or boot identity."""

    def __init__(
        self,
        event_log: BoundedEventLog,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        boot_session_id: Callable[[], str],
    ) -> None:
        self._events = event_log
        self._monotonic = monotonic
        self._boot_session_id = boot_session_id
        self._enabled_boot = ""
        self._duration: DiagnosticLoggingDuration | None = None
        self._expires_at: float | None = None
        self._reason_code = "diagnostics.verbose_default_off"
        self._lock = threading.Lock()

    def enable(
        self,
        duration: DiagnosticLoggingDuration = DiagnosticLoggingDuration.HOURS_2,
        *,
        user_confirmed: bool,
    ) -> DiagnosticLoggingStatus:
        if not user_confirmed:
            raise ValueError("verbose diagnostics require explicit user confirmation")
        if not isinstance(duration, DiagnosticLoggingDuration):
            raise ValueError("verbose diagnostics duration is invalid")
        with self._lock:
            boot = self._read_boot_session()
            if boot is None:
                raise ValueError("boot session identity is unavailable")
            now = self._read_monotonic()
            self._enabled_boot = boot
            self._duration = duration
            self._expires_at = (
                None
                if duration is DiagnosticLoggingDuration.UNTIL_REBOOT
                else now + _DURATION_SECONDS[duration]
            )
            self._reason_code = "diagnostics.verbose_enabled"
            return self._status_locked(now, boot)

    def disable(self) -> DiagnosticLoggingStatus:
        with self._lock:
            now = self._read_monotonic()
            boot = self._read_boot_session()
            self._disable_locked("diagnostics.verbose_disabled")
            return self._status_locked(now, boot)

    def status(self) -> DiagnosticLoggingStatus:
        now = self._read_monotonic()
        boot = self._read_boot_session()
        with self._lock:
            return self._status_locked(now, boot)

    def append(
        self,
        *,
        verbosity: DiagnosticVerbosity,
        severity: str,
        code: str,
        component: str,
        stage: str,
        details: Mapping[str, Any] | None = None,
    ) -> SupportEvent | None:
        now = self._read_monotonic()
        boot = self._read_boot_session()
        with self._lock:
            status = self._status_locked(now, boot)
            if verbosity is DiagnosticVerbosity.VERBOSE and not status.enabled:
                return None
            return self._events.append(
                severity=severity,
                code=code,
                component=component,
                stage=stage,
                details=sanitize_value(details or {}),
            )

    def snapshot(self) -> tuple[SupportEvent, ...]:
        return self._events.snapshot()

    def _status_locked(
        self, now: float, boot: str | None
    ) -> DiagnosticLoggingStatus:
        if self._duration is not None:
            if boot is None or boot != self._enabled_boot:
                self._disable_locked("diagnostics.verbose_boot_changed")
            elif self._expires_at is not None and now >= self._expires_at:
                self._disable_locked("diagnostics.verbose_expired")
        if self._duration is None:
            return DiagnosticLoggingStatus(
                False,
                DiagnosticLoggingMode.OFF,
                None,
                None,
                self._reason_code,
            )
        if self._expires_at is None:
            return DiagnosticLoggingStatus(
                True,
                DiagnosticLoggingMode.UNTIL_REBOOT,
                self._duration,
                None,
                self._reason_code,
            )
        return DiagnosticLoggingStatus(
            True,
            DiagnosticLoggingMode.TTL,
            self._duration,
            max(0, int(self._expires_at - now)),
            self._reason_code,
        )

    def _disable_locked(self, reason_code: str) -> None:
        self._enabled_boot = ""
        self._duration = None
        self._expires_at = None
        self._reason_code = reason_code

    def _read_monotonic(self) -> float:
        value = self._monotonic()
        if not math.isfinite(value) or value < 0:
            raise ValueError("monotonic clock returned an invalid value")
        return value

    def _read_boot_session(self) -> str | None:
        try:
            value = self._boot_session_id()
        except Exception:
            return None
        if not value or len(value) > 256 or any(character.isspace() for character in value):
            return None
        return value
