"""Direct RPC exclusion for cable-retained disconnect-before-sleep."""

import asyncio
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


class MainDisconnectSleepDisabledTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._background_operations = set()
        self.plugin._unloading = False

    def test_direct_rpc_refuses_before_any_power_or_teardown_work(self):
        self.plugin._run_background_operation = Mock()
        self.plugin._run_whole_dock_trial = Mock()
        self.plugin._run_dock_power_request = Mock()

        with patch.object(self.module, "create_power_request") as create_request:
            result = asyncio.run(self.plugin.execute_egpu_disconnect(
                release_display=True,
                trial_action="whole_dock_sleep",
                trial_confirmed=True,
                trial_attachment_token=f"{'a' * 64}:{'b' * 64}",
                trial_request_id="c" * 32,
            ))

        self.assertEqual(result, {
            "schema_version": 1,
            "ok": False,
            "code": "dock_power.disconnect_sleep_disabled",
            "busy": False,
            "safe_to_unplug": False,
            "hardware_write": False,
        })
        create_request.assert_not_called()
        self.plugin._run_background_operation.assert_not_called()
        self.plugin._run_whole_dock_trial.assert_not_called()
        self.plugin._run_dock_power_request.assert_not_called()
        self.assertFalse(hasattr(self.plugin, "_dock_power_context"))
        self.assertFalse(hasattr(self.plugin, "_whole_dock_trial_status"))


if __name__ == "__main__":
    unittest.main()
