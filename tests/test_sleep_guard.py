from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.sleep_inhibitor import (  # noqa: E402
    G1SleepGuardHardwareDiscovery,
    Login1SleepInhibitor,
    SleepGuardController,
)
from hdm.adapters.steamos.commands import (  # noqa: E402
    ManagedProcessStatus,
    SleepInhibitorProcess,
)
from hdm.adapters.steamos.drm import DrmCardRecord  # noqa: E402
from hdm.adapters.steamos.pci import (  # noqa: E402
    PciDeviceRecord,
    Usb4DeviceRecord,
)
from hdm.adapters.steamos.host import HostRecord  # noqa: E402
from hdm.domain.models import EgpuPresence, SleepGuardAction  # noqa: E402
from hdm.domain.sleep_policy import decide_sleep_guard  # noqa: E402
from hdm.profiles.gpd_g1 import GpdG1Match  # noqa: E402


class Fixed:
    def __init__(self, value):
        self.value = value

    def scan(self):
        return self.value


class FixedTopology:
    def scan_pci(self):
        return ()

    def scan_usb4(self):
        return ()


class PartialG1Topology(FixedTopology):
    def scan_usb4(self):
        return (
            Usb4DeviceRecord("0-2", "Intel", "Tapex Creek", True, "a" * 64),
        )


#: The PCI topology the tested Ally X reports *after* a live disconnect has
#: software-removed 0000:08:00.0 and 0000:08:00.1.
#:
#: The GPU and its audio function are gone. What is not gone: the dock's own
#: Thunderbolt USB controller on the sibling port of the same switch, the
#: bridges above it, and the Thunderbolt link itself -- all wake-enabled. The
#: BDFs and the ancestry are the ones recorded from the device in issue #201.
AFTER_SOFTWARE_REMOVAL = (
    PciDeviceRecord(
        "0000:00:03.1", "0x1002", "0x14ef", "0x060400", "pcieport", (), False
    ),
    PciDeviceRecord(
        "0000:04:00.0", "0x8086", "0x15ef", "0x060400", "pcieport",
        ("0000:00:03.1",), True,
    ),
    PciDeviceRecord(
        "0000:05:02.0", "0x8086", "0x15ef", "0x060400", "pcieport",
        ("0000:04:00.0", "0000:00:03.1"), True,
    ),
    # The dock's own USB controller. Still attached, still wake-enabled.
    PciDeviceRecord(
        "0000:09:00.0", "0x8086", "0x15f0", "0x0c0330", "xhci_hcd",
        ("0000:05:02.0", "0000:04:00.0", "0000:00:03.1"), True,
    ),
)


class AfterSoftwareRemovalTopology(FixedTopology):
    """What the machine looks like once a live disconnect has run."""

    def scan_pci(self):
        return AFTER_SOFTWARE_REMOVAL

    def scan_usb4(self):
        # The Thunderbolt router is a thunderbolt-bus device. Removing PCI
        # functions does not touch it, so it is still here and still authorized.
        return (Usb4DeviceRecord("0-1", "Intel", "Tapex Creek", True, "a" * 64),)


class FakeProcess:
    def __init__(self, start_error: str = "") -> None:
        self.running = False
        self.start_error = start_error
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> ManagedProcessStatus:
        self.start_count += 1
        if self.start_error:
            return ManagedProcessStatus(False, self.start_error)
        self.running = True
        return ManagedProcessStatus(True)

    def stop(self) -> ManagedProcessStatus:
        self.stop_count += 1
        self.running = False
        return ManagedProcessStatus(False)

    def status(self) -> ManagedProcessStatus:
        return ManagedProcessStatus(self.running)


class SleepGuardPolicyTests(unittest.TestCase):
    def test_presence_maps_to_acquire_release_or_hold(self):
        self.assertEqual(
            decide_sleep_guard(EgpuPresence.PRESENT), SleepGuardAction.ACQUIRE
        )
        self.assertEqual(
            decide_sleep_guard(EgpuPresence.ABSENT), SleepGuardAction.RELEASE
        )
        self.assertEqual(
            decide_sleep_guard(EgpuPresence.UNKNOWN), SleepGuardAction.HOLD
        )


