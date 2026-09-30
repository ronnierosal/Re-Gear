"""Retained authorization cleanup and disconnect diagnostic regressions."""
import asyncio
import unittest
from types import SimpleNamespace
from contextlib import nullcontext
from unittest.mock import Mock, patch

from tests import test_main_dock_mutation_gate as dock_support
from tests import test_main_physical_unplug_sleep as sleep_support


class AuthorizationCleanupOrderingTests(unittest.TestCase):
    def test_failed_hold_clear_preserves_claim_for_next_reconciliation(self):
        fixture = dock_support.CompletedAttachmentAbsenceTests()
        fixture.setUp()
        fixture.plugin._restore_remembered_authorization_after_absence = Mock(
            return_value=object())
        result, retired = fixture.fixture()
        self.assertFalse(result)
        self.assertEqual(retired, 0, "Never orphan an authorization hold after claim retirement")

    def test_success_clears_hold_before_retiring_claim(self):
        fixture = dock_support.CompletedAttachmentAbsenceTests()
        fixture.setUp()
        events = []

        def restore(*_):
            holds = fixture.module.DeviceAuthorizationHoldStore.return_value
            holds.clear_after_absence.side_effect = lambda *_: events.append("clear") or True
            store = fixture.module.DockPowerIntentStore.return_value
            retire = store.retire_physically_disconnected.side_effect

            def record_retirement(*args):
                events.append("retire")
                return retire(*args)

            store.retire_physically_disconnected.side_effect = record_retirement
            return object()

        fixture.plugin._restore_remembered_authorization_after_absence = restore
        self.assertEqual(fixture.fixture(), (True, 1))
        self.assertEqual(events, ["clear", "retire"])

    def test_sleep_cleanup_does_not_retire_claim_when_hold_clear_fails(self):
        fixture = sleep_support.MainPhysicalUnplugSleepTests()
        fixture.setUp()
        plugin, module = fixture.plugin, fixture.module
        fixture.store.release_unsubmitted.return_value = True
        plugin._connection_topology.observe.return_value = fixture._topology(
            present=False, absent=True)
        plugin._dock_power_portable_verified = Mock(return_value=True)
        plugin._restore_remembered_authorization_after_absence = Mock(return_value=object())

        def refused(request, **kwargs):
            self.assertTrue(kwargs["consume"](request))
            plugin._whole_dock_suspend_result = {"requested": False,
                                                "code": "dock_power.suspend_inhibited"}
            return module.DockPowerResult("dock_power.request_unverified")

        plugin._run_sleep_request = refused
        with patch.object(module.time, "monotonic", return_value=11), \
                patch.object(module, "verified_transport_absent", return_value=True), \
                patch.object(module, "DeviceAuthorizationHoldStore") as holds:
            holds.return_value.clear_after_absence.return_value = False
            plugin._sleep_after_physical_unplug(
                fixture.request, fixture.runtime, fixture.admission, fixture.store)
        fixture.store.retire_physically_disconnected.assert_not_called()
        plugin._whole_dock_trial_lease.release.assert_not_called()


