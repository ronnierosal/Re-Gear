"""Continue one sleep request, observe the kernel cycle, and restore own leases.

No teardown or reconnect lives here. The caller supplies the selected route's
fresh verification and once-only consumption while retaining mutation admission.
Kernel success is not a claim about display, charging, or enclosure health.
"""
import time

from regear.application.dock_power import DockPowerCoordinator, DockPowerResult
from regear.delivery.dock_sleep_handoff import SleepLeaseHandoff
from regear.delivery.dock_sleep_lease import GuardSleepLease


def run_observed_sleep(request, *, background, transaction, verify, consume,
                       submit, observer, session, cancelled, publish=lambda code: None,
                       monotonic=time.monotonic, wait=time.sleep):
    baseline = observer.read()
    if baseline is None:
        return DockPowerResult('dock_power.sleep_observer_unavailable')
    consumed = False

    def record(operation, action):
        nonlocal consumed
        consumed = (operation == request.operation and action == request.action
                    and consume(request) is True)
        return consumed

    handoff = SleepLeaseHandoff(request,
        background=GuardSleepLease(background, request),
        transaction=GuardSleepLease(transaction, request) if transaction is not None else None,
        verify_original=verify, intent_consumed=lambda r: r is request and consumed,
        request_sleep=submit, session=session, cancelled=cancelled, monotonic=monotonic)
    coordinator = DockPowerCoordinator(operation_id=request.operation, action=request.action,
        requested_at=request.requested_at, deadline=request.deadline,
        verify_down=lambda operation: operation == request.operation and verify(request),
        record_intent=record, request_power=handoff.submit,
        admission_held=lambda: cancelled() is False, sleep_supported=True, monotonic=monotonic)
    outcome = coordinator.execute()
    if not outcome.requested:
        if handoff.status.code == 'dock_power.handoff_recovery_required':
            return DockPowerResult('dock_power.sleep_protection_unverified')
        return outcome
    # A synchronous refusal was already restored by the handoff. After accepted
    # submission, all exits restore controls and never submit another sleep.
    code = 'dock_power.sleep_cycle_unresolved'
    try:
        publish('dock_power.sleep_requested_unverified')
        deadline = monotonic() + 30
        for _ in range(61):
            state = observer.classify(baseline)
            if state == 'success':
                code = 'dock_power.sleep_cycle_observed'
                break
            if state == 'fail':
                code = 'dock_power.sleep_cycle_failed'
                break
            if (state != 'unchanged' or cancelled() is not False
                    or monotonic() >= deadline):
                break
            wait(0.5)
    except Exception:
        code = 'dock_power.sleep_cycle_unresolved'
    finally:
        if handoff.restore() is not True:
            code = 'dock_power.sleep_protection_unverified'
    return DockPowerResult(code, requested=True)
