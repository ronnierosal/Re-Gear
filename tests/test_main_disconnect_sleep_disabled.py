"""Legacy sleep-disconnect remains excluded from the physical-unplug flow."""

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

    def test_physical_unplug_sleep_requires_explicit_confirmation(self):
        self.plugin._run_background_operation = Mock()
        self.plugin._run_whole_dock_trial = Mock()
        self.plugin._run_dock_power_request = Mock()

        with patch.object(self.module, "create_power_request") as create_request:
            result = asyncio.run(self.plugin.execute_egpu_disconnect(
                release_display=True,
                trial_action="whole_dock_sleep",
                trial_confirmed=False,
                trial_attachment_token=f"{'a' * 64}:{'b' * 64}",
                trial_request_id="c" * 32,
            ))

        self.assertEqual(result["code"], "dock_teardown.trial_confirmation_required")
        self.assertFalse(result["ok"])
        self.assertFalse(result["safe_to_unplug"])
        create_request.assert_not_called()
        self.plugin._run_background_operation.assert_not_called()
        self.plugin._run_whole_dock_trial.assert_not_called()
        self.plugin._run_dock_power_request.assert_not_called()
        self.assertFalse(hasattr(self.plugin, "_dock_power_context"))
        self.assertFalse(hasattr(self.plugin, "_whole_dock_trial_status"))

    def test_completed_legacy_cleanup_cannot_bypass_sleep_confirmation(self):
        self.plugin._reconcile_physically_disconnected_dock = Mock(return_value=True)
        self.assertTrue(self.plugin._reconcile_physically_disconnected_dock())
        self.plugin._run_background_operation = Mock()
        self.plugin._run_whole_dock_trial = Mock()
        self.plugin._run_dock_power_request = Mock()

        result = asyncio.run(self.plugin.execute_egpu_disconnect(
            release_display=True,
            trial_action="whole_dock_sleep",
            trial_confirmed=False,
            trial_attachment_token=f"{'a' * 64}:{'b' * 64}",
            trial_request_id="c" * 32,
        ))

        self.assertEqual(result["code"], "dock_teardown.trial_confirmation_required")
        self.plugin._run_background_operation.assert_not_called()
        self.plugin._run_whole_dock_trial.assert_not_called()
        self.plugin._run_dock_power_request.assert_not_called()

    def test_legacy_sleep_intent_refuses_before_runtime_or_continuation(self):
        self.plugin._live_disconnect_runtime = Mock()
        self.plugin._run_dock_mutation = Mock()
        self.plugin._record_sleep_continuation = Mock()

        with patch.object(self.module, "RelaunchIntentStore") as relaunch_store, \
                patch.object(self.module, "PendingSleepStore") as pending_store:
            result = asyncio.run(self.plugin.execute_egpu_disconnect(
                release_display=True,
                relaunch_app_id="1145360",
                relaunch_intent="sleep",
            ))

        self.assertEqual(result, {
            "schema_version": 1,
            "ok": False,
            "code": "dock_power.disconnect_sleep_disabled",
            "busy": False,
            "safe_to_unplug": False,
            "hardware_write": False,
        })
        relaunch_store.assert_not_called()
        pending_store.assert_not_called()
        self.plugin._record_sleep_continuation.assert_not_called()
        self.plugin._live_disconnect_runtime.assert_not_called()
        self.plugin._run_dock_mutation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
