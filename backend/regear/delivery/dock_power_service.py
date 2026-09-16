"""Backend-owned original power request and verified power continuation.

Create the request before claiming/releasing a dock, then bind it durably after
claim and before teardown. This module never tears down or reauthorizes hardware.
Sleep continuation requires the actual handoff for that exact original request.
The production entry point remains separate from this delivery mechanism.
"""
from dataclasses import dataclass
import math
import re
import time
import uuid

from regear.application.dock_power import DockPowerCoordinator, DockPowerResult


def dock_power_capabilities():
    """Describe this build without observing a dock or approving an action.

    Implementation availability is not live readiness. In particular, a
    physical-disconnect-before-sleep profile is not evidence for sleeping with
    a cable-connected, deauthorized dock. No caller-supplied profile or setting
    can promote this descriptive contract into permission to execute.
    """
    return {
        'schema_version': 1,
        'code': 'dock_power.capabilities',
        'authorizes_action': False,
        'actions': {
            'shutdown': {
                'implementation': 'implemented',
                'live_readiness': 'not_assessed',
                # Offered through the guarded teardown route since the
                # 2026-09-14 maintainer decision; every gate on that route
                # still runs. `dock_power.live_preflight_required` used to be
                # listed here, naming a gate that was never implemented; a
                # contract must not cite a check that does not exist.
                # Hardware completion remains unverified: D5.2 recorded fan
                # and LEDs staying on until a manual power-button hold, and
                # the later clean manual shutdown is user-reported, not an
                # automated continuation result. This payload still
                # authorizes nothing.
                'actionable': True,
                'reason_codes': [
                    'dock_power.shutdown_hardware_unverified',
                ],
            },
            'sleep': {
                'implementation': 'implemented',
                'live_readiness': 'not_assessed',
                # Offered through the guarded teardown route since the
                # 2026-09-15 maintainer decision, on the same footing as
                # shutdown: every gate on the route still runs, the two-lease
                # handoff is what releases sleep protection, and no sleep/wake
                # cycle has been observed on hardware through this route.
                'actionable': True,
                'reason_codes': [
                    'dock_power.sleep_hardware_unverified',
                ],
            },
        },
    }


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
    if (type(ttl_seconds) not in (int, float)
            or not math.isfinite(ttl_seconds) or not 0 < ttl_seconds <= 300):
        raise ValueError('dock_power.invalid_intent')
    now = monotonic()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('dock_power.invalid_intent')
    deadline = now + ttl_seconds
    # Floating-point addition can round a 300-second TTL above the strict
    # limit. Shorten by one representable step rather than relax validation.
    if deadline - now > ttl_seconds:
        deadline = math.nextafter(deadline, -math.inf)
    return DockPowerRequest(uuid.uuid4().hex, action, session, now, deadline)


def continue_dock_power(request, *, runtime, store, portable_verified, power,
                        admission_held, monotonic=time.monotonic, sleep_handoff=None):
    """Consume the exact bound intent once while mutation admission stays held.

    An accepted request is not evidence that the machine has powered off.
    Failed/ambiguous submissions stay consumed and must never be replayed.
    """
    if type(request) is not DockPowerRequest:
        return DockPowerResult('dock_power.invalid_intent')
    if request.action == 'sleep':
        from regear.delivery.dock_sleep_handoff import SleepLeaseHandoff
        if (type(sleep_handoff) is not SleepLeaseHandoff
                or not sleep_handoff.bound_to(request)):
            return DockPowerResult('dock_power.sleep_handoff_unavailable')
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
                sleep_handoff.submit(action) if action == 'sleep'
                else power.request_poweroff().requested is True),
            sleep_supported=request.action == 'sleep',
            admission_held=admission_held, monotonic=monotonic)
        return coordinator.execute()
    except Exception:
        return DockPowerResult('dock_power.unresolved')