class G1SleepGuardHardwareDiscoveryTests(unittest.TestCase):
    ALLY = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
    INTERNAL = DrmCardRecord(
        "card0", "0000:01:00.0", "0x1002", "0x15bf", True, "amdgpu"
    )

    def test_detected_candidate_acquires_even_before_full_identity_verification(self):
        discovery = G1SleepGuardHardwareDiscovery(
            drm=Fixed((self.INTERNAL,)),
            pci_usb4=FixedTopology(),
            host=Fixed(self.ALLY),
        )
        with patch(
            "hdm.adapters.steamos.sleep_inhibitor.match_gpd_g1",
            return_value=GpdG1Match(True, False, reason="incomplete fixture"),
        ):
            self.assertEqual(discovery.observe_presence(), EgpuPresence.PRESENT)

    def test_partial_usb4_candidate_is_not_treated_as_verified_absence(self):
        discovery = G1SleepGuardHardwareDiscovery(
            drm=Fixed((self.INTERNAL,)),
            pci_usb4=PartialG1Topology(),
            host=Fixed(self.ALLY),
        )

        self.assertEqual(discovery.observe_presence(), EgpuPresence.PRESENT)

    def test_verified_absence_releases_and_missing_host_evidence_holds(self):
        supported = G1SleepGuardHardwareDiscovery(
            drm=Fixed((self.INTERNAL,)),
            pci_usb4=FixedTopology(),
            host=Fixed(self.ALLY),
        )
        unsupported = G1SleepGuardHardwareDiscovery(
            drm=Fixed((self.INTERNAL,)),
            pci_usb4=FixedTopology(),
            host=Fixed(HostRecord("Unknown", "Unknown", "Unknown")),
        )
        with patch(
            "hdm.adapters.steamos.sleep_inhibitor.match_gpd_g1",
            return_value=GpdG1Match(False, False),
        ):
            self.assertEqual(supported.observe_presence(), EgpuPresence.ABSENT)
        self.assertEqual(unsupported.observe_presence(), EgpuPresence.UNKNOWN)


class AfterLiveDisconnectTests(unittest.TestCase):
    """Issue #201: does software-removing the GPU release the sleep guard?

    It matters because the GPU functions are not the only thing on that
    tunnel. The dock's own USB controller sits on a sibling port of the same
    Thunderbolt switch, wake-enabled, and a removal does not touch it. If the
    guard released on GPU absence alone, the handheld would be allowed to sleep
    with a plausible cause of the immediate wake still armed -- the exact
    failure the guard exists to prevent.

    It does not release, and this pins why: presence does not key on the GPU.
    When no DRM card matches it falls back to the transport, and the authorized
    Thunderbolt router outlives any PCI removal.
    """

    ALLY = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
    INTERNAL = DrmCardRecord(
        "card0", "0000:01:00.0", "0x1002", "0x15bf", True, "amdgpu"
    )

    def discovery(self):
        return G1SleepGuardHardwareDiscovery(
            drm=Fixed((self.INTERNAL,)),
            pci_usb4=AfterSoftwareRemovalTopology(),
            host=Fixed(self.ALLY),
        )

    def test_removing_the_gpu_does_not_report_the_dock_as_absent(self) -> None:
        self.assertEqual(self.discovery().observe_presence(), EgpuPresence.PRESENT)

    def test_the_sleep_guard_therefore_stays_armed(self) -> None:
        self.assertEqual(
            decide_sleep_guard(self.discovery().observe_presence()),
            SleepGuardAction.ACQUIRE,
        )

    def test_the_wake_enabled_usb_controller_is_still_in_the_topology(self) -> None:
        # If a future change makes presence key on PCI alone, this is the
        # record that has to keep it armed.
        bdfs = {record.bdf for record in AFTER_SOFTWARE_REMOVAL}

        self.assertIn("0000:09:00.0", bdfs)
        self.assertNotIn("0000:08:00.0", bdfs)
        self.assertNotIn("0000:08:00.1", bdfs)

    def test_only_an_unplugged_cable_reports_absence(self) -> None:
        # The Thunderbolt router going away is a physical disconnection, which
        # is the one thing that should release the guard.
        unplugged = G1SleepGuardHardwareDiscovery(
            drm=Fixed((self.INTERNAL,)),
            pci_usb4=FixedTopology(),
            host=Fixed(self.ALLY),
        )

        self.assertEqual(unplugged.observe_presence(), EgpuPresence.ABSENT)