class DisconnectDiagnosticTests(unittest.TestCase):
    def setUp(self):
        fixture = dock_support.MainDockAdmissionTests()
        fixture.setUp()
        self.module, self.plugin = fixture.module, fixture.plugin

    def test_phase_durations_measure_work_without_adding_waits(self):
        with patch.object(self.module.time, "perf_counter", side_effect=[10, 12, 15, 16]):
            self.plugin._set_disconnect_phase("return_portable")
            self.plugin._set_disconnect_phase("gpu_release")
            self.assertEqual(self.plugin._disconnect_timings(),
                             {"return_portable": 2000, "gpu_release": 3000})
            self.assertEqual(self.plugin._disconnect_timings(),
                             {"return_portable": 2000, "gpu_release": 4000})

    def test_failure_details_exclude_raw_text_and_invalid_stage_code_pairs(self):
        self.plugin._remember_teardown_result(
            SimpleNamespace(code="private/path/uuid"),
            SimpleNamespace(tunnel_stage="settle", tunnel_code="private/path/uuid"))
        self.assertEqual(self.plugin._whole_dock_teardown_details,
                         {"code": "dock_teardown.unresolved", "tunnel_stage": "settle"})

    def test_actual_power_route_remembers_teardown_before_wrapping_failure(self):
        plugin, module = self.plugin, self.module
        plugin._unloading = False
        plugin._dock_mutation_gate = lambda: SimpleNamespace(admit=lambda: nullcontext())
        plugin._return_portable_before_disconnect = Mock()
        binding = SimpleNamespace(binding="binding", generation="generation",
                                  usb_bdf="usb", router_id="router", gpu_bdf="gpu")
        runtime = Mock(tunnel_stage="settle",
                       tunnel_code="dock_teardown.tunnel_settle_unverified")
        runtime.execute_claimed.return_value = SimpleNamespace(
            code="dock_teardown.unresolved", software_down=False)
        request = SimpleNamespace(action="sleep", operation="operation",
                                  requested_at=0, deadline=float("inf"))
        with patch.object(module, "DrmDiscovery") as drm, \
                patch.object(module, "resolve_whole_dock", return_value=binding), \
                patch.object(module, "GamescopeDiscovery"), \
                patch.object(module, "resolve_gamescope_user", return_value=SimpleNamespace(
                    context=SimpleNamespace(uid=1000, username="deck"))), \
                patch.object(module, "RootOwnedRuntimeState"), \
                patch.object(module, "Login1SleepInhibitor") as inhibitor, \
                patch.object(module, "WholeDockRuntime", return_value=runtime), \
                patch.object(module, "DockPowerIntentStore"), \
                patch.object(module, "build_live_disconnect_runtime"):
            drm.return_value.scan.return_value = [SimpleNamespace(boot_vga=False, pci_bdf="gpu")]
            inhibitor.return_value.acquire.return_value.active = True
            inhibitor.return_value.status.return_value.active = True
            with self.assertRaisesRegex(ValueError, "dock_power.disconnect_unverified"):
                plugin._run_whole_dock_trial("operation", power_request=request)
        self.assertEqual(plugin._whole_dock_teardown_details, {
            "code": "dock_teardown.unresolved", "tunnel_stage": "settle",
            "tunnel_code": "dock_teardown.tunnel_settle_unverified"})

    def test_settle_reason_survives_power_wrapper_without_raw_exception_text(self):
        for reason, expected in (
                ('dock_teardown.tunnel_settle_timeout', 'dock_teardown.tunnel_settle_timeout'),
                ('private UUID/path', None)):
            self.plugin._remember_teardown_result(
                SimpleNamespace(code='dock_teardown.unresolved'),
                SimpleNamespace(tunnel_stage='settle',
                                tunnel_code='dock_teardown.tunnel_settle_unverified',
                                tunnel_reason=reason))
            self.assertEqual(self.plugin._whole_dock_teardown_details.get('tunnel_reason'),
                             expected)

    def test_sleep_error_rpc_retains_inner_failure_and_resets_next_request(self):
        plugin, module = self.plugin, self.module
        plugin._background_operations = set()
        plugin._unloading = False
        plugin._dock_power_session = "1" * 64 + ":" + "2" * 32

        def fail(*args, **kwargs):
            plugin._set_disconnect_phase("dock_teardown")
            plugin._remember_teardown_result(
                SimpleNamespace(code="dock_teardown.unresolved"),
                SimpleNamespace(tunnel_stage="authorization_hold",
                                tunnel_code="dock_teardown.authorization_hold_unverified"))
            raise ValueError("dock_power.disconnect_unverified")

        plugin._run_dock_power_request = fail
        response = asyncio.run(plugin.execute_egpu_disconnect(
            trial_action="whole_dock_sleep", release_display=True,
            trial_confirmed=True, trial_request_id="d" * 32))
        self.assertEqual(response["code"], "dock_power.disconnect_unverified")
        self.assertEqual(response["teardown"]["tunnel_stage"], "authorization_hold")
        self.assertEqual(response["teardown"]["code"], "dock_teardown.unresolved")
        self.assertIn("dock_teardown", response["phase_timings_ms"])
        self.assertFalse(response["power_requested"])
        self.assertFalse(response["safe_to_unplug"])
        plugin._run_dock_power_request = Mock(side_effect=ValueError("dock_power.preflight_changed"))
        response = asyncio.run(plugin.execute_egpu_disconnect(
            trial_action="whole_dock_sleep", release_display=True,
            trial_confirmed=True, trial_request_id="e" * 32))
        self.assertEqual(response["teardown"], {})


if __name__ == "__main__":
    unittest.main()
