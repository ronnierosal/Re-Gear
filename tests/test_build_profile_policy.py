import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from regear.delivery.build_profile_policy import profiled_plugin, rpc_allowed


class ExamplePlugin:
    def __init__(self):
        self.calls = []

    async def execute_egpu_disconnect(self, release_display=False, relaunch_app_id="",
                                      relaunch_intent="disconnect", trial_action=""):
        self.calls.append((relaunch_intent, trial_action))
        return {"code": "existing_lifecycle_guard"}

    async def start_auto_tdp(self, target_fps=60):
        self.calls.append("tdp")
        return {"ok": True}

    async def future_feature(self):
        self.calls.append("future")

    async def stop_auto_tdp(self):
        self.calls.append("stop")

    async def get_device_authorization_status(self, _request=None):
        self.calls.append("authorization_status")
        return {"state": "offered"}

    async def acknowledge_device_authorization(self, token):
        self.calls.append(("acknowledge", token))
        return {"accepted": True}

    async def decline_device_authorization(self, token):
        self.calls.append(("decline", token))
        return {"accepted": True}

    async def confirm_device_authorization(self, token, consent, action):
        self.calls.append(("confirm", token, consent, action))
        return {"requested": True}

    async def _main(self):
        self.calls.append("startup_and_recovery")


class ProductionAdmissionTests(unittest.TestCase):
    def test_development_preserves_original_class_and_actions(self):
        self.assertIs(ExamplePlugin, profiled_plugin(ExamplePlugin, "development"))
        plugin = profiled_plugin(ExamplePlugin, "development")()
        asyncio.run(plugin.start_auto_tdp())
        self.assertEqual(["tdp"], plugin.calls)

    def test_development_retains_sleep_and_shutdown_lifecycle_actions(self):
        plugin = profiled_plugin(ExamplePlugin, "development")()
        for action in ("whole_dock_sleep", "whole_dock_shutdown"):
            result = asyncio.run(plugin.execute_egpu_disconnect(
                release_display=True,
                relaunch_intent="disconnect",
                trial_action=action,
            ))
            self.assertEqual("existing_lifecycle_guard", result["code"])
        self.assertEqual([
            ("disconnect", "whole_dock_sleep"),
            ("disconnect", "whole_dock_shutdown"),
        ], plugin.calls)

    def test_plain_disconnect_and_completion_reach_existing_guard(self):
        plugin = profiled_plugin(ExamplePlugin, "production")()
        for action in ("whole_dock_disconnect", "whole_dock_disconnect_complete"):
            result = asyncio.run(plugin.execute_egpu_disconnect(True, "", "disconnect", action))
            self.assertEqual("existing_lifecycle_guard", result["code"])
        self.assertEqual(2, len(plugin.calls))

    def test_power_trial_and_unknown_actions_do_not_reach_body(self):
        plugin = profiled_plugin(ExamplePlugin, "production")()
        for action in ("", "whole_dock_sleep", "whole_dock_sleep_connected", "whole_dock_shutdown",
                       "whole_dock_reconnect", "whole_dock_physical_reset", "whole_dock_reconcile",
                       "capture", "new_action", [], None):
            result = asyncio.run(plugin.execute_egpu_disconnect(trial_action=action))
            self.assertEqual("build_profile.feature_unavailable", result["code"])
            self.assertFalse(result["hardware_write"])
        result = asyncio.run(plugin.execute_egpu_disconnect(
            relaunch_intent="sleep", trial_action="whole_dock_disconnect"))
        self.assertFalse(result["ok"])
        self.assertEqual([], plugin.calls)

    def test_unrelated_and_future_public_rpcs_are_disabled(self):
        plugin = profiled_plugin(ExamplePlugin, "production")()
        for method in (plugin.start_auto_tdp, plugin.future_feature):
            self.assertEqual("build_profile.feature_unavailable", asyncio.run(method())["code"])
        self.assertEqual([], plugin.calls)

    def test_unknown_profile_fails_closed_without_removing_startup_recovery(self):
        plugin = profiled_plugin(ExamplePlugin, "unknown")()
        self.assertFalse(asyncio.run(plugin.execute_egpu_disconnect(
            trial_action="whole_dock_disconnect"))["ok"])
        asyncio.run(plugin._main())
        self.assertEqual(["startup_and_recovery"], plugin.calls)

    def test_tdp_mutations_denied_and_status_remains_readable(self):
        for enabled in (True, False, 0, None, "false"):
            self.assertFalse(rpc_allowed("production", "set_tdp_enabled", {"enabled": enabled}))
        self.assertTrue(rpc_allowed("production", "get_tdp_status", {}))
        self.assertFalse(rpc_allowed("production", "take_pending_sleep", {}))

    def test_positional_and_keyword_admission_agree(self):
        plugin = profiled_plugin(ExamplePlugin, "production")()
        for invoke in (
            lambda: plugin.execute_egpu_disconnect(True, "", "sleep", "whole_dock_disconnect"),
            lambda: plugin.execute_egpu_disconnect(relaunch_intent="sleep", trial_action="whole_dock_disconnect"),
        ):
            self.assertFalse(asyncio.run(invoke())["ok"])
        self.assertEqual([], plugin.calls)

    def test_production_admits_only_the_explicit_authorization_contract(self):
        plugin = profiled_plugin(ExamplePlugin, "production")()
        token = "a" * 32
        self.assertEqual(
            "offered",
            asyncio.run(plugin.get_device_authorization_status())["state"],
        )
        self.assertTrue(
            asyncio.run(plugin.acknowledge_device_authorization(token))["accepted"]
        )
        self.assertTrue(
            asyncio.run(plugin.decline_device_authorization(token))["accepted"]
        )
        self.assertTrue(
            asyncio.run(
                plugin.confirm_device_authorization(token, True, "authorize")
            )["requested"]
        )
        self.assertTrue(
            asyncio.run(
                plugin.confirm_device_authorization(token, True, "enroll")
            )["requested"]
        )
        self.assertEqual(5, len(plugin.calls))

    def test_production_refuses_bad_tokens_consent_and_unknown_actions_before_body(self):
        plugin = profiled_plugin(ExamplePlugin, "production")()
        for invoke in (
            lambda: plugin.acknowledge_device_authorization("bad"),
            lambda: plugin.decline_device_authorization("A" * 32),
            lambda: plugin.confirm_device_authorization("a" * 32, False, "authorize"),
            lambda: plugin.confirm_device_authorization("a" * 32, True, "remember"),
            lambda: plugin.confirm_device_authorization("a" * 32, True, ["enroll"]),
            lambda: plugin.confirm_device_authorization("a" * 32, True, {"action": "enroll"}),
        ):
            result = asyncio.run(invoke())
            self.assertEqual("build_profile.feature_unavailable", result["code"])
        self.assertEqual([], plugin.calls)
