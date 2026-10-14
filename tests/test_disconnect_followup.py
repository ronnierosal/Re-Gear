"""Retained authorization cleanup and disconnect diagnostic regressions."""
import asyncio
import unittest
import subprocess
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

    def test_suspend_dispatch_does_not_retry_session_or_ambiguous_refusal(self):
        from regear.adapters.steamos.commands import SystemSuspendCommandRunner
        for outcome, code in (
            (subprocess.CompletedProcess([], 1, b"", b"User deck is logged in; close inhibitors"),
             "dock_power.suspend_failed"),
            (subprocess.TimeoutExpired("busctl", 5), "dock_power.suspend_timeout"),
        ):
            with self.subTest(code=code), patch.object(
                    self.module, "SystemSuspendCommandRunner",
                    side_effect=lambda: SystemSuspendCommandRunner(effective_uid=lambda: 0)), patch(
                    "regear.adapters.steamos.commands.subprocess.run") as run:
                if isinstance(outcome, Exception):
                    run.side_effect = outcome
                else:
                    run.return_value = outcome
                self.assertFalse(self.plugin._submit_suspend(object()))
                run.assert_called_once()
                self.assertEqual(self.plugin._whole_dock_suspend_result,
                                 {"requested": False, "code": code, "attempts": 1})

    def test_expired_active_sleep_wait_is_projected_without_replaying_work(self):
        plugin = self.plugin
        request = "a" * 32
        plugin._whole_dock_trial_worker_alive = True
        plugin._whole_dock_trial_phase = "power_verification"
        plugin._whole_dock_trial_started = 10.0
        retained = {"schema_version": 1, "code": "dock_teardown.trial_running",
                    "busy": True, "safe_to_unplug": False, "request_id": request}
        plugin._whole_dock_trial_status = retained.copy()
        progress = {"schema_version": 1, "code": "dock_power.unplug_request_expired",
                    "busy": True, "ok": False, "safe_to_unplug": False,
                    "software_down": True, "unplug_required": True,
                    "power_action": "sleep", "power_requested": False,
                    "route_action": "whole_dock_sleep", "request_id": request}
        plugin._dock_sleep_status = progress.copy()
        plugin._run_sleep_request = Mock()
        with patch.object(self.module.time, "monotonic", return_value=320.0):
            result = asyncio.run(plugin.get_egpu_disconnect_status("whole_dock_trial"))
        self.assertEqual(result["code"], progress["code"])
        self.assertEqual(result["phase"], "power_verification")
        self.assertTrue(result["in_flight"])
        self.assertFalse(result["power_requested"])
        self.assertEqual(plugin._dock_sleep_status, progress)
        self.assertEqual(plugin._whole_dock_trial_status, retained)
        plugin._run_sleep_request.assert_not_called()
        for field, wrong in (("request_id", "b" * 32),
                             ("route_action", "whole_dock_disconnect"),
                             ("software_down", False), ("busy", False)):
            with self.subTest(field=field):
                plugin._dock_sleep_status = {**progress, field: wrong}
                result = asyncio.run(plugin.get_egpu_disconnect_status("whole_dock_trial"))
                self.assertEqual(result["code"], retained["code"])

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

    def test_remaining_pci_payload_is_bounded_and_category_only(self):
        valid = {'bridges': 3, 'endpoints': 0, 'unreadable': 0}
        for counts in (valid, dict(valid, private='path'), dict(valid, bridges=True),
                       dict(valid, bridges=1025), dict(valid, bridges=-1)):
            self.plugin._remember_teardown_result(
                SimpleNamespace(code='dock_teardown.unresolved'),
                SimpleNamespace(tunnel_stage='settle',
                                tunnel_code='dock_teardown.tunnel_settle_unverified',
                                remaining_pci=counts))
            actual = self.plugin._whole_dock_teardown_details.get('remaining_pci')
            self.assertEqual(actual, valid if counts is valid else None)

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


