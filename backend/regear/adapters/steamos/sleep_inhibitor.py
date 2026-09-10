"""Crash-safe login1 sleep-inhibitor lease and exact G1 presence checks."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Callable, Protocol

from ...domain.models import EgpuPresence, SleepGuardAction
from ...domain.sleep_policy import decide_sleep_guard
from ...profiles.ally_x import matches_ally_x
from ...profiles.gpd_g1 import match_gpd_g1
from .commands import ManagedProcessStatus, SleepInhibitorProcess
from .drm import DrmDiscovery
from .host import HostDiscovery
from .pci import PciUsb4Discovery


class InhibitorProcess(Protocol):
    def start(self) -> ManagedProcessStatus: ...

    def stop(self) -> ManagedProcessStatus: ...

    def status(self) -> ManagedProcessStatus: ...


@dataclass(frozen=True, slots=True)
class InhibitorLeaseStatus:
    active: bool
    error: str = ""


class G1SleepGuardHardwareDiscovery:
    """Observe only the evidence required to acquire, release, or hold."""

    def __init__(
        self,
        drm: DrmDiscovery | None = None,
        pci_usb4: PciUsb4Discovery | None = None,
        host: HostDiscovery | None = None,
    ) -> None:
        self._drm = drm or DrmDiscovery()
        self._pci_usb4 = pci_usb4 or PciUsb4Discovery()
        self._host = host or HostDiscovery()

    def observe_presence(self) -> EgpuPresence:
        host = self._host.scan()
        cards = self._drm.scan()
        if not matches_ally_x(host) or not cards:
            return EgpuPresence.UNKNOWN
        g1 = match_gpd_g1(
            cards,
            self._pci_usb4.scan_pci(),
            self._pci_usb4.scan_usb4(),
        )
        if g1.detected:
            return EgpuPresence.PRESENT
        return EgpuPresence.ABSENT


class Login1SleepInhibitor:
    """Own a guarded systemd-inhibit process with crash-release semantics."""

    def __init__(
        self,
        process_factory: Callable[[], InhibitorProcess] = SleepInhibitorProcess,
    ) -> None:
        self._process_factory = process_factory
        self._lock = RLock()
        self._process: InhibitorProcess | None = None
        self._error = ""

    def acquire(self) -> InhibitorLeaseStatus:
        with self._lock:
            if self._process is not None:
                current = self._process.status()
                if current.running:
                    return InhibitorLeaseStatus(True)
                self._process = None
            process = self._process_factory()
            current = process.start()
            if not current.running:
                self._error = (
                    "Could not acquire the login1 sleep inhibitor: "
                    + (current.error or "systemd-inhibit did not stay active")
                )
                return InhibitorLeaseStatus(False, self._error)
            self._process = process
            self._error = ""
            return InhibitorLeaseStatus(True)

    def release(self) -> InhibitorLeaseStatus:
        with self._lock:
            process = self._process
            self._process = None
            if process is not None:
                current = process.stop()
                if current.error:
                    self._error = "Could not release the sleep inhibitor: " + current.error
                    return InhibitorLeaseStatus(False, self._error)
            self._error = ""
            return InhibitorLeaseStatus(False)

    def status(self) -> InhibitorLeaseStatus:
        with self._lock:
            if self._process is None:
                return InhibitorLeaseStatus(False, self._error)
            current = self._process.status()
            if not current.running:
                self._process = None
                if current.error:
                    self._error = "Sleep inhibitor exited: " + current.error
            return InhibitorLeaseStatus(current.running, self._error)


class SleepGuardController:
    def __init__(self, lease: Login1SleepInhibitor | None = None) -> None:
        self._lease = lease or Login1SleepInhibitor()
        self._lock = RLock()
        self._closed = False

    def reconcile(self, presence: EgpuPresence) -> InhibitorLeaseStatus:
        with self._lock:
            if self._closed:
                return self._lease.status()
            action = decide_sleep_guard(presence)
            if action is SleepGuardAction.ACQUIRE:
                return self._lease.acquire()
            if action is SleepGuardAction.RELEASE:
                return self._lease.release()
            return self._lease.status()

    def close(self) -> InhibitorLeaseStatus:
        with self._lock:
            self._closed = True
            return self._lease.release()

    def status(self) -> InhibitorLeaseStatus:
        with self._lock:
            return self._lease.status()
