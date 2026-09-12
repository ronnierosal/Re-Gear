"""Experimental post-GPU composition; not a player eject entry point.

The trusted orchestrator must retain mutation admission throughout execution.
A binding must have been captured before GPU release. This first runtime only
supports a verified hub-only USB branch, and never grants cable clearance.
"""
import os
from pathlib import Path
import re
import stat
import time
from dataclasses import dataclass
from threading import Lock, get_ident

from ..adapters.steamos.dock_branch import DockBranchDiscovery
from ..adapters.steamos.whole_dock_topology import revalidate_retained, usb_branch_is_hub_only, TopologyRefused
from ..adapters.steamos.whole_dock_writer import WholeDockSysfsWriter
from ..application.whole_dock_teardown import WholeDockTeardown
from ..application.live_disconnect import LiveDisconnectResult, LiveDisconnectStage
from ..domain.dock_teardown import (
    TeardownApproval, TunnelCapability, TunnelEvidence, UsbBranchEvidence,
    WritePermission, decide_dock_teardown,
)
from ..ports.whole_dock_teardown import DockObservation, WholeDockApproval
from .whole_dock_claim import WholeDockClaimStore

PCI_ROOT = Path('/sys/bus/pci/devices')
DEVICES_ROOT = Path('/sys/devices')


@dataclass(frozen=True)
class WholeDockReconnectResult:
    code: str
    software_reconnected: bool = False
    safe_to_unplug: bool = False