class PortableEvidenceReplanTests(unittest.TestCase):
    def fixture(self, *, generations=("a", "b", "b", "b"), direct=None,
                game_on_repreview=False):
        from tests.test_supervised_transition import (
            service, Observations, VersionedObservation, snapshot,
            ExperimentalTransitionApprovalStore)
        fixture = dock_support.PortableBeforeDisconnectTests()
        fixture.setUp()
        values = [VersionedObservation(g, snapshot("tv-docked.json",
            game_state="running" if game_on_repreview and i >= 2 else None))
            for i, g in enumerate(generations)]
        actual, orchestrator, _ = service(Observations(*values))
        actual._identifier = iter(f"operation-{i:04d}" for i in range(20)).__next__
        actual._approvals = ExperimentalTransitionApprovalStore(
            ttl_seconds=30, monotonic=lambda: 10,
            token_factory=iter(f"experimental_token_{i:04d}" for i in range(10)).__next__)
        boundary = Mock(wraps=actual)
        boundary.status.return_value = SimpleNamespace(durable=True,
            target=fixture.module.PlacementState.PORTABLE, operation_id="operation-0002",
            acknowledgement_required=False)
        boundary.acknowledge.return_value = True
        if direct is not None:
            boundary.execute.return_value = direct
        passed, _ = fixture.fixture(service_override=boundary)
        return passed, fixture.plugin, boundary, orchestrator

    def test_real_service_changed_evidence_repreviews_before_one_dispatch(self):
        passed, _, boundary, orchestrator = self.fixture()
        self.assertTrue(passed)
        self.assertEqual(boundary.preview.call_count, 2)
        self.assertEqual(boundary.execute.call_count, 2)
        self.assertNotEqual(boundary.execute.call_args_list[0], boundary.execute.call_args_list[1])
        self.assertEqual(len(orchestrator.plans), 1)
        self.assertEqual(orchestrator.plans[0].plan_id, "operation-0002")

    def test_real_service_repreview_refuses_lost_readiness_without_dispatch(self):
        passed, _, boundary, orchestrator = self.fixture(game_on_repreview=True)
        self.assertFalse(passed)
        self.assertEqual(boundary.preview.call_count, 2)
        self.assertEqual(boundary.execute.call_count, 1)
        self.assertEqual(orchestrator.plans, [])

    def test_real_service_churn_is_bounded_without_dispatch(self):
        passed, plugin, boundary, orchestrator = self.fixture(
            generations=("a", "b", "c", "d", "e", "f"))
        self.assertFalse(passed)
        self.assertEqual(boundary.execute.call_count, 3)
        self.assertEqual(orchestrator.plans, [])
        self.assertEqual(plugin._whole_dock_portable_outcome,
            {"kind": "refused", "code": "transition.evidence_changed", "attempts": 3})

    def test_other_or_ambiguous_direct_refusals_do_not_retry(self):
        from regear.application.supervised_transition import SupervisedTransitionExecution
        cases = [(False, "transition.concurrent_request", ""),
                 (False, "audio.recovery_required", ""),
                 (False, "transition.preconditions_changed", ""),
                 (False, "private/path", ""),
                 (False, "transition.evidence_changed", "started-operation"),
                 (True, "transition.evidence_changed", "")]
        for accepted, code, operation in cases:
            with self.subTest(code=code, accepted=accepted, operation=operation):
                passed, plugin, boundary, orchestrator = self.fixture(
                    direct=SupervisedTransitionExecution(accepted, code, operation))
                self.assertFalse(passed)
                self.assertEqual(boundary.execute.call_count, 1)
                self.assertEqual(orchestrator.plans, [])
                self.assertEqual(plugin._whole_dock_portable_outcome["code"],
                    "" if code == "private/path" else code)


class DisplayAcknowledgementRecoveryTests(unittest.TestCase):
    def test_real_terminal_ack_rearms_failure_but_preserves_successful_handheld_choice(self):
        from tests.test_supervised_transition import (service, Observations,
            TransitionJournal, append_journal_entry, JournalEventKind,
            WorkflowState, PlacementState)
        from regear.application.automatic_dock import AutomaticDockCoordinator
        for kind in (JournalEventKind.BLOCKED, JournalEventKind.FAILED, JournalEventKind.COMMITTED):
            for correct_id in (True, False):
                with self.subTest(kind=kind, correct_id=correct_id):
                    fixture = dock_support.MainDockAdmissionTests(); fixture.setUp()
                    plugin = fixture.plugin
                    journal = append_journal_entry(TransitionJournal("operation-0001", "request-0001"),
                        kind=JournalEventKind.REQUESTED, occurred_at="2026-09-30T00:00:00Z",
                        workflow_state=WorkflowState.IDLE, placement=PlacementState.DOCKED_EGPU,
                        code="request.accepted", details=(("capability", "presentation_transition"),
                            ("target_placement", "portable")))
                    if kind is JournalEventKind.COMMITTED:
                        for step in (JournalEventKind.OBSERVED, JournalEventKind.VALIDATED, JournalEventKind.PLANNED):
                            journal = append_journal_entry(journal, kind=step,
                                occurred_at="2026-09-30T00:00:00Z", workflow_state=WorkflowState.RETURNING_TO_PORTABLE,
                                placement=PlacementState.DOCKED_EGPU, code="plan." + step.value)
                    journal = append_journal_entry(journal, kind=kind,
                        occurred_at="2026-09-30T00:00:01Z", workflow_state=WorkflowState.IDLE,
                        placement=PlacementState.PORTABLE, code="transition." + kind.value)
                    actual, orchestrator, store = service(Observations(), journal=journal)
                    store.retire_committed = store.clear_terminal
                    plugin._presentation_transition_service = lambda: actual
                    plugin._automatic_dock = AutomaticDockCoordinator()
                    plugin._automatic_dock.suppress_current_attachment_after_portable_return()
                    plugin._topology_wakeup = Mock()
                    result = asyncio.run(plugin.acknowledge_supervised_tv_switch(
                        "operation-0001" if correct_id else "operation-9999"))
                    self.assertEqual(result["acknowledged"], correct_id)
                    self.assertEqual(plugin._automatic_dock._attempted,
                        not correct_id or kind is JournalEventKind.COMMITTED)
                    self.assertEqual(store.current is None, correct_id)
                    self.assertEqual(orchestrator.plans, [], "Acknowledgement must not dispatch")
                    self.assertEqual(plugin._topology_wakeup.invalidate.call_count, int(correct_id))
