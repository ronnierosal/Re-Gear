"""RPC admission is exercised separately from unrelated mocked delivery tests."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module
from tests import test_main_link_recovery as recovery_fixtures
from regear.delivery.dock_mutation_gate import DockMutationDenied


class Denied:
    @contextmanager
    def admit(self):
        raise DockMutationDenied("test.inhibited")
        yield


class MainDockAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)

    def test_whole_dock_trial_holds_admission_across_release(self):
        held = []
        events = []
        @contextmanager
        def admit():
            held.append(True)
            try:
                yield
            finally:
                held.clear()
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        binding = NS(gpu_bdf="gpu", audio_bdf="audio", usb_bdf="usb",
                     router_id="router", binding="binding", generation="generation")
        runtime = Mock()
        release = Mock()
        def step(name):
            def run(*args, **kwargs):
                self.assertTrue(held)
                events.append(name)
                return name
            return run
        runtime.begin_before_release.side_effect = step("claim")
        release.execute.side_effect = step("release")
        runtime.verify_gpu_release.side_effect = step("verify")
        runtime.execute_claimed.side_effect = step("teardown")
        with patch.object(self.module, "DrmDiscovery") as drm, \
                patch.object(self.module, "resolve_whole_dock", return_value=binding), \
                patch.object(self.module, "GamescopeDiscovery"), \
                patch.object(self.module, "resolve_gamescope_user", return_value=NS(context=NS(uid=1000, username="deck"))), \
                patch.object(self.module, "RootOwnedRuntimeState"), \
                patch.object(self.module, "Login1SleepInhibitor") as inhibitor, \
                patch.object(self.module, "WholeDockRuntime", return_value=runtime), \
                patch.object(self.module, "build_live_disconnect_runtime", return_value=release):
            drm.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf="gpu")]
            inhibitor.return_value.acquire.return_value.active = True
            self.assertEqual(self.plugin._run_whole_dock_trial("trial"), "teardown")
        self.assertEqual(events, ["claim", "release", "verify", "teardown"])
        self.assertFalse(held)
        self.assertFalse(self.plugin._whole_dock_trial_runtime[1]["held"])

    def test_reconnect_requires_original_trial(self):
        with self.assertRaises(ValueError):
            self.plugin._run_whole_dock_reconnect_trial()

    def test_changed_attachment_refuses_before_any_release(self):
        from contextlib import nullcontext
        self.plugin._dock_mutation_gate = lambda: NS(admit=nullcontext)
        with patch.object(self.module, "DrmDiscovery") as drm, \
                patch.object(self.module, "resolve_whole_dock", return_value=NS(binding="new", generation="new")), \
                patch.object(self.module, "build_live_disconnect_runtime") as release:
            drm.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf="gpu")]
            with self.assertRaisesRegex(ValueError, "approval_superseded"):
                self.plugin._run_whole_dock_trial("trial", "old:old")
            release.assert_not_called()

    def test_trial_requires_explicit_confirmation(self):
        self.plugin._run_whole_dock_trial = Mock()
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            trial_action="whole_dock_disconnect", release_display=True))
        self.assertFalse(result["ok"])
        self.plugin._run_whole_dock_trial.assert_not_called()

    def test_trial_status_survives_rpc_result_and_never_clears_unplug(self):
        self.plugin._background_operations = set()
        self.plugin._unloading = False
        self.plugin._run_whole_dock_trial = Mock(return_value=NS(
            code="dock_teardown.software_down", software_down=True))
        async def run():
            result = await self.plugin.execute_egpu_disconnect(
                trial_action="whole_dock_disconnect", release_display=True,
                trial_confirmed=True)
            self.assertTrue(result["ok"])
            status = await self.plugin.get_egpu_disconnect_status("whole_dock_trial")
            self.assertEqual(status, result)
            self.assertFalse(status["safe_to_unplug"])
        asyncio.run(run())

    def test_unavailable_factory_never_invokes_mutation(self):
        self.plugin._dock_mutation_gate = Mock(side_effect=OSError("unavailable"))
        command = Mock()
        with self.assertRaises(DockMutationDenied):
            self.plugin._run_dock_mutation(command)
        command.assert_not_called()

    def test_gate_lifetime_covers_entire_operation(self):
        held = []
        @contextmanager
        def admit():
            held.append(True)
            try:
                yield
            finally:
                held.clear()
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        self.assertTrue(self.plugin._run_dock_mutation(lambda: bool(held)))
        self.assertEqual(held, [])

    def test_manual_recovery_refuses_without_calling_service(self):
        fixture = recovery_fixtures.LinkRecoveryStrategySelectionTests()
        fixture.module = self.module
        plugin, service = fixture.executable()
        plugin._dock_mutation_gate = lambda: Denied()
        result = fixture.run_execute(plugin, confirm=True)
        self.assertEqual(result['code'], 'link_recovery.dock_mutation_inhibited')
        self.assertEqual(service.asked_for, [])

    def test_legacy_disconnect_refuses_before_runtime_execution(self):
        runtime = NS(execute=Mock())
        self.plugin._live_disconnect_runtime = lambda: runtime
        self.plugin._dock_mutation_gate = lambda: Denied()
        with patch.object(self.module, 'RelaunchIntentStore'):
            result = asyncio.run(self.plugin.execute_egpu_disconnect())
        self.assertFalse(result['ok'])
        runtime.execute.assert_not_called()

    def test_automatic_recovery_inhibition_does_not_consume_attempt(self):
        from regear.application.automatic_link_recovery import AutomaticLinkRecovery
        from regear.domain.models import GameState
        from tests.test_link_recovery_service import FakeCommands, USER, service
        plugin = self.plugin
        plugin._unloading = False
        plugin._discovery = object()
        plugin._last_readiness_observation = recovery_fixtures.observation(
            transport_identity='transport:known')
        policy = plugin._automatic_link_recovery = AutomaticLinkRecovery()
        facts = dict(absent=False, present=True, identity='transport:known',
                     pci_complete=False, enabled=True, idle=True)
        policy.observe(now=0, **{**facts, 'absent': True, 'present': False})
        policy.observe(now=1, **facts)
        plugin._automatic_recovery_preferences = lambda: NS(load=lambda: True)
        plugin._automatic_dock_preferences = lambda: NS(load=lambda: True)
        plugin._transition_journal_service = lambda: NS(status=lambda: NS(
            durable=True, owner=NS(value='none')))
        plugin._dock_mutation_gate = lambda: Denied()
        current = NS(snapshot=NS(game_state=GameState.IDLE, gamescope=NS(running=True),
            gpus=(NS(role=self.module.GpuRole.INTERNAL, present=True,
                     confidence=self.module.Confidence.VERIFIED),)))
        async def observe(_):
            return recovery_fixtures.status()
        async def background(fn):
            return fn()
        plugin._observe_connection_readiness = observe
        plugin._run_background_operation = background
        plugin._append_journey_event = Mock()
        commands = FakeCommands()
        plugin._link_recovery, _ = service(commands, [True])
        with patch.object(self.module.time, 'monotonic', return_value=11), \
             patch.object(self.module, 'resolve_runtime_profiles', return_value=NS(exact_host=True)), \
             patch.object(self.module, 'GamescopeDiscovery'), \
             patch.object(self.module, 'resolve_gamescope_user', return_value=NS(ok=True, context=USER)), \
             patch.object(self.module, 'SnapshotTransitionObservationAdapter') as adapter:
            adapter.return_value.observe.return_value = current
            self.assertFalse(asyncio.run(plugin._maybe_automatic_link_recovery(current, True)))
        self.assertEqual(commands.calls, [])
        self.assertEqual(policy.attempts, 0)
        self.assertFalse(policy.in_flight)
        plugin._append_journey_event.assert_not_called()


    def test_fixed_failure_reason_and_phase_survive_rpc(self):
        self.plugin._background_operations = set()
        self.plugin._unloading = False
        def fail(*args):
            self.plugin._whole_dock_trial_phase = 'admission'
            raise DockMutationDenied('dock_mutation.inhibited')
        self.plugin._run_whole_dock_trial = fail
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            trial_action='whole_dock_disconnect', release_display=True, trial_confirmed=True))
        self.assertEqual(result['code'], 'dock_mutation.inhibited')
        self.assertEqual(result['phase'], 'admission')
        self.assertEqual(result['release_stage'], 'not_run')
        self.assertFalse(result['safe_to_unplug'])

    def test_record_read_exposes_stage_without_identifiers_or_mutation(self):
        with patch.object(self.module, 'WholeDockClaimStore') as store:
            store.return_value.load.return_value = NS(stage='release_intent', binding='private')
            result = asyncio.run(self.plugin.get_egpu_disconnect_status('whole_dock_record'))
            self.assertEqual(result, {'schema_version':1, 'claim_stage':'release_intent', 'safe_to_unplug':False})
            store.return_value.claim.assert_not_called()
            store.return_value.record.assert_not_called()
    def _capture_fixture(self, *, stage='release_intent', matched=True, idle=True,
                         complete=True, changed_claim=False, timer_ready=True):
        held = []
        @contextmanager
        def admit(*, allow_inhibited=False):
            self.assertTrue(allow_inhibited)
            held.append(True)
            try:
                yield
            finally:
                held.clear()
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        self.plugin._api = NS(get_snapshot_report=lambda: NS(snapshot=NS(
            game_state=self.module.GameState.IDLE if idle else self.module.GameState.UNKNOWN)))
        async def background(fn):
            return fn()
        self.plugin._run_background_operation = background
        claim = NS(stage=stage, binding='bound', generation='generation')
        runtime = Mock()
        def status():
            self.assertTrue(held, 'capture status must run under admission')
            return NS(scan_complete=complete, holders=('systemd-logind.service',))
        runtime.status.side_effect = status
        async def run():
            start = await self.plugin.execute_egpu_disconnect(release_display=True,
                trial_action="whole_dock_capture", trial_confirmed=True)
            self.assertEqual(start['code'], 'release_capture.starting')
            return await self.plugin._release_capture_task
        with patch.object(self.module, 'WholeDockClaimStore') as store, \
                patch.object(self.module, 'DrmDiscovery') as drm, \
                patch.object(self.module, 'resolve_whole_dock', return_value=NS(
                    gpu_bdf='gpu', binding='bound' if matched else 'changed', generation='generation')), \
                patch.object(self.module, 'GamescopeDiscovery'), \
                patch.object(self.module, 'resolve_gamescope_user', return_value=NS(
                    context=NS(uid=1000, username='deck'))), \
                patch.object(self.module, 'build_live_disconnect_runtime', return_value=runtime) as build, \
                patch.object(self.module, 'BrokerCaptureRestoreTimer') as timer, \
                patch.object(self.module.time, 'sleep') as sleep, \
                patch.object(self.module.time, 'monotonic', return_value=0):
            store.return_value.load.side_effect = [claim, None if changed_claim else claim]
            timer.return_value.arm.return_value = timer_ready
            drm.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf='gpu')]
            result = asyncio.run(run())
            store.return_value.claim.assert_not_called()
            store.return_value.record.assert_not_called()
            store.return_value.retire_reconnected.assert_not_called()
            runtime.execute.assert_not_called()
            self.assertFalse(held)
            self.assertEqual(result, self.plugin._release_capture_status)
            return result, build.call_count, runtime.status.call_count, sleep.call_count

    def test_capture_preserves_claim_and_publishes_samples_under_lock(self):
        result, built, observed, sleeps = self._capture_fixture()
        self.assertEqual(result['code'], 'release_capture.complete')
        self.assertEqual(len(result['samples']), 36)
        self.assertEqual(result['samples'][0]['holders'], ['systemd-logind.service'])
        self.assertTrue(all(sample['scan_complete'] for sample in result['samples']))
        self.assertEqual((built, observed, sleeps), (1, 37, 36))

    def test_capture_refuses_mismatched_claim_attachment_or_unknown_idle(self):
        for options in ({'stage': 'software_down'}, {'matched': False}, {'idle': False}):
            with self.subTest(options=options):
                result, built, observed, _ = self._capture_fixture(**options)
                self.assertEqual(result['code'], 'release_capture.unresolved')
                self.assertEqual(result['samples'], [])
                self.assertEqual((built, observed), (0, 0))

    def test_capture_incomplete_preflight_refuses_without_samples(self):
        result, _, observed, _ = self._capture_fixture(complete=False)
        self.assertEqual(result['code'], 'release_capture.unresolved')
        self.assertEqual(result['samples'], [])
        self.assertEqual(observed, 1)

    def test_capture_changed_claim_is_unresolved_and_never_rewritten(self):
        result, _, _, _ = self._capture_fixture(changed_claim=True)
        self.assertEqual(result['code'], 'release_capture.unresolved')
        self.assertEqual(len(result['samples']), 36)

    def test_capture_timer_failure_prevents_timed_observation(self):
        result, _, observed, sleeps = self._capture_fixture(timer_ready=False)
        self.assertEqual(result['code'], 'release_capture.unresolved')
        self.assertEqual(result['samples'], [])
        self.assertEqual((observed, sleeps), (1, 0))

    def test_capture_requires_exact_confirmation_and_refuses_busy(self):
        self.plugin._run_background_operation = Mock()
        for confirmation in (False, 1, 'yes'):
            result = asyncio.run(self.plugin._capture_egpu_release_diagnostics(confirmation))
            self.assertEqual(result['code'], 'release_capture.not_started')
        self.plugin._unloading = True
        self.assertEqual(asyncio.run(self.plugin._capture_egpu_release_diagnostics(True))['code'],
                         'release_capture.not_started')
        self.plugin._unloading = False
        self.plugin._release_capture_task = NS(done=lambda: False)
        self.assertEqual(asyncio.run(self.plugin._capture_egpu_release_diagnostics(True))['code'],
                         'release_capture.busy')
        self.plugin._run_background_operation.assert_not_called()

if __name__ == '__main__':
    unittest.main()

class HeldCaptureIntegrationTests(unittest.TestCase):
    setUp = MainDockAdmissionTests.setUp

    def fixture(self, *, timer_ready=True, hold_ready=True, clear=True, restore_ready=True, observe_error=False):
        self.plugin._api = NS(get_snapshot_report=lambda: NS(snapshot=NS(game_state=self.module.GameState.IDLE)))
        calls = []
        def call(action, *args):
            calls.append(action)
            if action == 'prepare':
                return {'code': 'held_helper.prepared', 'pins': {'test': 'pins'}}
            if action == 'restore':
                return {'restored': restore_ready}
            if action == 'status':
                return {'code': 'held_helper.status', 'held': hold_ready}
            return {'code': 'held_helper.held' if hold_ready else 'held_helper.refused'}
        runtime = Mock()
        runtime.status.return_value = NS(scan_complete=True, holders=() if clear else ('wireplumber.service',))
        if observe_error:
            runtime.status.side_effect = ValueError('observation failed')
        with patch.object(self.module, 'HeldTrialLauncher') as launcher, patch.object(self.module, 'HeldTrialRestoreTimer') as timer, patch.object(self.module.time, 'sleep'):
            launcher.return_value.call.side_effect = call
            timer.return_value.arm.return_value = timer_ready
            timer.return_value.active.return_value = timer_ready
            if observe_error:
                with self.assertRaises(ValueError):
                    self.plugin._run_held_session_capture(NS(uid=1000, username='deck'), 'a'*32, runtime, [])
                result = None
            else:
                result = self.plugin._run_held_session_capture(NS(uid=1000, username='deck'), 'a'*32, runtime, [])
        return result, calls

    def test_held_capture_success_restores_without_unplug_clearance(self):
        result, calls = self.fixture()
        self.assertEqual(result['code'], 'release_capture.held_clear_restored')
        self.assertFalse(result['safe_to_unplug'])
        self.assertEqual(calls, ['prepare', 'hold', 'status', 'status', 'restore'])

    def test_no_hold_without_independent_timer(self):
        result, calls = self.fixture(timer_ready=False)
        self.assertNotIn('hold', calls)
        self.assertEqual(calls[-1], 'restore')
        self.assertFalse(result.get('clear_observed', False))

    def test_restore_after_hold_failure_and_observer_exception(self):
        for options in ({'hold_ready':False}, {'observe_error':True}):
            _, calls = self.fixture(**options)
            self.assertEqual(calls[-1], 'restore')

    def test_failed_restore_never_claims_success(self):
        result, _ = self.fixture(restore_ready=False)
        self.assertEqual(result['code'], 'release_capture.unresolved')
        self.assertFalse(result['session_restored'])
