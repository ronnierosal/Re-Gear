"""Bind an actual sleep guard to one backend sleep request.

This adapter grants no suspend authority and performs no hardware reconnect.
The caller must retain the same controller used by background reconciliation.
"""
from regear.adapters.steamos.sleep_inhibitor import SleepGuardController
from regear.delivery.dock_power_service import DockPowerRequest


class GuardSleepLease:
    def __init__(self, controller: SleepGuardController, request: DockPowerRequest):
        if type(request) is not DockPowerRequest or request.action != 'sleep':
            raise ValueError('dock_power.invalid_sleep_handoff')
        self._controller = controller
        self._request = request
        self._owner = object()

    def prepare(self, request: DockPowerRequest) -> bool:
        return request is self._request and self._controller.prepare_handoff(self._owner)

    def owned(self, request: DockPowerRequest) -> bool:
        return request is self._request and self._controller.handoff_owned(self._owner)

    def active(self) -> bool:
        status = self._controller.status()
        return status.active is True and not status.error

    def release(self, request: DockPowerRequest) -> bool:
        return request is self._request and self._controller.release_handoff(self._owner)

    def reacquire(self, request: DockPowerRequest) -> bool:
        return request is self._request and self._controller.reacquire_handoff(self._owner)

    def finish(self, request: DockPowerRequest) -> bool:
        return request is self._request and self._controller.finish_handoff(self._owner)
