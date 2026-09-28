"""Journey regression: a new sleep request after an earlier Safe Disconnect."""

import unittest
import os
import sys
import tempfile
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests import test_main_physical_unplug_sleep as support
from tests import test_main_whole_dock_trial_status_reset as reset_support


class RetainedDisconnectSleepTests(unittest.TestCase):
    def test_definite_refusal_then_unclaimed_reconnect_rearms_disconnect(self):
        fixture = reset_support.WholeDockTrialStatusResetTests()
        fixture.setUp()
        fixture.plugin._whole_dock_trial_status = {
            "schema_version": 1, "code": "dock_power.request_unverified",
            "busy": False, "ok": False, "safe_to_unplug": False,
            "software_down": True, "power_requested": False,
            "sleep_cycle_observed": False, "unplug_required": False,
            "power_action": "sleep", "route_action": "whole_dock_sleep",
            "request_id": "f" * 32,
            "suspend": {"requested": False, "code": "dock_power.suspend_inhibited"},
        }
        p1, p2, p3 = fixture.patches()
        with p1, p2, p3:
            result = fixture.read()
        self.assertEqual(result["code"], "dock_teardown.no_trial")

    def test_definite_suspend_refusal_releases_consumed_intent_after_unplug(self):
        fixture = support.MainPhysicalUnplugSleepTests()
        fixture.setUp()
        plugin, module = fixture.plugin, fixture.module
        fixture.store.release_unsubmitted.return_value = True
        plugin._connection_topology.observe.return_value = fixture._topology(
            present=False, absent=True)
        plugin._dock_power_portable_verified = Mock(return_value=True)

        def refused(request, **kwargs):
            self.assertTrue(kwargs["consume"](request))
            plugin._whole_dock_suspend_result = {
                "requested": False, "code": "dock_power.suspend_inhibited",
            }
            return module.DockPowerResult("dock_power.request_unverified")

        plugin._run_sleep_request = refused
        with patch.object(module.time, "monotonic", return_value=11), \
                patch.object(module, "verified_transport_absent", return_value=True):
            result = plugin._sleep_after_physical_unplug(
                fixture.request, fixture.runtime, fixture.admission, fixture.store)

        self.assertFalse(result.requested)
        fixture.store.consume.assert_called_once()
        fixture.store.release_unsubmitted.assert_called_once()

    def test_new_sleep_after_previous_disconnect_reaches_sleep_after_unplug(self):
        fixture = support.MainPhysicalUnplugSleepTests()
        fixture.setUp()
        plugin, module = fixture.plugin, fixture.module
        fixture.store.bind_sleep_after_disconnect.return_value = True
        # Real requests get a new UUID, unlike the old matching-ID fixture.
        old_operation = "d" * 32
        fixture.runtime._operation = old_operation
        fixture.runtime._owned = lambda stage: stage == "software_down"
        fixture.runtime.verify_power_continuation = lambda *args, **kwargs: True
        fixture.store.load.return_value = module.WholeDockClaim(
            old_operation, fixture.runtime.binding.binding,
            fixture.runtime.binding.generation, "software_down",
        )
        plugin._whole_dock_trial_runtime = (fixture.runtime, fixture.admission)
        plugin._dock_mutation_gate = lambda: SimpleNamespace(
            admit=lambda **kwargs: nullcontext())
        plugin._connection_topology.observe.return_value = fixture._topology(
            present=False, absent=True)
        plugin._dock_power_portable_verified = Mock(return_value=True)
        plugin._run_sleep_request = Mock(return_value=module.DockPowerResult(
            "dock_power.request_unverified", requested=False))
        with patch.object(module, "verified_transport_absent", side_effect=[False, True]), \
                patch.object(module, "SuspendObserver") as observer, \
                patch.object(module, "RootOwnedRuntimeState"), \
                patch.object(module, "DockPowerIntentStore", return_value=fixture.store), \
                patch.object(module.time, "monotonic", return_value=11):
            observer.return_value.read.return_value = object()
            result = plugin._run_dock_power_request(
                fixture.request, keep_connected=False)

        self.assertEqual(plugin._run_sleep_request.call_count, 1,
                         f"Physical unplug never reached sleep: {result.code}")


@unittest.skipUnless(sys.platform == "linux", "Requires real Linux file locking")
class AuthorizationHoldLockJourneyTests(unittest.TestCase):
    def setUp(self):
        from regear.delivery.whole_dock_claim import WholeDockClaimStore
        from regear.delivery.device_authorization_hold import DeviceAuthorizationHoldStore
        from regear.delivery.whole_dock_runtime import WholeDockRuntime

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        os.chmod(root, 0o700)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, descriptor)
        kwargs = dict(owner_uid=os.geteuid(), trusted_directory_fd=descriptor)
        self.claims = WholeDockClaimStore(root, **kwargs)
        self.holds = DeviceAuthorizationHoldStore(root, **kwargs)
        self.claims.claim("operation", "binding", "generation")
        self.claims.record("operation", "tunnel_remove_intent")
        self.runtime = object.__new__(WholeDockRuntime)
        self.runtime._store = self.claims
        self.runtime._operation = "operation"
        self.runtime.binding = SimpleNamespace(binding="binding", generation="generation")
        self.runtime._admission = lambda: True
        self.observation = SimpleNamespace(
            topology_complete=True, idle=True, gpu_functions_present=False,
            gpu_scan_complete=True, usb=SimpleNamespace(controller_bdf="usb"),
            tunnel=SimpleNamespace(sysfs_id="router"))
        self.runtime.observe = lambda: self.observation
        decision = patch("regear.delivery.whole_dock_runtime.decide_dock_teardown",
                         return_value=SimpleNamespace(permitted=True))
        decision.start()
        self.addCleanup(decision.stop)
        self.uuid = "00000000-0000-0000-0000-000000000001"

    def guard(self):
        return self.runtime._guard(self.observation, "tunnel_remove_intent")

    def test_prepare_with_real_runtime_guard_does_not_relock(self):
        hold = self.holds.prepare("operation", "binding", "generation",
                                  self.uuid, self.guard)
        self.assertIsNotNone(hold)
        self.assertEqual(hold.state, "prepared")
        self.assertEqual(self.holds.load_hold(), hold)

    def test_mark_manual_with_real_runtime_guard_does_not_relock(self):
        hold = self.holds.prepare("operation", "binding", "generation",
                                  self.uuid, lambda: True)
        marked = self.holds.mark_manual(hold, self.guard)
        self.assertIsNotNone(marked)
        self.assertEqual(marked.state, "manual")
        self.assertEqual(self.holds.load_hold(), marked)

    def test_prepare_rechecks_claim_changed_during_guard(self):
        def changed():
            self.assertTrue(self.guard())
            self.claims.record("operation", "software_down")
            return True

        self.assertIsNone(self.holds.prepare(
            "operation", "binding", "generation", self.uuid, changed))
        self.assertIsNone(self.holds.load_hold())

    def test_mark_manual_rechecks_claim_changed_during_guard(self):
        hold = self.holds.prepare("operation", "binding", "generation",
                                  self.uuid, lambda: True)

        def changed():
            self.assertTrue(self.guard())
            self.claims.record("operation", "software_down")
            return True

        self.assertIsNone(self.holds.mark_manual(hold, changed))
        self.assertEqual(self.holds.load_hold(), hold)


if __name__ == "__main__":
    unittest.main()
