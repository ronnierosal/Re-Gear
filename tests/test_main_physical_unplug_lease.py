"""Release the retained disconnect inhibitor only after physical unplug."""
import asyncio
from contextlib import nullcontext
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


REQUEST_ID = "c" * 32


class PhysicalUnplugLeaseReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._whole_dock_trial_worker_alive = False
        self.plugin._release_capture_task = None
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1,
            "code": "dock_teardown.software_down",
            "busy": False,
            "ok": True,
            "software_down": True,
            "safe_to_unplug": False,
            "request_id": REQUEST_ID,
            "phase": "late_completion",
        }
        self.runtime = NS(_operation=REQUEST_ID)
        self.admission = {"held": False}
        self.plugin._whole_dock_trial_runtime = (self.runtime, self.admission)
        self.lease = Mock()
        self.lease.status.return_value = NS(active=True, error="")
        self.lease.release.return_value = NS(active=False, error="")
        self.plugin._whole_dock_trial_lease = self.lease
        self.topology = NS(
            transport_present=False,
            transport_absent_verified=True,
        )
        self.plugin._connection_topology = NS(
            observe=Mock(return_value=self.topology)
        )
        self.plugin._dock_mutation_gate = lambda: NS(
            admit=lambda **_kwargs: nullcontext()
        )
        self.plugin._sleep_hardware = NS(
            observe_presence=lambda: self.module.EgpuPresence.ABSENT
        )
        self.plugin._sleep_guard = NS(
            reconcile=lambda _presence: NS(active=False, error="")
        )
        self.plugin._last_sleep_guard_log = ("absent", False, "")

    def reconcile(self, *, independently_absent=True):
        with patch.object(
            self.module,
            "verified_transport_absent",
            return_value=independently_absent,
        ):
            asyncio.run(self.plugin._reconcile_sleep_guard())

    def test_absent_transport_releases_owned_lease_and_readiness_is_clear(self):
        terminal = self.plugin._whole_dock_trial_status
        runtime = self.plugin._whole_dock_trial_runtime

        self.reconcile()

        self.lease.release.assert_called_once_with()
        self.assertIsNone(self.plugin._whole_dock_trial_lease)
        self.assertIs(self.plugin._whole_dock_trial_status, terminal)
        self.assertIs(self.plugin._whole_dock_trial_runtime, runtime)
        self.assertEqual(self.plugin._connection_topology.observe.call_count, 2)
        readiness = asyncio.run(self.plugin.get_sleep_readiness())
        self.assertEqual(readiness["code"], "sleep.available")
        self.assertIs(readiness["retained_inhibitor"], False)

    def test_deauthorized_but_attached_and_unknown_topology_keep_lease(self):
        for topology in (
            NS(transport_present=True, transport_absent_verified=False),
            NS(transport_present=None, transport_absent_verified=None),
        ):
            with self.subTest(topology=topology):
                self.setUp()
                self.plugin._connection_topology.observe.return_value = topology
                self.reconcile()
                self.lease.release.assert_not_called()
                self.assertIs(self.plugin._whole_dock_trial_lease, self.lease)

    def test_independent_absence_failure_keeps_lease(self):
        self.reconcile(independently_absent=False)

        self.lease.release.assert_not_called()
        self.assertIs(self.plugin._whole_dock_trial_lease, self.lease)

    def test_transport_reattach_between_checks_keeps_lease(self):
        self.plugin._connection_topology.observe.side_effect = (
            self.topology,
            NS(transport_present=True, transport_absent_verified=False),
        )

        self.reconcile()

        self.lease.release.assert_not_called()
        self.assertIs(self.plugin._whole_dock_trial_lease, self.lease)

    def test_active_trial_capture_and_power_handoff_keep_lease(self):
        cases = ("worker", "capture", "admission", "power_handoff")
        for case in cases:
            with self.subTest(case=case):
                self.setUp()
                if case == "worker":
                    self.plugin._whole_dock_trial_worker_alive = True
                elif case == "capture":
                    self.plugin._release_capture_task = NS(done=lambda: False)
                elif case == "admission":
                    self.admission["held"] = True
                else:
                    self.admission["power_handoff"] = True
                self.reconcile()
                self.lease.release.assert_not_called()
                self.assertIs(self.plugin._whole_dock_trial_lease, self.lease)

    def test_terminal_result_must_match_retained_runtime_request(self):
        malformed = (
            {"code": "dock_teardown.trial_unresolved"},
            {"busy": True},
            {"ok": False},
            {"software_down": False},
            {"safe_to_unplug": True},
            {"request_id": "d" * 32},
        )
        for change in malformed:
            with self.subTest(change=change):
                self.setUp()
                self.plugin._whole_dock_trial_status.update(change)
                self.reconcile()
                self.lease.release.assert_not_called()

    def test_failed_owned_release_stays_retained_and_readiness_is_unknown(self):
        self.lease.release.return_value = NS(
            active=False,
            error="inhibitor stop failed",
        )

        self.reconcile()

        self.lease.release.assert_called_once_with()
        self.assertIs(self.plugin._whole_dock_trial_lease, self.lease)
        self.lease.status.return_value = NS(
            active=False,
            error="inhibitor stop failed",
        )
        readiness = asyncio.run(self.plugin.get_sleep_readiness())
        self.assertEqual(readiness["code"], "sleep.available")
        self.assertIsNone(readiness["retained_inhibitor"])


if __name__ == "__main__":
    unittest.main()
