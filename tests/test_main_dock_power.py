"""Backend entry and ordered power continuation; no hardware commands."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


class MainDockPowerTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._background_operations = set()
        self.plugin._unloading = False
        boot = patch.object(self.module, 'read_boot_hash', return_value='b' * 64)
        boot.start()
        self.addCleanup(boot.stop)

    def test_absent_dock_shutdown_skips_teardown_and_submits_once(self):
        @contextmanager
        def admit(**kwargs):
            yield
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        self.plugin._run_whole_dock_trial = Mock()
        request = self.module.create_power_request('shutdown', 'session')
        with patch.object(self.module, 'verified_transport_absent', return_value=True), \
             patch.object(self.module, 'SystemPowerCommandRunner') as runner:
            runner.return_value.request_poweroff.return_value = NS(
                requested=True, code='safe_disconnect.poweroff_request_accepted_unverified')
            self.assertTrue(self.plugin._run_dock_power_request(request).requested)
            self.assertFalse(self.plugin._run_dock_power_request(request).requested)
            runner.return_value.request_poweroff.assert_called_once()
        self.plugin._run_whole_dock_trial.assert_not_called()

    def test_dock_arrival_during_ordinary_power_classification_does_not_submit(self):
        @contextmanager
        def admit(**kwargs):
            yield
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        request = self.module.create_power_request('shutdown', 'session')
        with patch.object(self.module, 'verified_transport_absent', side_effect=[True, False]), \
             patch.object(self.module, 'SystemPowerCommandRunner') as runner:
            with self.assertRaisesRegex(ValueError, 'preflight_changed'):
                self.plugin._run_dock_power_request(request)
            runner.assert_not_called()

    def test_attached_dock_power_uses_existing_teardown_with_original_request(self):
        request = self.module.create_power_request('shutdown', 'session')
        self.plugin._run_whole_dock_trial = Mock(return_value='existing-result')
        with patch.object(self.module, 'verified_transport_absent', return_value=False):
            self.assertEqual(self.plugin._run_dock_power_request(request), 'existing-result')
        self.plugin._run_whole_dock_trial.assert_called_once_with(
            request.operation, '', power_request=request)

    def test_already_down_shutdown_verifies_release_without_repeating_removal(self):
        @contextmanager
        def admit(**kwargs):
            yield
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        self.plugin._dock_power_portable_verified = lambda: True
        admission = {'held': False}
        runtime = NS(_operation='original-disconnect', _owned=lambda stage: True,
            verify_power_continuation=Mock(side_effect=lambda *a, **k: admission['held']))
        self.plugin._whole_dock_trial_runtime = (runtime, admission)
        self.plugin._run_whole_dock_trial = Mock()
        request = self.module.create_power_request('shutdown', 'session')
        with patch.object(self.module, 'verified_transport_absent', return_value=False), \
             patch.object(self.module, 'SystemPowerCommandRunner') as runner:
            runner.return_value.request_poweroff.return_value = NS(requested=True, code='accepted')
            result = self.plugin._run_dock_power_request(request)
            self.assertTrue(result.requested)
            self.assertTrue(result.software_down)
            self.assertFalse(admission['held'])
            runner.return_value.request_poweroff.assert_called_once()
        self.plugin._run_whole_dock_trial.assert_not_called()
        runtime.verify_power_continuation.assert_called_once_with('original-disconnect',
            portable_verified=self.plugin._dock_power_portable_verified)

    def test_ordinary_shutdown_timeout_is_not_replayed(self):
        @contextmanager
        def admit(**kwargs):
            yield
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        request = self.module.create_power_request('shutdown', 'session')
        with patch.object(self.module, 'verified_transport_absent', return_value=True), \
             patch.object(self.module, 'SystemPowerCommandRunner') as runner:
            runner.return_value.request_poweroff.side_effect = TimeoutError()
            with self.assertRaises(TimeoutError):
                self.plugin._run_dock_power_request(request)
            self.assertFalse(self.plugin._run_dock_power_request(request).requested)
            runner.return_value.request_poweroff.assert_called_once()

    def test_operator_reset_requires_fresh_single_use_preview_and_literal_attestation(self):
        calls = []
        async def background(fn, *args):
            calls.append('background')
            return fn(*args)
        self.plugin._run_background_operation = background
        def record(confirm=None, still_confirmed=lambda: True):
            if confirm is None:
                return {'ready': True, 'record_digest': 'a' * 64}
            return {'ok': confirm('a' * 64, 120), 'hardware_write': False}
        self.plugin._operator_reset_record = record
        async def trial():
            preview = await self.plugin.get_egpu_disconnect_status('physical_reset_preview')
            token = preview['confirmation_token']
            refused = await self.plugin._reconcile_egpu_after_physical_reset(token, 1)
            self.assertFalse(refused['ok'])
            refused = await self.plugin._reconcile_egpu_after_physical_reset('wrong', True)
            self.assertFalse(refused['ok'])
            self.assertTrue((await self.plugin._reconcile_egpu_after_physical_reset(token, True))['ok'])
            self.assertFalse((await self.plugin._reconcile_egpu_after_physical_reset(token, True))['ok'])
        asyncio.run(trial())
        self.assertEqual(calls, ['background', 'background'])

    def test_operator_reset_public_route_requires_separate_physical_attestation(self):
        from unittest.mock import AsyncMock
        self.plugin._reconcile_egpu_after_physical_reset = AsyncMock(return_value={'ok': True})
        base = dict(trial_action='whole_dock_physical_reset', trial_confirmed=True,
                    trial_request_id='a' * 32, release_display=False)
        self.assertFalse(asyncio.run(self.plugin.execute_egpu_disconnect(**base))['ok'])
        self.plugin._reconcile_egpu_after_physical_reset.assert_not_called()
        self.assertTrue(asyncio.run(self.plugin.execute_egpu_disconnect(
            **base, physical_reset_confirmed=True))['ok'])
        self.plugin._reconcile_egpu_after_physical_reset.assert_awaited_once_with('a' * 32, True)

    def test_operator_reset_expired_or_busy_preview_never_dispatches(self):
        self.plugin._run_background_operation = Mock()
        self.plugin._operator_reset_preview = ('token', 'digest', 0)
        result = asyncio.run(self.plugin._reconcile_egpu_after_physical_reset('token', True))
        self.assertEqual(result['code'], 'dock_reset.busy_or_expired')
        self.plugin._run_background_operation.assert_not_called()
        self.plugin._background_operations = {object()}
        result = asyncio.run(self.plugin.get_egpu_disconnect_status('physical_reset_preview'))
        self.assertFalse(result['ready'])
        self.plugin._run_background_operation.assert_not_called()

    def test_operator_reset_changed_observation_digest_refuses(self):
        async def background(fn, *args):
            return fn(*args)
        self.plugin._run_background_operation = background
        self.plugin._operator_reset_preview = ('token', 'a' * 64, float('inf'))
        self.plugin._operator_reset_record = lambda confirm, still_confirmed: {'ok': confirm('b' * 64, 120)}
        result = asyncio.run(self.plugin._reconcile_egpu_after_physical_reset('token', True))
        self.assertFalse(result['ok'])
        self.assertIsNone(self.plugin._operator_reset_preview)

    def test_operator_reset_rechecks_expiry_and_unload_during_final_observation(self):
        for change in ('expiry', 'unload'):
            with self.subTest(change=change):
                self.plugin._unloading = False
                self.plugin._operator_reset_preview = ('token', 'a' * 64, 120)
                clock = [0]
                async def background(fn, *args):
                    return fn(*args)
                self.plugin._run_background_operation = background
                def record(confirm, still_confirmed):
                    self.assertTrue(confirm('a' * 64, 120))
                    if change == 'expiry':
                        clock[0] = 121
                    else:
                        self.plugin._unloading = True
                    return {'ok': still_confirmed()}
                self.plugin._operator_reset_record = record
                with patch.object(self.module.time, 'monotonic', side_effect=lambda: clock[0]):
                    result = asyncio.run(self.plugin._reconcile_egpu_after_physical_reset('token', True))
                self.assertFalse(result['ok'])

    def test_power_status_needs_no_runtime_and_never_starts_work(self):
        self.plugin._run_background_operation = Mock()
        self.plugin._run_whole_dock_trial = Mock()
        with patch.object(self.module, 'DrmDiscovery') as discovery:
            result = asyncio.run(self.plugin.get_egpu_disconnect_status("power_capabilities"))
        self.assertFalse(result['authorizes_action'])
        self.assertEqual(result['actions']['shutdown']['live_readiness'], 'not_assessed')
        self.assertFalse(result['actions']['sleep']['actionable'])
        self.plugin._run_background_operation.assert_not_called()
        self.plugin._run_whole_dock_trial.assert_not_called()
        discovery.assert_not_called()

    def test_sleep_missing_observer_does_not_start_teardown(self):
        self.plugin._run_whole_dock_trial = Mock()
        async def background(fn):
            return fn()
        self.plugin._run_background_operation = background
        with patch.object(self.module, 'SuspendObserver') as observer:
            observer.return_value.read.return_value = None
            result = asyncio.run(self.plugin.execute_egpu_disconnect(
                release_display=True, trial_action='whole_dock_sleep', trial_confirmed=True))
        self.assertEqual(result['code'], 'dock_power.sleep_observer_unavailable')
        self.plugin._run_whole_dock_trial.assert_not_called()

    def test_sleep_keep_connected_selects_sleep_without_teardown(self):
        @contextmanager
        def admit(**kwargs):
            yield
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        self.plugin._run_sleep_request = Mock(return_value=NS(code='sleep', requested=True))
        self.plugin._run_whole_dock_trial = Mock()
        async def background(fn):
            return fn()
        self.plugin._run_background_operation = background
        with patch.object(self.module, 'SuspendObserver') as observer, \
             patch.object(self.module, 'verified_transport_absent', return_value=False):
            observer.return_value.read.return_value = object()
            result = asyncio.run(self.plugin.execute_egpu_disconnect(
                release_display=True, trial_action='whole_dock_sleep_connected', trial_confirmed=True))
        self.assertTrue(result['power_requested'])
        self.assertEqual(result['power_action'], 'sleep')
        self.assertEqual(self.plugin._run_sleep_request.call_args.args[0].action, 'sleep')
        self.plugin._run_whole_dock_trial.assert_not_called()

    def test_sleep_after_down_uses_actual_two_leases_and_consumes_before_submit(self):
        from tests.test_dock_sleep_lease import Process
        request = self.module.create_power_request('sleep', 'session')
        self.plugin._dock_power_session = request.session
        self.plugin._sleep_guard = self.module.SleepGuardController(
            self.module.Login1SleepInhibitor(Process))
        self.plugin._whole_dock_trial_lease = self.module.Login1SleepInhibitor(Process)
        self.plugin._whole_dock_trial_lease.acquire()
        self.plugin._dock_power_portable_verified = lambda: True
        admission = {'held': True}
        events = []
        runtime = NS(_operation=request.operation, binding=NS(binding='dock', generation='gen'),
            verify_power_continuation=lambda *a, **k: admission['held'] and admission['power_handoff'])
        store = NS(consume=lambda *args: events.append('consume') or True)
        def submit():
            self.assertEqual(events, ['consume'])
            self.assertFalse(self.plugin._sleep_guard.status().active)
            self.assertFalse(self.plugin._whole_dock_trial_lease.status().active)
            events.append('submit')
            return NS(requested=True)
        with patch.object(self.module, 'SuspendObserver') as observer, \
             patch.object(self.module, 'SystemSuspendCommandRunner') as command:
            observer.return_value.read.return_value = object()
            observer.return_value.classify.return_value = 'success'
            command.return_value.request_suspend.side_effect = submit
            result = self.plugin._sleep_after_dock_down(request, runtime, admission, store)
        self.assertEqual(result.code, 'dock_power.sleep_cycle_observed')
        self.assertEqual(events, ['consume', 'submit'])
        self.assertTrue(self.plugin._whole_dock_trial_lease.status().active)
        self.assertFalse(admission['power_handoff'])

    def test_completed_power_correlation_does_not_submit_again_or_change_action(self):
        self.plugin._run_dock_power_request = Mock(return_value=NS(code='accepted', requested=True))
        async def background(fn):
            return fn()
        self.plugin._run_background_operation = background
        args = dict(release_display=True, trial_action='whole_dock_shutdown',
                    trial_confirmed=True, trial_request_id='c' * 32)
        first = asyncio.run(self.plugin.execute_egpu_disconnect(**args))
        status = asyncio.run(self.plugin.get_egpu_disconnect_status('power_status'))
        self.assertEqual(status['request_id'], args['trial_request_id'])
        self.assertEqual(status['route_action'], 'whole_dock_shutdown')
        self.assertEqual(status['power_action'], 'shutdown')
        self.assertFalse(status['busy'])
        self.assertEqual(asyncio.run(self.plugin.execute_egpu_disconnect(**args)), first)
        args['trial_action'] = 'whole_dock_sleep'
        self.assertEqual(asyncio.run(self.plugin.execute_egpu_disconnect(**args))['code'],
                         'dock_power.request_action_changed')
        self.plugin._run_dock_power_request.assert_called_once()

    def test_shutdown_still_requires_explicit_confirmation(self):
        self.plugin._run_whole_dock_trial = Mock()
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            release_display=True, trial_action='whole_dock_shutdown'))
        self.assertFalse(result['ok'])
        self.plugin._run_whole_dock_trial.assert_not_called()

    def test_backend_request_and_power_result_are_separate_from_unplug(self):
        self.plugin._run_whole_dock_trial = Mock(return_value=NS(
            code='dock_power.request_accepted_unverified', requested=True,
            software_down=True))
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            release_display=True, trial_action='whole_dock_shutdown', trial_confirmed=True))
        self.assertTrue(result['power_requested'])
        self.assertTrue(result['ok'])
        self.assertTrue(result['software_down'])
        self.assertFalse(result['safe_to_unplug'])
        args, kwargs = self.plugin._run_whole_dock_trial.call_args
        self.assertEqual(args[0], kwargs['power_request'].operation)
        self.assertEqual(kwargs['power_request'].action, 'shutdown')

    def test_failed_power_submission_preserves_verified_software_down_status(self):
        self.plugin._run_whole_dock_trial = Mock(return_value=NS(
            code='dock_power.request_unverified', requested=False,
            software_down=True))
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            release_display=True, trial_action='whole_dock_shutdown', trial_confirmed=True))
        self.assertTrue(result['software_down'])
        self.assertFalse(result['power_requested'])
        self.assertFalse(result['ok'])
        self.assertFalse(result['safe_to_unplug'])

    def test_new_boot_reconciliation_checks_live_evidence_before_archive(self):
        from contextlib import nullcontext
        for invalid in ('', 'inner', 'game', 'topology', 'journal'):
            with self.subTest(invalid=invalid):
                self.plugin._dock_mutation_gate = lambda: NS(admit=lambda **kw: nullcontext())
                self.plugin._discovery = Mock()
                self.plugin._transition_journal_service = lambda: NS(status=lambda: NS(
                    durable=True, owner=NS(value='active' if invalid == 'journal' else 'none')))
                claim = NS(stage='software_down', binding='dock')
                store = Mock()
                store.load.return_value = claim
                store.retire_after_boot.side_effect = lambda expected, boot, guard: guard()
                snapshot = NS(game_state=self.module.GameState.UNKNOWN if invalid == 'game'
                    else self.module.GameState.IDLE, gamescope=NS(running=True))
                topology = NS(binding='dock', generation='new')
                user = NS(uid=1000, username='deck')
                with patch.object(self.module, 'DockPowerIntentStore', return_value=store), \
                    patch.object(self.module, 'DrmDiscovery') as drm, \
                    patch.object(self.module, 'resolve_transport', side_effect=[topology,
                        NS(binding='dock', generation='changed') if invalid == 'topology' else topology]), \
                    patch.object(self.module, 'GamescopeDiscovery'), \
                    patch.object(self.module, 'resolve_gamescope_user', return_value=NS(ok=True, context=user)), \
                    patch.object(self.module, 'SnapshotTransitionObservationAdapter') as observer, \
                    patch.object(self.module, 'resolve_runtime_profiles', return_value=NS(exact_host=True)), \
                    patch.object(self.module, 'inner_removal_records_absent', return_value=invalid != 'inner'), \
                    patch.object(self.module, 'HeldTrialLauncher') as launcher:
                    drm.return_value.scan.return_value = []
                    observer.return_value.observe.return_value.snapshot = snapshot
                    launcher.return_value.call.return_value = {'code': 'held_helper.settled', 'settled': True}
                    self.assertEqual(self.plugin._reconcile_dock_power_after_boot(), not invalid)

    def test_reconciled_new_boot_retries_ordinary_gate_without_reset(self):
        from regear.delivery.dock_mutation_gate import DockMutationDenied
        for recovery in (True, False):
            self.plugin._reconcile_dock_power_after_boot = Mock(return_value=True)
            self.plugin._run_dock_mutation = Mock(side_effect=[
                DockMutationDenied('dock_mutation.inhibited'), 'ordinary-result'])
            self.plugin._automatic_dock = Mock()
            if recovery:
                result = self.plugin._run_automatic_connection_recovery(Mock(), NS())
            else:
                result = self.plugin._run_automatic_tv_transition('generation', True)
            self.assertEqual(result, 'ordinary-result')
            self.assertEqual(self.plugin._run_dock_mutation.call_count, 2)
            self.plugin._automatic_dock.reset_after_acknowledgement.assert_not_called()

    def test_shutdown_order_and_failures_retain_inhibition(self):
        for failure in ('', 'bind', 'release', 'teardown', 'power', 'unknown_game',
                        'tv', 'unloading', 'lease_lost_portable', 'lease_lost_after_consume'):
            with self.subTest(failure=failure):
                events, held = [], []
                @contextmanager
                def admit():
                    held.append(True)
                    try:
                        yield
                    finally:
                        held.clear()
                self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
                binding = NS(gpu_bdf='gpu', audio_bdf='audio', usb_bdf='usb',
                    router_id='router', binding='binding', generation='generation')
                runtime, release, store, lease = Mock(), Mock(), Mock(), Mock()
                inhibitor = {'active': True}
                runtime.binding = binding
                runtime._operation = 'owned'
                def event(name, result=True):
                    self.assertTrue(held)
                    events.append(name)
                    if ((failure == 'lease_lost_portable' and name == 'portable')
                            or (failure == 'lease_lost_after_consume' and name == 'consume')):
                        inhibitor['active'] = False
                    if failure == name:
                        raise ValueError('injected failure')
                    return result
                self.plugin._return_portable_before_disconnect = lambda *a: event('portable')
                def begin(*args, before_release):
                    event('claim')
                    if before_release() is not True:
                        raise ValueError('bind refused')
                runtime.begin_before_release.side_effect = begin
                store.bind.side_effect = lambda *a: event('bind')
                release.execute.side_effect = lambda **kw: event('release', NS())
                runtime.verify_gpu_release.side_effect = lambda result: event('verify_release')
                runtime.execute_claimed.side_effect = lambda *a: event('teardown', NS(software_down=True))
                def proof(operation, *, portable_verified):
                    event('proof')
                    return portable_verified()
                runtime.verify_power_continuation.side_effect = proof
                store.consume.side_effect = lambda *a: event('consume')
                power = Mock()
                power.request_poweroff.side_effect = lambda: event('power', NS(requested=True))
                lease.acquire.return_value.active = True
                lease.status.side_effect = lambda: NS(active=inhibitor['active'])
                request = self.module.create_power_request('shutdown', 'a' * 32)
                snapshot = NS(game_state=self.module.GameState.UNKNOWN if failure == 'unknown_game'
                    else self.module.GameState.IDLE)
                self.plugin._discovery = Mock()
                self.plugin._unloading = failure == 'unloading'
                with patch.object(self.module, 'DrmDiscovery') as drm, \
                    patch.object(self.module, 'resolve_whole_dock', return_value=binding), \
                    patch.object(self.module, 'GamescopeDiscovery'), \
                    patch.object(self.module, 'resolve_gamescope_user', return_value=NS(context=NS(uid=1000, username='deck'))), \
                    patch.object(self.module, 'RootOwnedRuntimeState'), \
                    patch.object(self.module, 'Login1SleepInhibitor', return_value=lease), \
                    patch.object(self.module, 'WholeDockRuntime', return_value=runtime), \
                    patch.object(self.module, 'DockPowerIntentStore', return_value=store), \
                    patch.object(self.module, 'SystemPowerCommandRunner', return_value=power), \
                    patch.object(self.module, 'SnapshotTransitionObservationAdapter') as observer, \
                    patch.object(self.module, 'infer_operating_mode', return_value=NS(
                        mode=None if failure == 'tv' else self.module.OperatingMode.PORTABLE)), \
                    patch.object(self.module, 'build_live_disconnect_runtime', return_value=release):
                    drm.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf='gpu')]
                    observer.return_value.observe.return_value.snapshot = snapshot
                    if failure in ('bind', 'release', 'teardown', 'lease_lost_portable', 'unloading'):
                        with self.assertRaises(ValueError):
                            self.plugin._run_whole_dock_trial(request.operation, power_request=request)
                        power.request_poweroff.assert_not_called()
                        if failure in ('lease_lost_portable', 'unloading'):
                            release.execute.assert_not_called()
                            runtime.execute_claimed.assert_not_called()
                            store.consume.assert_not_called()
                    else:
                        result = self.plugin._run_whole_dock_trial(request.operation, power_request=request)
                        self.assertEqual(result.requested, not failure)
                        self.assertIs(getattr(result, 'software_down', None), True)
                        if failure in ('unknown_game', 'tv', 'lease_lost_after_consume'):
                            power.request_poweroff.assert_not_called()
                        if failure == 'lease_lost_after_consume':
                            store.consume.assert_called_once()
                            self.assertIn('teardown', events)
                lease.release.assert_not_called()
                self.assertFalse(held)
                if not failure:
                    self.assertEqual(events, ['portable', 'claim', 'bind', 'release',
                        'verify_release', 'teardown', 'proof', 'consume', 'proof', 'power'])


if __name__ == '__main__':
    unittest.main()