def _pci_names():
    names = set()
    for entry in PCI_ROOT.iterdir():
        if len(names) >= 1024 or not re.fullmatch(
                r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', entry.name):
            raise ValueError('dock_teardown.pci_inventory_invalid')
        names.add(entry.name)
    return names


def _authorization(binding):
    path = DEVICES_ROOT.joinpath(*binding.router_target.parts, 'authorized')
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('dock_teardown.authorization_invalid')
    with path.open('r', encoding='ascii') as source:
        value = source.read(129).strip()
    if value not in ('0', '1'):
        raise ValueError('dock_teardown.authorization_unknown')
    return value == '1', os.access(path, os.W_OK, effective_ids=True)


class WholeDockRuntime:
    def __init__(self, binding, store_root, *, idle, admission_held,
                 monotonic=time.monotonic, wait=time.sleep):
        self.binding = binding
        self._idle = idle
        self._admission = admission_held
        self._store = WholeDockClaimStore(store_root)
        self._discovery = DockBranchDiscovery()
        self._writer = WholeDockSysfsWriter()
        self._operation = None
        self._consent = None
        self._continuation = False
        self._continued = False
        self._continuation_lock = Lock()
        self._continuation_thread = None
        self._reconnect_attempted = False
        self._monotonic, self._wait = monotonic, wait

    def _reconnect_guard(self, stage):
        if self._admission() is not True or self._idle() is not True or not self._owned(stage):
            return False
        revalidate_retained(self.binding, gpu_removed=True, usb_removed=True, tunnel_down=True)
        return self._admission() is True and self._idle() is True and self._owned(stage)

    def reconnect_owned(self):
        """One explicit same-instance software reconnect, retaining inhibition."""
        if not self._continuation_lock.acquire(blocking=False):
            return WholeDockReconnectResult('dock_reconnect.busy')
        try:
            if self._reconnect_attempted or not self._reconnect_guard('software_down'):
                return WholeDockReconnectResult('dock_reconnect.refused')
            self._reconnect_attempted = True
            self.record(self._operation, 'reauthorize_intent')
            if not self._reconnect_guard('reauthorize_intent'):
                return WholeDockReconnectResult('dock_reconnect.preflight_changed')
            self._writer.reauthorize(self.binding.router_target,
                lambda: self._reconnect_guard('reauthorize_intent'))
            # Polling is read-only; neither timeouts nor failed observations retry
            # the write. Durable inhibition remains even after software success.
            from ..adapters.steamos.whole_dock_topology import (
                observe_reconnected, ReconnectPending, WholeDockBinding,
            )
            deadline = self._monotonic() + 30.0
            for _ in range(61):
                if self._admission() is not True or self._idle() is not True or not self._owned('reauthorize_intent'):
                    return WholeDockReconnectResult('dock_reconnect.admission_changed')
                try:
                    restored = observe_reconnected(self.binding)
                except ReconnectPending:
                    restored = None
                else:
                    if not isinstance(restored, WholeDockBinding):
                        raise ValueError('dock_reconnect.observation_invalid')
                if isinstance(restored, WholeDockBinding):
                    self.record(self._operation, 'software_reconnected')
                    return WholeDockReconnectResult('dock_reconnect.software_reconnected', True)
                if restored is not None:
                    raise ValueError('dock_reconnect.observation_invalid')
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    break
                self._wait(min(0.5, remaining))
            return WholeDockReconnectResult('dock_reconnect.timeout')
        except Exception:
            return WholeDockReconnectResult('dock_reconnect.unresolved')
        finally:
            self._continuation_lock.release()

    def finish_reconnect(self):
        """Retire only verified software reconnect; no device writes or clearance."""
        if not self._continuation_lock.acquire(blocking=False):
            return False
        try:
            if not self._owned('software_reconnected'):
                return False
            from ..adapters.steamos.whole_dock_topology import observe_reconnected, WholeDockBinding
            def guard():
                # Store retirement holds its own claim lock. Do not call _owned
                # from this callback: the store validates owner while locked.
                if self._admission() is not True or self._idle() is not True:
                    return False
                restored = observe_reconnected(self.binding)
                return (isinstance(restored, WholeDockBinding)
                    and self._admission() is True and self._idle() is True)
            if not guard():
                return False
            receipt = self._store.retire_reconnected(self._operation,
                self.binding.binding, self.binding.generation, guard)
            return type(receipt) is str and bool(re.fullmatch(
                r'completed-whole-dock-[0-9a-f]{32}\.json', receipt))
        except Exception:
            return False
        finally:
            self._continuation_lock.release()

    def begin_before_release(self, operation, approval):
        """Claim once before release. Failure retains any persisted intent."""
        if self._operation is not None or self._admission() is not True:
            raise ValueError('dock_teardown.begin_refused')
        now = self.observe()
        if (type(approval) is not WholeDockApproval
                or approval.binding != now.binding or approval.generation != now.generation
                or set(now.gpu_functions_present) != {self.binding.gpu_bdf, self.binding.audio_bdf}
                or not now.usb.present or now.tunnel.authorized is not True
                or not now.topology_complete or not now.idle):
            raise ValueError('dock_teardown.begin_preflight_refused')
        # The final-step preflight is evaluated with expected future GPU absence;
        # this authorizes no write. Actual absence is mandatory after release.
        decision = decide_dock_teardown(usb=now.usb, tunnel=now.tunnel,
            gpu_functions_present=(), gpu_scan_complete=now.gpu_scan_complete,
            approval=approval.teardown)
        if not decision.permitted or self.observe() != now or self._admission() is not True:
            raise ValueError('dock_teardown.begin_preflight_refused')
        if not self._store.claim(operation, now.binding, now.generation):
            raise ValueError('dock_teardown.transaction_owned')
        self._operation, self._consent = operation, approval
        self.record(operation, 'release_intent')

    def verify_gpu_release(self, result):
        if (self._consent is None or not self._owned('release_intent')
                or self._admission() is not True
                or type(result) is not LiveDisconnectResult
                or result.stage is not LiveDisconnectStage.REMOVED
                or len(result.removed) != 2
                or set(result.removed) != {self.binding.gpu_bdf, self.binding.audio_bdf}
                or result.restored):
            raise ValueError('dock_teardown.gpu_release_unverified')
        now = self.observe()
        if (now.gpu_functions_present or not now.gpu_scan_complete
                or not now.topology_complete or not now.idle
                or not now.usb.present or now.tunnel.authorized is not True):
            raise ValueError('dock_teardown.gpu_release_unverified')
        self.record(self._operation, 'gpu_removed')

    def execute_claimed(self, operation, approval):
        if not self._continuation_lock.acquire(blocking=False):
            raise ValueError('dock_teardown.continuation_busy')
        try:
            return self._execute_claimed(operation, approval)
        finally:
            self._continuation_lock.release()

    def _execute_claimed(self, operation, approval):
        if (self._continued or self._consent is None or approval != self._consent
                or operation != self._operation or not self._owned('gpu_removed')
                or self._admission() is not True):
            raise ValueError('dock_teardown.continuation_refused')
        now = self.observe()
        if (now.gpu_functions_present or not now.gpu_scan_complete
                or not now.topology_complete or not now.idle):
            raise ValueError('dock_teardown.continuation_refused')
        self._continued = True
        self._continuation = True
        self._continuation_thread = get_ident()
        try:
            return self.execute(operation, approval)
        finally:
            self._continuation = False
            self._continuation_thread = None

    def execute(self, operation, approval):
        return WholeDockTeardown(self).execute(operation, approval)

    def verify_power_continuation(self, operation, *, portable_verified):
        """Read-only proof for the same owner's proposed power continuation.

        This does not release inhibitors, authorize sleep, retire the claim, or
        submit power. The caller must retain mutation admission through its
        subsequent durable intent and power request.
        """
        if not self._continuation_lock.acquire(blocking=False):
            return False
        try:
            if (operation != self._operation or not self._owned('software_down')
                    or self._admission() is not True
                    or portable_verified() is not True):
                return False
            now = self.observe()
            return (now.binding == self.binding.binding
                and now.generation == self.binding.generation
                and now.topology_complete is True and now.idle is True
                and now.gpu_scan_complete is True and not now.gpu_functions_present
                and now.usb.present is False and now.usb.scan_complete is True
                and now.usb.storage_scan_complete is True
                and not now.usb.mounted_storage and not now.usb.storage_in_use
                and now.tunnel.authorized is False
                and portable_verified() is True
                and self._admission() is True and self._owned('software_down'))
        except Exception:
            return False
        finally:
            self._continuation_lock.release()

    def observe(self):
        binding = self.binding
        names = _pci_names()
        present = tuple(bdf for bdf in (binding.gpu_bdf, binding.audio_bdf) if bdf in names)
        usb_present = binding.usb_bdf in names
        authorized, writable = _authorization(binding)
        arguments = dict(gpu_removed=not present, usb_removed=not usb_present,
                         tunnel_down=not authorized)
        revalidate_retained(binding, **arguments)
        usb = self._discovery.observe_usb(binding.usb_bdf)
        storage = self._discovery.observe_storage(binding.usb_bdf)
        # Repeat retained inventory after USB/storage collection. Unknown,
        # unexpected disappearance and new endpoints all raise and stop work.
        revalidate_retained(binding, **arguments)
        if usb.present is not usb_present:
            raise ValueError('dock_teardown.usb_inventory_changed')
        hub_only = usb_branch_is_hub_only(binding, usb)
        revalidate_retained(binding, **arguments)
        if not hub_only:
            raise ValueError('dock_teardown.usb_peripherals_or_unknown')
        return DockObservation(binding.binding, binding.generation,
            UsbBranchEvidence(binding.usb_bdf, usb_present, usb.complete,
                tuple(storage.mounts), tuple(use.kind for use in storage.other_uses),
                storage.complete),
            TunnelEvidence(binding.router_id, authorized, TunnelCapability.SUPPORTED,
                WritePermission.WRITABLE if writable else WritePermission.DENIED, True),
            present, True, hub_only and storage.complete is True,
            self._idle() is True and self._admission() is True)

    def claim(self, operation, observation):
        if (self._admission() is not True or not observation.topology_complete
                or not observation.idle or observation.gpu_functions_present
                or not observation.gpu_scan_complete
                or self.observe() != observation):
            return False
        if self._continuation:
            if self._continuation_thread != get_ident():
                return False
            self._continuation = False
            return operation == self._operation and self._owned('gpu_removed')
        if self._operation is not None:
            return False
        if not self._store.claim(operation, observation.binding, observation.generation):
            return False
        self._operation = operation
        return True

    def _owned(self, stage=None):
        claim = self._store.load()
        return (self._operation is not None and claim is not None
            and claim.operation == self._operation
            and claim.binding == self.binding.binding
            and claim.generation == self.binding.generation
            and (stage is None or claim.stage == stage))

    def record(self, operation, stage):
        if (operation != self._operation or not self._owned()
                or self._admission() is not True):
            raise ValueError('dock_teardown.claim_not_owned')
        self._store.record(operation, stage)

    def _guard(self, observation, stage):
        if self._admission() is not True or not self._owned(stage):
            return False
        now = self.observe()
        if now != observation or not now.topology_complete or not now.idle:
            return False
        decision = decide_dock_teardown(usb=now.usb, tunnel=now.tunnel,
            gpu_functions_present=now.gpu_functions_present,
            gpu_scan_complete=now.gpu_scan_complete,
            approval=TeardownApproval(now.usb.controller_bdf, now.tunnel.sysfs_id))
        return decision.permitted and self._admission() is True and self._owned(stage)

    def remove_usb(self, observation):
        self._writer.remove_usb(self.binding.usb_target,
            lambda: self._guard(observation, 'usb_remove_intent'))

    def deauthorize(self, observation):
        self._writer.deauthorize(self.binding.router_target,
            lambda: self._guard(observation, 'tunnel_remove_intent'))
        # The authorized attribute can change before the kernel finishes
        # removing downstream bridges. Only that exact retained-topology
        # observation is pending; never replay the write or suppress a changed
        # identity, unreadable attribute, endpoint, or lost ownership.
        deadline = self._monotonic() + 10.0
        for attempt in range(21):
            if (self._admission() is not True or self._idle() is not True
                    or not self._owned('tunnel_remove_intent')):
                raise ValueError('dock_teardown.settle_admission_changed')
            try:
                self.observe()
                return
            except TopologyRefused as error:
                if (type(error) is not TopologyRefused
                        or error.args != ('dock_topology.pci_branch_remains',)):
                    raise
                remaining = deadline - self._monotonic()
                if remaining <= 0 or attempt == 20:
                    raise ValueError('dock_teardown.tunnel_settle_timeout') from error
                self._wait(min(0.5, remaining))
