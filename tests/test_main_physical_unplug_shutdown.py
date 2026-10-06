"""Actual production shutdown waiter with secure persisted one-shot intents."""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


class MainPhysicalUnplugShutdownTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._whole_dock_trial_worker_alive = True
        self.boot = '1' * 64
        self.request = self.module.DockPowerRequest('a' * 32, 'shutdown',
            self.boot + ':' + '2' * 32, 10, 20)
        self.plugin._dock_power_session = self.request.session
        self.plugin._dock_power_context = (self.request, '3' * 32, 'whole_dock_shutdown')
        self.runtime = NS(_operation=self.request.operation,
            binding=NS(binding='b' * 64, generation='c' * 64))
        self.admission = {'held': True}
        self.plugin._whole_dock_trial_lease = Mock()
        self.plugin._whole_dock_trial_lease.status.return_value = NS(active=True)
        self.plugin._whole_dock_trial_lease.release.return_value = NS(active=False)
        self.plugin._whole_dock_trial_runtime = (self.runtime, self.admission)
        self.plugin._dock_power_portable_verified = Mock(return_value=True)
        self.plugin._restore_remembered_authorization_after_absence = Mock(return_value=False)
        self.plugin._connection_topology = Mock()
        self.plugin._connection_topology.observe.return_value = NS(
            transport_present=False, transport_absent_verified=True)
        self.power = Mock()
        self.power.request_poweroff.return_value = NS(requested=True)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, fd)
        from regear.delivery.dock_power_intent import DockPowerIntentStore
        self.store = DockPowerIntentStore(self.root, owner_uid=os.geteuid(), trusted_directory_fd=fd)
        self.assertTrue(self.store.claim(self.request.operation,
            self.runtime.binding.binding, self.runtime.binding.generation))
        self.assertTrue(self.store.bind(self.request.operation,
            self.runtime.binding.binding, self.runtime.binding.generation,
            'shutdown', self.request.session, 10, 20))
        self.store.record(self.request.operation, 'software_down')
        self.path = self.root / ('dock-power-' + self.request.operation + '.json')

    def run_waiter(self, *, now=11, strict=True, poll=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.module.time, 'monotonic', return_value=now))
            stack.enter_context(patch.object(self.module.time, 'sleep', side_effect=poll))
            stack.enter_context(patch.object(self.module, 'read_boot_hash', return_value=self.boot))
            stack.enter_context(patch.object(self.module, 'verified_transport_absent', return_value=strict))
            stack.enter_context(patch.object(self.module, 'SystemPowerCommandRunner', return_value=self.power))
            return self.plugin._shutdown_after_physical_unplug(
                self.request, self.runtime, self.admission, self.store)

    def test_verified_absence_submits_original_once_and_keeps_attempt_history(self):
        result = self.run_waiter()
        self.assertTrue(result.requested)
        self.assertEqual(result.code, 'dock_power.request_accepted_unverified')
        self.assertTrue(json.loads(self.path.read_bytes())['consumed'])
        self.assertEqual(self.store.load().stage, 'software_down')
        self.power.request_poweroff.assert_called_once()
        # Re-entering an internal helper cannot replay the persisted consumption.
        self.assertFalse(self.run_waiter().requested)
        self.power.request_poweroff.assert_called_once()

    def test_attached_wait_has_exact_prompt_then_only_absence_submits(self):
        self.plugin._connection_topology.observe.return_value = NS(
            transport_present=True, transport_absent_verified=False)
        def unplug(_):
            status = self.plugin._dock_sleep_status
            self.assertEqual(status['code'], 'dock_power.unplug_required')
            self.assertEqual(status['request_id'], '3' * 32)
            self.assertEqual(status['power_action'], 'shutdown')
            self.assertTrue(status['software_down'])
            self.assertTrue(status['busy'])
            self.assertFalse(status['safe_to_unplug'])
            self.assertFalse(json.loads(self.path.read_bytes())['consumed'])
            self.power.request_poweroff.assert_not_called()
            self.plugin._connection_topology.observe.return_value = NS(
                transport_present=False, transport_absent_verified=True)
        self.assertTrue(self.run_waiter(poll=unplug).requested)

    def test_expiry_and_explicit_cancel_never_submit_even_after_unplug(self):
        result = self.run_waiter(now=20)
        self.assertEqual(result.code, 'dock_power.unplug_request_expired')
        self.power.request_poweroff.assert_not_called()
        self.assertFalse(self.path.exists())
        self.assertIsNone(self.store.load())
        self.assertTrue(list(self.root.glob('unsubmitted-shutdown-wait-*.json')))

    def test_cancel_exact_waiter_then_absence_cleans_without_power(self):
        self.plugin._connection_topology.observe.return_value = NS(
            transport_present=True, transport_absent_verified=False)
        def cancel(_):
            wrong = asyncio.run(self.plugin.cancel_egpu_shutdown('4' * 32))
            self.assertEqual(wrong['code'], 'dock_power.cancel_unavailable')
            ack = asyncio.run(self.plugin.cancel_egpu_shutdown('3' * 32))
            self.assertEqual(ack['code'], 'dock_power.cancel_pending')
            self.plugin._connection_topology.observe.return_value = NS(
                transport_present=False, transport_absent_verified=True)
        result = self.run_waiter(poll=cancel)
        self.assertEqual(result.code, 'dock_power.unplug_request_cancelled')
        self.power.request_poweroff.assert_not_called()
        self.assertIsNone(self.store.load())

    def test_cancel_after_consumption_refuses_without_erasing_history(self):
        self.assertTrue(self.run_waiter().requested)
        ack = asyncio.run(self.plugin.cancel_egpu_shutdown('3' * 32))
        self.assertEqual(ack['code'], 'dock_power.already_consumed')
        self.assertTrue(json.loads(self.path.read_bytes())['consumed'])

    def test_unknown_absence_and_lost_session_or_lease_never_submit(self):
        for field in ('session', 'boot', 'lease', 'portable', 'claim', 'unloading'):
            with self.subTest(field=field):
                case = MainPhysicalUnplugShutdownTests()
                case.setUp()
                try:
                    if field == 'session': case.plugin._dock_power_session = '5' * 64 + ':' + '6' * 32
                    if field == 'boot': case.boot = '5' * 64
                    if field == 'lease': case.plugin._whole_dock_trial_lease.status.return_value = NS(active=False)
                    if field == 'portable': case.plugin._dock_power_portable_verified.return_value = False
                    if field == 'claim': case.store.record(case.request.operation, 'reauthorize_intent')
                    if field == 'unloading': case.plugin._unloading = True
                    self.assertFalse(case.run_waiter().requested)
                    case.power.request_poweroff.assert_not_called()
                finally: case.doCleanups()

    def test_strict_absence_failure_remains_waiting_until_expired_not_powered(self):
        def stop(_): self.plugin._unloading = True
        self.assertFalse(self.run_waiter(strict=False, poll=stop).requested)
        self.power.request_poweroff.assert_not_called()
        self.assertFalse(json.loads(self.path.read_bytes())['consumed'])

    def test_ambiguous_power_submission_consumed_never_replayed(self):
        self.power.request_poweroff.side_effect = TimeoutError()
        self.assertEqual(self.run_waiter().code, 'dock_power.unresolved')
        self.assertFalse(self.run_waiter().requested)
        self.power.request_poweroff.assert_called_once()

    def test_authorization_failure_after_expiry_keeps_claim_and_inhibitor(self):
        self.plugin._restore_remembered_authorization_after_absence.return_value = None
        result = self.run_waiter(now=20)
        self.assertFalse(result.requested)
        self.assertIsNotNone(self.store.load())
        self.plugin._whole_dock_trial_lease.release.assert_not_called()

    def test_observed_partial_departure_then_replug_disables_original_request(self):
        samples = iter([NS(transport_present=False, transport_absent_verified=False),
            NS(transport_present=True, transport_absent_verified=False)])
        self.plugin._connection_topology.observe.side_effect = lambda: next(samples)
        result = self.run_waiter(poll=lambda _: None)
        self.assertEqual(result.code, 'dock_power.preflight_changed')
        self.power.request_poweroff.assert_not_called()
        self.assertFalse(json.loads(self.path.read_bytes())['consumed'])

    def test_absence_lost_during_consumption_retains_attempt_and_refuses_power(self):
        consume = self.store.consume
        def consume_then_replug(*args):
            result = consume(*args)
            self.plugin._connection_topology.observe.return_value = NS(
                transport_present=True, transport_absent_verified=False)
            return result
        self.store.consume = consume_then_replug
        self.assertEqual(self.run_waiter().code, 'dock_power.preflight_changed')
        self.power.request_poweroff.assert_not_called()
        self.assertTrue(json.loads(self.path.read_bytes())['consumed'])

    def test_expired_wait_keeps_lease_and_admission_until_real_absence(self):
        self.plugin._connection_topology.observe.return_value = NS(
            transport_present=True, transport_absent_verified=False)
        def unplug(_):
            self.assertEqual(self.plugin._dock_sleep_status['code'], 'dock_power.unplug_request_expired')
            self.assertTrue(self.admission['held'])
            self.plugin._whole_dock_trial_lease.release.assert_not_called()
            self.plugin._connection_topology.observe.return_value = NS(
                transport_present=False, transport_absent_verified=True)
        self.assertEqual(self.run_waiter(now=20, poll=unplug).code, 'dock_power.unplug_request_expired')
        self.plugin._whole_dock_trial_lease.release.assert_called_once()
        self.power.request_poweroff.assert_not_called()

    def test_actual_status_poll_exposes_correlated_shutdown_wait_without_dispatch(self):
        self.plugin._connection_topology.observe.return_value = NS(
            transport_present=True, transport_absent_verified=False)
        self.plugin._whole_dock_trial_status = {'schema_version': 1,
            'request_id': '3' * 32, 'code': 'dock_teardown.trial_running', 'busy': True,
            'safe_to_unplug': False}
        self.plugin._whole_dock_trial_phase = 'power_verification'
        def poll(_):
            status = asyncio.run(self.plugin.get_egpu_disconnect_status('whole_dock_trial'))
            self.assertEqual(status['route_action'], 'whole_dock_shutdown')
            self.assertEqual(status['phase'], 'power_verification')
            self.assertTrue(status['in_flight'])
            self.assertEqual(status['code'], 'dock_power.unplug_required')
            self.power.request_poweroff.assert_not_called()
            self.plugin._connection_topology.observe.return_value = NS(
                transport_present=False, transport_absent_verified=True)
        self.assertTrue(self.run_waiter(poll=poll).requested)

    def test_cancel_during_durable_consumption_is_refused_without_unlock_or_replay(self):
        consume = self.store.consume
        def consume_then_cancel(*args):
            result = consume(*args)
            ack = asyncio.run(self.plugin.cancel_egpu_shutdown('3' * 32))
            self.assertEqual(ack['code'], 'dock_power.already_consumed')
            return result
        self.store.consume = consume_then_cancel
        self.assertTrue(self.run_waiter().requested)
        self.power.request_poweroff.assert_called_once()
        self.assertTrue(json.loads(self.path.read_bytes())['consumed'])

    def test_consumption_durability_fault_retains_consumed_record_and_no_power(self):
        fsync = os.fsync
        def fail_directory(fd):
            if __import__('stat').S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('directory durability fault')
            return fsync(fd)
        with patch('regear.delivery.dock_power_intent.os.fsync', side_effect=fail_directory):
            self.assertEqual(self.run_waiter().code, 'dock_power.unresolved')
        self.power.request_poweroff.assert_not_called()
        self.assertTrue(json.loads(self.path.read_bytes())['consumed'])
        self.assertFalse(self.run_waiter().requested)
        self.power.request_poweroff.assert_not_called()

    def test_backend_restart_and_malformed_cancel_have_no_saved_request_authority(self):
        fresh = self.module.Plugin.__new__(self.module.Plugin)
        for request in ('3' * 32, '', None, '../unsafe'):
            ack = asyncio.run(fresh.cancel_egpu_shutdown(request))
            self.assertEqual(ack['code'], 'dock_power.cancel_unavailable')
        self.assertFalse(json.loads(self.path.read_bytes())['consumed'])
        self.power.request_poweroff.assert_not_called()

    def test_actual_production_wrapper_admits_only_backend_correlated_cancellation(self):
        from regear.delivery.build_profile_policy import profiled_plugin
        production = profiled_plugin(self.module.Plugin, 'production')
        self.plugin._connection_topology.observe.return_value = NS(
            transport_present=True, transport_absent_verified=False)
        def cancel(_):
            wrong = asyncio.run(production.cancel_egpu_shutdown(self.plugin, '4' * 32))
            self.assertEqual(wrong['code'], 'dock_power.cancel_unavailable')
            ack = asyncio.run(production.cancel_egpu_shutdown(self.plugin, '3' * 32))
            self.assertEqual(ack['code'], 'dock_power.cancel_pending')
            self.plugin._connection_topology.observe.return_value = NS(
                transport_present=False, transport_absent_verified=True)
        self.assertEqual(self.run_waiter(poll=cancel).code, 'dock_power.unplug_request_cancelled')
        self.power.request_poweroff.assert_not_called()

    def test_expired_shutdown_receipt_rearms_only_after_fresh_unclaimed_attachment(self):
        self.assertEqual(self.run_waiter(now=20).code, 'dock_power.unplug_request_expired')
        self.plugin._whole_dock_trial_worker_alive = False
        retained = {**self.plugin._dock_sleep_status, 'in_flight': False}
        self.plugin._whole_dock_trial_status = retained
        self.plugin._fresh_unclaimed_whole_dock_attachment_token = Mock(return_value=None)
        first = asyncio.run(self.plugin.get_egpu_disconnect_status('whole_dock_trial'))
        self.assertEqual(first['code'], 'dock_power.unplug_request_expired')
        token = '4' * 64 + ':' + '5' * 64
        self.plugin._fresh_unclaimed_whole_dock_attachment_token.return_value = token
        second = asyncio.run(self.plugin.get_egpu_disconnect_status('whole_dock_trial'))
        self.assertEqual(second['code'], 'dock_teardown.no_trial')
        self.assertEqual(second['attachment_token'], token)
        self.power.request_poweroff.assert_not_called()


if __name__ == '__main__': unittest.main()
