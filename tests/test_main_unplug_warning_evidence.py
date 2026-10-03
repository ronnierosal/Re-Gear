"""Strict, request-correlated evidence for the unplug warning lifecycle."""

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


REQUEST_ID = "d" * 32


class UnplugWarningEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._whole_dock_trial_worker_alive = False
        self.plugin._release_capture_task = None
        self.plugin._whole_dock_physical_absence_verified_request = ""
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1,
            "code": "dock_teardown.software_down",
            "busy": False,
            "ok": True,
            "software_down": True,
            "safe_to_unplug": False,
            "request_id": REQUEST_ID,
        }
        self.runtime = NS(_operation=REQUEST_ID)
        self.admission = {"held": False, "power_handoff": False}
        self.plugin._whole_dock_trial_runtime = (self.runtime, self.admission)
        self.lease = Mock()
        self.lease.status.return_value = NS(active=True, error="")
        self.lease.release.return_value = NS(active=False, error="")
        self.plugin._whole_dock_trial_lease = self.lease
        self.absent = NS(
            transport_present=False,
            transport_absent_verified=True,
        )
        self.plugin._connection_topology = NS(
            observe=Mock(return_value=self.absent)
        )
        self.plugin._dock_mutation_gate = lambda: NS(
            admit=lambda **_kwargs: nullcontext()
        )

    def reconcile(self, *, independently_absent=True):
        with patch.object(
            self.module,
            "verified_transport_absent",
            return_value=independently_absent,
        ):
            return self.plugin._reconcile_physically_unplugged_trial_lease()

    def test_exact_strict_absence_records_request_after_lease_release(self):
        self.assertTrue(self.reconcile())

        self.assertEqual(
            self.plugin._whole_dock_physical_absence_verified_request,
            REQUEST_ID,
        )
        self.assertIsNone(self.plugin._whole_dock_trial_lease)
        self.assertEqual(self.plugin._connection_topology.observe.call_count, 2)

    def test_failed_strict_absence_does_not_record_request(self):
        self.assertFalse(self.reconcile(independently_absent=False))

        self.assertEqual(
            self.plugin._whole_dock_physical_absence_verified_request,
            "",
        )
        self.lease.release.assert_not_called()

    def test_failed_lease_release_does_not_record_request(self):
        self.lease.release.return_value = NS(active=True, error="still active")

        self.assertFalse(self.reconcile())

        self.assertEqual(
            self.plugin._whole_dock_physical_absence_verified_request,
            "",
        )
        self.assertIs(self.plugin._whole_dock_trial_lease, self.lease)

    def test_sleep_cleanup_records_public_request_only_after_strict_absence(self):
        public_request = "e" * 32
        request = NS(
            action="sleep",
            operation="a" * 32,
            session="1" * 64 + ":" + "2" * 32,
            requested_at=10.0,
            deadline=20.0,
        )
        runtime = NS(
            _operation=request.operation,
            binding=NS(binding="b" * 64, generation="c" * 64),
        )
        admission = {"held": True}
        claim = self.module.WholeDockClaim(
            request.operation,
            runtime.binding.binding,
            runtime.binding.generation,
            "software_down",
        )
        store = Mock()
        store.load.return_value = claim
        store.retire_observed_sleep.return_value = True
        store.power_intent_absent.return_value = True
        store.retire_physically_disconnected.return_value = "completed-absent"
        self.plugin._whole_dock_trial_runtime = (runtime, admission)
        self.plugin._whole_dock_trial_lease = self.lease
        self.plugin._dock_sleep_status = {}
        self.plugin._dock_power_context = (
            request,
            public_request,
            "whole_dock_sleep",
        )
        self.plugin._dock_power_portable_verified = Mock(return_value=True)
        observed = self.module.DockPowerResult(
            "dock_power.sleep_cycle_observed",
            True,
            software_down=True,
        )
        self.plugin._run_sleep_request = Mock(return_value=observed)

        with patch.object(self.module.time, "monotonic", return_value=11.0), \
                patch.object(
                    self.module,
                    "verified_transport_absent",
                    return_value=True,
                ):
            result = self.plugin._sleep_after_physical_unplug(
                request,
                runtime,
                admission,
                store,
            )
            call = self.plugin._run_sleep_request.call_args
            self.assertTrue(call.kwargs["verify"]())
            self.assertTrue(call.kwargs["consume"](request))

        self.assertIs(result, observed)
        self.assertEqual(
            self.plugin._whole_dock_physical_absence_verified_request,
            public_request,
        )
        self.assertIsNone(self.plugin._whole_dock_trial_runtime)

    def test_sleep_unplug_prompt_uses_existing_trial_poll_channel(self):
        self.plugin._whole_dock_trial_worker_alive = True
        self.plugin._whole_dock_trial_started = 10.0
        self.plugin._whole_dock_trial_phase = "dock_teardown"
        self.plugin._whole_dock_trial_status = {
            "schema_version": 1,
            "code": "dock_teardown.trial_running",
            "busy": True,
            "safe_to_unplug": False,
            "request_id": REQUEST_ID,
        }
        self.plugin._dock_sleep_status = {
            "schema_version": 1,
            "code": "dock_power.unplug_required",
            "busy": True,
            "ok": False,
            "safe_to_unplug": False,
            "software_down": True,
            "unplug_required": True,
            "power_action": "sleep",
            "route_action": "whole_dock_sleep",
            "request_id": REQUEST_ID,
        }

        with patch.object(self.module.time, "monotonic", return_value=12.0):
            result = asyncio.run(
                self.plugin.get_egpu_disconnect_status("whole_dock_trial")
            )

        self.assertEqual(result["code"], "dock_power.unplug_required")
        self.assertEqual(result["request_id"], REQUEST_ID)
        self.assertIs(result["software_down"], True)
        self.assertIs(result["in_flight"], True)
        self.assertEqual(result["elapsed_s"], 2)

    def test_mismatched_sleep_progress_never_replaces_trial_status(self):
        self.plugin._whole_dock_trial_worker_alive = True
        self.plugin._whole_dock_trial_started = 10.0
        self.plugin._whole_dock_trial_phase = "dock_teardown"
        self.plugin._dock_sleep_status = {
            "schema_version": 1,
            "code": "dock_power.unplug_required",
            "busy": True,
            "safe_to_unplug": False,
            "software_down": True,
            "route_action": "whole_dock_sleep",
            "request_id": "e" * 32,
        }

        with patch.object(self.module.time, "monotonic", return_value=12.0):
            result = asyncio.run(
                self.plugin.get_egpu_disconnect_status("whole_dock_trial")
            )

        self.assertEqual(result["code"], "dock_teardown.software_down")
        self.assertEqual(result["request_id"], REQUEST_ID)


if __name__ == "__main__":
    unittest.main()
