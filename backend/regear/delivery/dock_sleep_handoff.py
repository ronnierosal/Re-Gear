"""Operation-owned sleep lease callback for the existing power coordinator.

This does not create/consume power intent, enable sleep, or implement teardown.
Only operation-aware adapters with reversible reconciliation pause may implement
LeasePort. Login1SleepInhibitor/SleepGuardController alone do not satisfy it.
The production route uses actual request, ownership and observation checks.
Optional legacy capability restrictions can narrow, never grant, that authority.
"""
from dataclasses import dataclass
import math
from threading import Lock
from typing import Callable, Protocol

from regear.delivery.dock_power_service import DockPowerRequest


@dataclass(frozen=True)
class HandoffCapabilities:
    profile: bool = False
    wake_without_reauthorization: bool = False
    thermal: bool = False
    crash_continuity: bool = False

    def verified(self) -> bool:
        return all(value is True for value in (
            self.profile, self.wake_without_reauthorization,
            self.thermal, self.crash_continuity))


class LeasePort(Protocol):
    """All methods bind the exact request and must never reconnect hardware.

    prepare atomically claims this operation and pauses autonomous reconciliation
    WITHOUT releasing protection. owned must verify both owner and pause. release
    keeps the claim/pause. reacquire restores protection under that same claim.
    finish relinquishes the pause/claim only after BOTH protections are verified.
    False/exception can mean partial work; owned/readback must remain usable.
    """
    def prepare(self, request: DockPowerRequest) -> bool: ...
    def owned(self, request: DockPowerRequest) -> bool: ...
    def active(self) -> bool: ...
    def release(self, request: DockPowerRequest) -> bool: ...
    def reacquire(self, request: DockPowerRequest) -> bool: ...
    def finish(self, request: DockPowerRequest) -> bool: ...


@dataclass(frozen=True)
class HandoffStatus:
    code: str = 'dock_power.handoff_not_started'
    submission: str = 'not_attempted'
    protection_verified: bool = False


