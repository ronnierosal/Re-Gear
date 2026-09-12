"""One original power intent after a verified, owner-bound dock teardown.

The caller retains mutation admission throughout execute. record_intent must
atomically persist a new intent for this operation and refuse an existing one;
that durable contract prevents replay after a process restart. No callback may
reauthorize the dock or implement reconnect-on-resume.
"""
from dataclasses import dataclass
import math
import re
from threading import Lock
import time
from collections.abc import Callable


@dataclass(frozen=True)
class DockPowerResult:
    code: str
    requested: bool = False


class DockPowerCoordinator:
    """Consume a bounded request once; acceptance never proves sleep/poweroff."""

    def __init__(self, *, operation_id: str, action: str,
                 requested_at: float, deadline: float,
                 verify_down: Callable[[str], bool],
                 record_intent: Callable[[str, str], bool],
                 request_power: Callable[[str], bool],
                 admission_held: Callable[[], bool],
                 sleep_supported: bool = False,
                 monotonic: Callable[[], float] = time.monotonic):
        if (type(operation_id) is not str
                or re.fullmatch(r'[0-9a-f]{32}', operation_id) is None
                or type(action) is not str or action not in ('sleep', 'shutdown')
                or type(sleep_supported) is not bool
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in (requested_at, deadline))
                or requested_at < 0 or not 0 < deadline - requested_at <= 300):
            raise ValueError('dock_power.invalid_intent')
        self._operation, self._action = operation_id, action
        self._requested_at, self._deadline = requested_at, deadline
        self._verify, self._record, self._power = verify_down, record_intent, request_power
        self._admission, self._sleep_supported = admission_held, sleep_supported
        self._now = monotonic
        self._lock = Lock()
        self._consumed = False

    def _guard(self):
        now = self._now()
        return (type(now) in (int, float) and math.isfinite(now)
                and self._requested_at <= now < self._deadline
                and self._admission() is True
                and self._verify(self._operation) is True
                and self._admission() is True
                and self._requested_at <= self._now() < self._deadline)

    def execute(self) -> DockPowerResult:
        if not self._lock.acquire(blocking=False):
            return DockPowerResult('dock_power.busy')
        try:
            if self._consumed:
                return DockPowerResult('dock_power.already_consumed')
            self._consumed = True
            if self._action == 'sleep' and self._sleep_supported is not True:
                return DockPowerResult('dock_power.sleep_unverified')
            if not self._guard():
                return DockPowerResult('dock_power.preflight_changed')
            if self._record(self._operation, self._action) is not True:
                return DockPowerResult('dock_power.intent_not_recorded')
            if not self._guard():
                return DockPowerResult('dock_power.preflight_changed')
            if self._power(self._action) is not True:
                return DockPowerResult('dock_power.request_unverified')
            return DockPowerResult('dock_power.request_accepted_unverified', True)
        except Exception:
            # An exception can occur after a successful write/submission. Never
            # retry or substitute another power action based on an absent reply.
            return DockPowerResult('dock_power.unresolved')
        finally:
            self._lock.release()
