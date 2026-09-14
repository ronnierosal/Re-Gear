"""Direct RPC attempts cannot execute the thermally excluded reconnect path."""
import asyncio
import unittest
from unittest.mock import Mock

from tests.test_main_process_delivery import load_main_module


class SoftwareReconnectDisabledTests(unittest.TestCase):
    def test_direct_confirmed_rpc_refused_even_at_golden_software_down(self):
        module = load_main_module(real_dock_gate=True)
        plugin = module.Plugin.__new__(module.Plugin)
        original = {'schema_version': 1, 'code': 'dock_teardown.software_down',
                    'busy': False, 'ok': True, 'software_down': True}
        plugin._whole_dock_trial_status = original
        plugin._run_background_operation = Mock(side_effect=AssertionError('worker started'))
        plugin._run_whole_dock_reconnect_trial = Mock(side_effect=AssertionError('reconnect executed'))
        for confirmed in (True, False):
            with self.subTest(confirmed=confirmed):
                result = asyncio.run(plugin.execute_egpu_disconnect(
                    release_display=True, trial_action='whole_dock_reconnect',
                    trial_confirmed=confirmed, trial_request_id='a' * 32,
                    trial_attachment_token='b' * 64 + ':' + 'c' * 64))
                self.assertEqual(result['code'], 'dock_reconnect.disabled')
                self.assertFalse(result['ok'])
                self.assertFalse(result['hardware_write'])
                self.assertIs(plugin._whole_dock_trial_status, original)
        plugin._run_background_operation.assert_not_called()
        plugin._run_whole_dock_reconnect_trial.assert_not_called()
