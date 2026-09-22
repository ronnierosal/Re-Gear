"""Disconnect-before-sleep waits for a real cable removal."""

import asyncio
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


class MainPhysicalUnplugSleepTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._whole_dock_trial_lease = Mock()
        self.plugin._whole_dock_trial_lease.release.return_value = SimpleNamespace(
            active=False)
        self.plugin._whole_dock_trial_runtime = object()
        self.plugin._connection_topology = Mock()
        self.plugin._dock_sleep_status = {}
        self.request = SimpleNamespace(
            action="sleep", operation="a" * 32,
            session="1" * 64 + ":" + "2" * 32,
            requested_at=10.0, deadline=20.0,
        )
        self.runtime = SimpleNamespace(
            _operation=self.request.operation,
            binding=SimpleNamespace(binding="b" * 64, generation="c" * 64),
        )
        self.admission = {"held": True}
        self.store = Mock()
        self.claim = self.module.WholeDockClaim(
            self.request.operation,
            self.runtime.binding.binding,
            self.runtime.binding.generation,
            "software_down",
        )
        self.store.load.return_value = self.claim
        self.store.release_bound_sleep.return_value = True
        self.store.retire_observed_sleep.return_value = True
        self.store.power_intent_absent.return_value = True
        self.store.retire_physically_disconnected.return_value = "completed-absent"

    def _topology(self, *, present, absent):
        return SimpleNamespace(
            transport_present=present,
            transport_absent_verified=absent,
        )

    def test_expiry_never_submits_and_waits_for_physical_absence_before_cleanup(self):
        observations = {"count": 0}
        def topology():
            observations["count"] += 1
            return self._topology(
                present=observations["count"] < 3,
                absent=observations["count"] >= 3,
            )
        self.plugin._connection_topology.observe.side_effect = topology
        self.plugin._dock_power_portable_verified = Mock(return_value=True)
        self.plugin._run_sleep_request = Mock()
        with patch.object(self.module.time, "monotonic", side_effect=[11.0, 20.0, 20.0, 21.0]), \
                patch.object(self.module.time, "sleep"), \
                patch.object(self.module, "verified_transport_absent", return_value=True):
            result = self.plugin._sleep_after_physical_unplug(
                self.request, self.runtime, self.admission, self.store)

        self.assertEqual(result.code, "dock_power.unplug_request_expired")
        self.assertFalse(result.requested)
        self.assertTrue(result.software_down)
        self.plugin._run_sleep_request.assert_not_called()
        self.store.release_bound_sleep.assert_called_once()
        self.store.retire_physically_disconnected.assert_called_once()
        self.plugin._whole_dock_trial_lease.release.assert_called_once()
        self.assertIsNone(self.plugin._whole_dock_trial_runtime)
        self.assertEqual(
            self.plugin._dock_sleep_status["code"],
            "dock_power.unplug_request_expired",
        )
        self.assertFalse(self.plugin._dock_sleep_status["safe_to_unplug"])

    def test_strict_physical_absence_submits_original_sleep_once(self):
        self.plugin._connection_topology.observe.return_value = self._topology(
            present=False, absent=True)
        self.plugin._dock_power_portable_verified = Mock(return_value=True)
        observed = self.module.DockPowerResult(
            "dock_power.sleep_cycle_observed", True, software_down=True)
        self.plugin._run_sleep_request = Mock(return_value=observed)

        with patch.object(self.module.time, "monotonic", return_value=11.0), \
                patch.object(self.module, "verified_transport_absent", return_value=True):
            result = self.plugin._sleep_after_physical_unplug(
                self.request, self.runtime, self.admission, self.store)
            call = self.plugin._run_sleep_request.call_args
            self.assertTrue(call.kwargs["verify"]())

        self.assertIs(result, observed)
        self.plugin._run_sleep_request.assert_called_once()
        self.assertIs(call.args[0], self.request)
        self.assertTrue(call.kwargs["consume"](self.request))
        self.store.consume.assert_called_once_with(
            self.request.operation,
            self.runtime.binding.binding,
            self.runtime.binding.generation,
            "sleep",
            self.request.session,
            self.request.requested_at,
            self.request.deadline,
        )
        self.store.retire_observed_sleep.assert_called_once()
        self.store.retire_physically_disconnected.assert_called_once()
        self.plugin._whole_dock_trial_lease.release.assert_called_once()
        self.assertIsNone(self.plugin._whole_dock_trial_runtime)

    def test_topology_absence_without_strict_absence_does_not_sleep(self):
        observations = {"count": 0}
        def topology():
            observations["count"] += 1
            return self._topology(present=False, absent=True)
        self.plugin._connection_topology.observe.side_effect = topology
        self.plugin._dock_power_portable_verified = Mock(return_value=True)
        self.plugin._run_sleep_request = Mock()

        transport = {"count": 0}
        def absent():
            transport["count"] += 1
            return transport["count"] >= 2
        with patch.object(self.module.time, "monotonic", side_effect=[11.0, 20.0, 20.0]), \
                patch.object(self.module.time, "sleep"), \
                patch.object(self.module, "verified_transport_absent", side_effect=absent):
            result = self.plugin._sleep_after_physical_unplug(
                self.request, self.runtime, self.admission, self.store)

        self.assertEqual(result.code, "dock_power.unplug_request_expired")
        self.plugin._run_sleep_request.assert_not_called()

    def test_confirmed_rpc_routes_to_physical_unplug_sleep(self):
        async def background(worker):
            return worker()

        self.plugin._run_background_operation = background
        self.plugin._run_dock_power_request = Mock(return_value=self.module.DockPowerResult(
            "dock_power.unplug_request_expired",
            software_down=True,
        ))
        self.plugin._dock_power_session = self.request.session

        with patch.object(
            self.module,
            "create_power_request",
            return_value=self.request,
        ):
            result = asyncio.run(self.plugin.execute_egpu_disconnect(
                release_display=True,
                trial_action="whole_dock_sleep",
                trial_confirmed=True,
                trial_attachment_token=f"{'a' * 64}:{'b' * 64}",
                trial_request_id="c" * 32,
            ))

        self.assertEqual(result["code"], "dock_power.unplug_request_expired")
        self.assertTrue(result["software_down"])
        self.assertFalse(result["power_requested"])
        self.assertFalse(result["safe_to_unplug"])
        self.plugin._run_dock_power_request.assert_called_once_with(
            self.request,
            f"{'a' * 64}:{'b' * 64}",
            keep_connected=False,
        )

    def test_existing_software_down_state_still_waits_for_physical_unplug(self):
        admission = {"held": False}
        runtime = SimpleNamespace(
            _operation=self.request.operation,
            _owned=lambda phase: phase == "software_down",
            verify_power_continuation=lambda *_args, **_kwargs: True,
        )
        self.plugin._whole_dock_trial_runtime = (runtime, admission)
        self.plugin._dock_mutation_gate = lambda: SimpleNamespace(
            admit=lambda **_kwargs: nullcontext()
        )
        expected = self.module.DockPowerResult(
            "dock_power.unplug_required",
            software_down=True,
        )
        self.plugin._sleep_after_physical_unplug = Mock(return_value=expected)
        self.plugin._sleep_after_dock_down = Mock()

        with patch.object(
            self.module,
            "verified_transport_absent",
            return_value=False,
        ), patch.object(self.module, "SuspendObserver") as observer, \
                patch.object(self.module, "RootOwnedRuntimeState") as state, \
                patch.object(self.module, "DockPowerIntentStore"):
            observer.return_value.read.return_value = object()
            state.return_value.ensure.return_value = object()
            result = self.plugin._run_dock_power_request(
                self.request,
                keep_connected=False,
            )

        self.assertTrue(result.software_down)
        self.plugin._sleep_after_physical_unplug.assert_called_once()
        self.plugin._sleep_after_dock_down.assert_not_called()


if __name__ == "__main__":
    unittest.main()
