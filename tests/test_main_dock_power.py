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

    def test_power_status_needs_no_runtime_and_never_starts_work(self):
        self.plugin._run_background_operation = Mock()
        self.plugin._run_whole_dock_trial = Mock()
        with patch.object(self.module, 'DrmDiscovery') as discovery:
            result = asyncio.run(self.plugin.get_egpu_power_status())
        self.assertFalse(result['authorizes_action'])
        self.assertEqual(result['actions']['shutdown']['live_readiness'], 'not_assessed')
        self.assertFalse(result['actions']['sleep']['actionable'])
        self.plugin._run_background_operation.assert_not_called()
        self.plugin._run_whole_dock_trial.assert_not_called()
        discovery.assert_not_called()

    def test_sleep_refuses_before_hardware_or_background_work(self):
        self.plugin._run_whole_dock_trial = Mock()
        self.plugin._run_background_operation = Mock()
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            release_display=True, trial_action='whole_dock_sleep', trial_confirmed=True))
        self.assertEqual(result['code'], 'dock_power.sleep_unverified')
        self.plugin._run_whole_dock_trial.assert_not_called()
        self.plugin._run_background_operation.assert_not_called()

    def test_shutdown_still_requires_explicit_confirmation(self):
        self.plugin._run_whole_dock_trial = Mock()
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            release_display=True, trial_action='whole_dock_shutdown'))
        self.assertFalse(result['ok'])
        self.plugin._run_whole_dock_trial.assert_not_called()

    def test_backend_request_and_power_result_are_separate_from_unplug(self):
        self.plugin._run_whole_dock_trial = Mock(return_value=NS(
            code='dock_power.request_accepted_unverified', requested=True))
        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            release_display=True, trial_action='whole_dock_shutdown', trial_confirmed=True))
        self.assertTrue(result['power_requested'])
        self.assertTrue(result['ok'])
        self.assertFalse(result['safe_to_unplug'])
        args, kwargs = self.plugin._run_whole_dock_trial.call_args
        self.assertEqual(args[0], kwargs['power_request'].operation)
        self.assertEqual(kwargs['power_request'].action, 'shutdown')

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
        for failure in ('', 'bind', 'release', 'teardown', 'power', 'unknown_game', 'tv', 'unloading'):
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
                runtime.binding = binding
                runtime._operation = 'owned'
                def event(name, result=True):
                    self.assertTrue(held)
                    events.append(name)
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
                    if failure in ('bind', 'release', 'teardown'):
                        with self.assertRaises(ValueError):
                            self.plugin._run_whole_dock_trial(request.operation, power_request=request)
                        power.request_poweroff.assert_not_called()
                    else:
                        result = self.plugin._run_whole_dock_trial(request.operation, power_request=request)
                        self.assertEqual(result.requested, not failure)
                        if failure in ('unknown_game', 'tv', 'unloading'):
                            power.request_poweroff.assert_not_called()
                lease.release.assert_not_called()
                self.assertFalse(held)
                if not failure:
                    self.assertEqual(events, ['portable', 'claim', 'bind', 'release',
                        'verify_release', 'teardown', 'proof', 'consume', 'proof', 'power'])


if __name__ == '__main__':
    unittest.main()
