"""Backend-owned original shutdown request and verified power continuation.

Create the request before claiming/releasing a dock, then bind it durably after
claim and before teardown. This module never tears down or reauthorizes hardware.
Sleep is unavailable until a supported inhibitor and resume profile is verified.
"""
from dataclasses import dataclass
import math
import re
import time
import uuid

from regear.application.dock_power import DockPowerCoordinator, DockPowerResult


@dataclass(frozen=True)
class DockPowerRequest:
    operation: str
    action: str
    session: str
    requested_at: float
    deadline: float

    def __post_init__(self):
        if (type(self.operation) is not str
                or re.fullmatch(r'[0-9a-f]{32}', self.operation) is None
                or type(self.action) is not str
                or self.action not in ('shutdown', 'sleep')
                or type(self.session) is not str or not self.session
                or len(self.session) > 256
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in (self.requested_at, self.deadline))
                or self.requested_at < 0
                or not 0 < self.deadline - self.requested_at <= 300):
            raise ValueError('dock_power.invalid_intent')


def create_power_request(action, session, *, monotonic=time.monotonic,
                         ttl_seconds=300):
    """Generate intent in the backend, before any teardown or session restart."""
    if action == 'sleep':
        raise ValueError('dock_power.sleep_unverified')
    if (type(ttl_seconds) not in (int, float)
            or not math.isfinite(ttl_seconds) or not 0 < ttl_seconds <= 300):
        raise ValueError('dock_power.invalid_intent')
    now = monotonic()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('dock_power.invalid_intent')
    return DockPowerRequest(uuid.uuid4().hex, action, session, now, now + ttl_seconds)


def continue_dock_power(request, *, runtime, store, portable_verified, power,
                        admission_held, monotonic=time.monotonic):
    """Consume the exact bound intent once while mutation admission stays held.

    An accepted request is not evidence that the machine has powered off.
    Failed/ambiguous submissions stay consumed and must never be replayed.
    """
    if type(request) is not DockPowerRequest:
        return DockPowerResult('dock_power.invalid_intent')
    if request.action == 'sleep':
        return DockPowerResult('dock_power.sleep_unverified')
    try:
        binding, generation = runtime.binding.binding, runtime.binding.generation
        coordinator = DockPowerCoordinator(
            operation_id=request.operation, action=request.action,
            requested_at=request.requested_at, deadline=request.deadline,
            verify_down=lambda operation: runtime.verify_power_continuation(
                operation, portable_verified=portable_verified),
            record_intent=lambda operation, action: store.consume(
                operation, binding, generation, action, request.session,
                request.requested_at, request.deadline),
            request_power=lambda action: (
                action == 'shutdown' and power.request_poweroff().requested is True),
            admission_held=admission_held, monotonic=monotonic)
        return coordinator.execute()
    except Exception:
        return DockPowerResult('dock_power.unresolved')
