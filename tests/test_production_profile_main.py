"""Real Plugin RPC and startup composition under the packaged production profile."""

import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests.test_main_process_delivery import load_main_module
from regear.delivery import build_profile_config


class ProductionPluginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.object(build_profile_config, "BUILD_PROFILE", "production"):
            self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)

    async def test_other_dock_actions_refuse_before_any_runtime_or_journal_write(self):
        # An intentionally uninitialized Plugin would fail if admission reached
        # any runtime factory, approval store or lifecycle state mutation.
        for action in ("whole_dock_shutdown", "whole_dock_sleep", "whole_dock_sleep_connected",
                       "whole_dock_capture", "whole_dock_held_capture", "whole_dock_physical_reset",
                       "whole_dock_reconcile", "whole_dock_reconnect", ""):
            with self.subTest(action=action):
                result = await self.plugin.execute_egpu_disconnect(
                    True, "", "disconnect", action, True, "", "a" * 32)
                self.assertEqual("build_profile.feature_unavailable", result["code"])
                self.assertFalse(result["hardware_write"])
        self.assertEqual({}, self.plugin.__dict__)

    async def test_tdp_trial_and_shutdown_rpcs_refuse_before_body(self):
        for method, args in (
            ("set_tdp_enabled", (True,)), ("apply_tdp_limit", (20,)),
            ("start_auto_tdp", (60, 10, 25)), ("run_auto_tdp_benchmark", ()),
            ("approve_supervised_portable_vulkan_trial", ()),
            ("approve_supervised_portable_switch", ()),
            ("execute_supervised_portable_switch", ("unused-token",)),
            ("approve_presentation_preparation", ()),
            ("prepare_presentation_integration", ("unused-token",)),
            ("approve_safe_disconnect_shutdown", ()),
        ):
            result = await getattr(self.plugin, method)(*args)
            self.assertEqual("build_profile.feature_unavailable", result["code"])
        self.assertEqual({}, self.plugin.__dict__)

    async def test_plain_disconnect_still_requires_existing_confirmation(self):
        result = await self.plugin.execute_egpu_disconnect(trial_action="whole_dock_disconnect")
        self.assertEqual("dock_teardown.trial_confirmation_required", result["code"])

    async def test_first_time_authorization_rpcs_are_exactly_admitted(self):
        token = "a" * 32
        self.plugin._unloading = False
        self.plugin._device_authorization = Mock()
        self.plugin._device_authorization.confirm.return_value = {"requested": True}
        for action in ("authorize", "enroll"):
            accepted = await self.plugin.confirm_device_authorization(
                token, True, action
            )
            self.assertTrue(accepted["requested"])
        self.assertEqual(2, self.plugin._device_authorization.confirm.call_count)

        self.plugin._device_authorization.reset_mock()
        for consent, action in (
            (False, "authorize"),
            (False, "enroll"),
            (True, "remember"),
            (True, ["enroll"]),
            (True, {"action": "enroll"}),
        ):
            refused = await self.plugin.confirm_device_authorization(
                token, consent, action
            )
            self.assertEqual("build_profile.feature_unavailable", refused["code"])
        self.plugin._device_authorization.confirm.assert_not_called()

    async def test_manual_connection_preferences_and_game_relaunch_refuse_before_body(self):
        for method, args in (
            ("set_automatic_dock_enabled", (True, True, True)),
            ("execute_link_recovery", (True, "")),
            ("approve_supervised_tv_switch", ()),
            ("execute_supervised_tv_switch", ("unused-token",)),
            ("acknowledge_supervised_tv_switch", ("unused-receipt",)),
            ("remember_game_close_choice", ("123", "disconnect", True, True)),
            ("forget_game_close_choice", ("123", "disconnect")),
            ("take_pending_relaunch", ()), ("take_pending_sleep", ()),
        ):
            with self.subTest(method=method):
                result = await getattr(self.plugin, method)(*args)
                self.assertEqual("build_profile.feature_unavailable", result["code"])
        self.assertEqual({}, self.plugin.__dict__)

    async def test_exact_completion_calls_only_retained_completion_path(self):
        request = "a" * 32
        completion = {"code": "dock_teardown.software_down", "request_id": request,
                      "software_down": True, "safe_to_unplug": False}
        self.plugin._run_background_operation = AsyncMock(return_value=completion)
        self.plugin._complete_interrupted_whole_dock_trial = Mock()
        result = await self.plugin.execute_egpu_disconnect(
            False, "", "disconnect", "whole_dock_disconnect_complete", True, "", request)
        self.assertEqual(completion, result)
        self.plugin._run_background_operation.assert_awaited_once_with(
            self.plugin._complete_interrupted_whole_dock_trial, request)

    async def test_completion_cannot_be_used_to_initiate_teardown(self):
        result = await self.plugin.execute_egpu_disconnect(
            True, "", "disconnect", "whole_dock_disconnect_complete", True, "", "a" * 32)
        self.assertEqual("dock_teardown.completion_confirmation_required", result["code"])
        self.assertEqual({}, self.plugin.__dict__)

    async def test_startup_keeps_topology_safety_connection_and_native_recovery(self):
        self.plugin._build_info = {"version": "test", "revision": "test"}
        self.plugin._events = Mock()
        self.plugin._process_service = Mock(return_value=NS(recover_interrupted=lambda: NS(action_required=False)))
        self.plugin._reconcile_sleep_guard = AsyncMock()
        self.plugin.get_snapshot = AsyncMock(return_value={
            "snapshot": {"blockers": [], "game_state": "idle", "support_tier": "unknown"},
            "inference": {"mode": "unknown"},
        })
        self.plugin._append_journey_event = Mock()
        self.plugin._sleep_guard_loop = AsyncMock()
        self.plugin._automatic_dock_loop = AsyncMock()
        self.plugin._native_portable_recovery_loop = AsyncMock()
        with patch.object(self.module, "LinuxTopologyWakeup") as topology:
            await self.plugin._main()
            await asyncio.gather(self.plugin._sleep_guard_task, self.plugin._automatic_dock_task,
                                 self.plugin._native_recovery_task)
            topology.return_value.start.assert_called_once()
        self.plugin._reconcile_sleep_guard.assert_awaited_once()
        self.plugin._sleep_guard_loop.assert_awaited_once()
        self.plugin._automatic_dock_loop.assert_awaited_once()
        self.plugin._native_portable_recovery_loop.assert_awaited_once()