class Login1SleepInhibitorTests(unittest.TestCase):
    def test_system_process_uses_exact_guarded_argv(self):
        argv = SleepInhibitorProcess.argv()

        self.assertEqual(argv[0], "/usr/bin/python")
        self.assertEqual(argv[2], "--guard")
        self.assertTrue(argv[1].endswith("inhibitor_guard.py"))
        self.assertGreater(int(argv[3]), 1)

    def test_system_process_inherits_no_variable_at_all(self):
        """An allowlist, so a new influential variable needs no denylist entry."""
        with patch.dict(
            "os.environ",
            {
                "LD_LIBRARY_PATH": "/tmp/decky",
                "LD_PRELOAD": "/tmp/injected.so",
                "PYTHONHOME": "/tmp/python",
                "PYTHONPATH": "/tmp/modules",
                "PATH": "/tmp/evil",
                # Not on any denylist, and must still not reach the child.
                "PYTHONWARNINGS": "all",
                "XDG_RUNTIME_DIR": "/tmp/runtime",
            },
            clear=True,
        ):
            environment = SleepInhibitorProcess.environment()

        self.assertEqual(environment, SleepInhibitorProcess.CLEAN_ENVIRONMENT)
        self.assertNotIn("PYTHONWARNINGS", environment)
        self.assertEqual(environment["PATH"], "/usr/bin:/bin")

    def test_acquire_is_idempotent_and_release_stops_exact_process(self):
        process = FakeProcess()
        factory_count = 0

        def factory():
            nonlocal factory_count
            factory_count += 1
            return process

        lease = Login1SleepInhibitor(factory)

        self.assertTrue(lease.acquire().active)
        self.assertTrue(lease.acquire().active)
        self.assertEqual(factory_count, 1)
        self.assertEqual(process.start_count, 1)
        self.assertFalse(lease.release().active)
        self.assertEqual(process.stop_count, 1)
        self.assertFalse(lease.release().active)
        self.assertEqual(process.stop_count, 1)

    def test_failed_acquire_is_inactive_and_retryable(self):
        attempts: list[FakeProcess] = []

        def fail():
            process = FakeProcess("login1 unavailable")
            attempts.append(process)
            return process

        lease = Login1SleepInhibitor(fail)

        first = lease.acquire()
        second = lease.acquire()

        self.assertFalse(first.active)
        self.assertIn("login1 unavailable", first.error)
        self.assertFalse(second.active)
        self.assertEqual(len(attempts), 2)

    def test_unknown_presence_holds_active_lease_until_verified_absence(self):
        process = FakeProcess()
        controller = SleepGuardController(Login1SleepInhibitor(lambda: process))

        self.assertTrue(controller.reconcile(EgpuPresence.PRESENT).active)
        self.assertTrue(controller.reconcile(EgpuPresence.UNKNOWN).active)
        self.assertEqual(process.stop_count, 0)
        self.assertFalse(controller.reconcile(EgpuPresence.ABSENT).active)
        self.assertEqual(process.stop_count, 1)

    def test_close_is_terminal_and_prevents_reacquisition(self):
        process = FakeProcess()
        controller = SleepGuardController(Login1SleepInhibitor(lambda: process))

        self.assertTrue(controller.reconcile(EgpuPresence.PRESENT).active)
        self.assertFalse(controller.close().active)
        self.assertFalse(controller.reconcile(EgpuPresence.PRESENT).active)
        self.assertEqual(process.start_count, 1)
        self.assertEqual(process.stop_count, 1)


if __name__ == "__main__":
    unittest.main()
