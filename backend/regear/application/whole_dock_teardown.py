"""Post-GPU USB/tunnel executor; software result never grants unplug clearance."""
from dataclasses import dataclass
from threading import Lock

from ..domain.dock_teardown import (
    DockTeardownState, TeardownApproval, decide_dock_teardown,
)
from ..ports.whole_dock_teardown import DockObservation, WholeDockPort


@dataclass(frozen=True)
class WholeDockResult:
    code: str
    software_down: bool = False
    safe_to_unplug: bool = False


class WholeDockTeardown:
    def __init__(self, port: WholeDockPort):
        self._port = port
        self._lock = Lock()

    @staticmethod
    def _same(first: DockObservation, now: DockObservation) -> bool:
        return bool(first.binding and first.generation) and (
            first.binding == now.binding
            and first.generation == now.generation
            and first.usb.controller_bdf == now.usb.controller_bdf
            and first.tunnel.sysfs_id == now.tunnel.sysfs_id
            and now.topology_complete is True
            and now.idle is True
        )

    @staticmethod
    def _decision(now: DockObservation, approval: TeardownApproval):
        return decide_dock_teardown(
            usb=now.usb, tunnel=now.tunnel,
            gpu_functions_present=now.gpu_functions_present,
            gpu_scan_complete=now.gpu_scan_complete, approval=approval,
        )

    def execute(self, operation: str, approval: TeardownApproval) -> WholeDockResult:
        if not isinstance(operation, str) or not operation.strip():
            return WholeDockResult("dock_teardown.operation_required")
        if not self._lock.acquire(blocking=False):
            return WholeDockResult("dock_teardown.busy")
        try:
            return self._execute(operation, approval)
        except Exception:
            # Never restore/retry a possibly blocked kernel write here. A durable
            # claim remains owned, even if recording the failure itself would fail.
            return WholeDockResult("dock_teardown.unresolved")
        finally:
            self._lock.release()

    def _execute(self, operation: str, approval: TeardownApproval) -> WholeDockResult:
        first = self._port.observe()
        if not self._same(first, first):
            return WholeDockResult("dock_teardown.identity_or_idle_unknown")
        decision = self._decision(first, approval)
        if not decision.permitted:
            # Already-down observations alone carry no proof of this transaction.
            return WholeDockResult(decision.code)
        if not self._port.claim(operation, first):
            return WholeDockResult("dock_teardown.transaction_owned")

        self._port.record(operation, "prepared")
        now = self._port.observe()
        if not self._same(first, now) or not self._decision(now, approval).permitted:
            return WholeDockResult("dock_teardown.preflight_changed")
        if now.usb.present:
            self._port.record(operation, "usb_remove_intent")
            self._port.remove_usb(now)

        now = self._port.observe()
        if (not self._same(first, now) or not now.usb.scan_complete
                or now.usb.present or now.usb.input_devices or now.usb.other_devices):
            return WholeDockResult("dock_teardown.usb_removal_unverified")

        # The previously approved consequences have now disappeared. No new
        # target or consequence is authorized by this narrowed approval.
        remaining = TeardownApproval(first.usb.controller_bdf, first.tunnel.sysfs_id)
        decision = self._decision(now, remaining)
        if decision.state not in (DockTeardownState.PERMITTED, DockTeardownState.ALREADY_DOWN):
            return WholeDockResult(decision.code)
        self._port.record(operation, "usb_removed")
        if now.tunnel.authorized:
            self._port.record(operation, "tunnel_remove_intent")
            # Fresh observation after durable journal I/O, before the final write.
            now = self._port.observe()
            if (not self._same(first, now) or now.usb.present
                    or now.usb.input_devices or now.usb.other_devices
                    or not self._decision(now, remaining).permitted):
                return WholeDockResult("dock_teardown.tunnel_preflight_changed")
            self._port.deauthorize(now)

        after = self._port.observe()
        if (not self._same(first, after) or after.usb.input_devices
                or after.usb.other_devices or self._decision(after, remaining).state
                is not DockTeardownState.ALREADY_DOWN):
            return WholeDockResult("dock_teardown.final_state_unverified")
        self._port.record(operation, "software_down")
        # Automatic docking stays inhibited until a separate verified reconnect.
        return WholeDockResult("dock_teardown.software_down", software_down=True)