class SleepLeaseHandoff:
    """One-shot request_power callback; durable once-only guard stays upstream.

    verify_original must bind operation/session/action/deadline AND the exact
    current attachment/generation, complete down evidence and held admission.
    intent_consumed must read durable consumption of that SAME original request.
    A route without a transaction lease can hand off the background guard alone.
    """
    def __init__(self, request: DockPowerRequest, *, background: LeasePort,
                 transaction: LeasePort, verify_original: Callable,
                 intent_consumed: Callable, request_sleep: Callable,
                 session: Callable, cancelled: Callable, monotonic: Callable,
                 capabilities: Callable | None = None):
        if type(request) is not DockPowerRequest or request.action != 'sleep':
            raise ValueError('dock_power.invalid_sleep_handoff')
        if background is transaction:
            raise ValueError('dock_power.distinct_leases_required')
        self._request = request
        self._leases = (background,) if transaction is None else (background, transaction)
        self._verify, self._consumed = verify_original, intent_consumed
        self._submit, self._session = request_sleep, session
        self._cancelled, self._now, self._capabilities = cancelled, monotonic, capabilities
        self._lock = Lock()
        self._attempted = False
        self._prepared: list[LeasePort] = []
        self.status = HandoffStatus()

    def bound_to(self, request: DockPowerRequest) -> bool:
        """Do not substitute another operation when selecting the power callback."""
        return request is self._request

    def _local_guard(self) -> bool:
        request = self._request
        now = self._now()
        capability = self._capabilities() if self._capabilities is not None else None
        return (type(now) in (int, float) and math.isfinite(now)
                and request.requested_at <= now < request.deadline
                and (self._capabilities is None or (
                    type(capability) is HandoffCapabilities and capability.verified()))
                and self._session() == request.session
                and self._cancelled() is False)

    def _guard(self) -> bool:
        return (self._local_guard()
                and self._verify(self._request) is True
                and self._consumed(self._request) is True
                and self._local_guard())

    def _restore(self) -> bool:
        """Best effort on every owned lease even if the other one failed."""
        try:
            same_session = self._session() == self._request.session
        except Exception:
            same_session = False
        if not same_session:
            self.status = HandoffStatus('dock_power.handoff_recovery_required',
                                        self.status.submission)
            return False
        restored, owned = [], []
        # Incomplete prepare does not reduce the set of required protections.
        # Never acquire a lease whose operation ownership was not established.
        for lease in self._leases:
            held = False
            try:
                held = lease.owned(self._request) is True
                restored.append(held
                                and lease.reacquire(self._request) is True
                                and lease.active() is True)
            except Exception:
                restored.append(False)
            owned.append(held)
        safe = all(restored)
        if safe:
            # Never unpause one controller before the other protection is back.
            for lease in self._leases:
                try:
                    if lease.finish(self._request) is not True:
                        safe = False
                except Exception:
                    safe = False
            safe = self._protection_active() and safe
        if not safe:
            # A lease this handoff OWNED and could not get back is one it
            # released for the suspend and left down. Keep the handoff owned
            # so recovery can still finish it, but do not leave the machine
            # unguarded until then: let the ambient reconcile acquire that
            # lease again on its next tick. Only that lease -- one that was
            # never prepared was never released, and one that reacquired is
            # held and paused exactly as intended. A refusal that touched no
            # lease therefore emits nothing here.
            for lease, was_owned, came_back in zip(self._leases, owned, restored):
                if was_owned and not came_back:
                    try:
                        lease.resume_protection(self._request)
                    except Exception:
                        pass
        self.status = HandoffStatus(
            'dock_power.handoff_restored' if safe else 'dock_power.handoff_recovery_required',
            self.status.submission, safe)
        return safe

    def _protection_active(self) -> bool:
        readings = []
        for lease in self._leases:
            try:
                readings.append(lease.active() is True)
            except Exception:
                readings.append(False)
        return all(readings)

    def submit(self, action: str) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._attempted:
                return False
            self._attempted = True
            if action != self._request.action or not self._guard():
                self.status = HandoffStatus('dock_power.handoff_refused')
                return False
            for lease in self._leases:
                self._prepared.append(lease)  # prepare may throw after claiming
                if (lease.prepare(self._request) is not True
                        or lease.owned(self._request) is not True
                        or lease.active() is not True or not self._guard()):
                    self._restore()
                    return False
            for lease in self._leases:
                if (not self._guard()
                        or any(item.owned(self._request) is not True for item in self._leases)
                        or lease.release(self._request) is not True
                        or lease.active() is not False):
                    self._restore()
                    return False
            if (not self._guard()
                    or any(item.owned(self._request) is not True
                           or item.active() is not False for item in self._leases)):
                self._restore()
                return False
            self.status = HandoffStatus('dock_power.handoff_submitting', 'unknown')
            accepted = self._submit(self._request) is True
            self.status = HandoffStatus(
                'dock_power.sleep_requested_unverified' if accepted else 'dock_power.sleep_refused',
                'accepted' if accepted else 'refused')
            if not accepted:
                self._restore()
            # Accepted means submission only. Keep operation pause until restore.
            return accepted
        except Exception:
            self._restore()
            return False
        finally:
            self._lock.release()

    def restore(self) -> bool:
        """Restore after wake/abort without resubmitting or reconnecting.

        Caller must observe wake separately; this method proves only leases.
        Cross-session recovery cannot reuse process-local lease handles.
        """
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._session() != self._request.session:
                self.status = HandoffStatus('dock_power.handoff_recovery_required',
                                            self.status.submission)
                return False
            if self.status.protection_verified:
                safe = self._protection_active()
                self.status = HandoffStatus(
                    'dock_power.handoff_restored' if safe else 'dock_power.handoff_recovery_required',
                    self.status.submission, safe)
                return safe
            return self._restore()
        except Exception:
            self.status = HandoffStatus('dock_power.handoff_recovery_required',
                                        self.status.submission)
            return False
        finally:
            self._lock.release()
