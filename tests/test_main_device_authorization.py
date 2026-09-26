"""Plugin wiring for first-time USB4 authorization choices."""

import asyncio
import unittest
from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module


DOCK_UUID = "01234567-89ab-cdef-0123-456789abcdef"


class MainDeviceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._device_authorization = Mock()
        self.plugin._device_authorization_observer = Mock()

    def test_production_composition_explicitly_enables_remembered_trust(self):
        plugin = self.module.Plugin()
        self.assertIs(plugin._device_authorization._remembered_grant_enabled, True)

    def test_status_reconciles_lifecycle_before_reading_facade(self):
        self.plugin._reconcile_device_authorization_disconnect = Mock()
        expected = {"schema_version": 1, "state": "offered", "token": "a" * 32}
        self.plugin._device_authorization.status.return_value = expected
        result = asyncio.run(self.plugin.get_device_authorization_status())
        self.assertEqual({**expected, "remembered_grant_offered": True}, result)
        self.plugin._reconcile_device_authorization_disconnect.assert_called_once_with()
        self.plugin._device_authorization.status.assert_called_once_with()

    def test_answers_delegate_exactly_once_to_the_plugin_owned_facade(self):
        token = "a" * 32
        self.plugin._device_authorization.acknowledge.return_value = {"accepted": True}
        self.plugin._device_authorization.decline.return_value = {"accepted": True}
        self.plugin._device_authorization.confirm.side_effect = [
            {"requested": True}, {"requested": True}
        ]
        self.assertTrue(
            asyncio.run(self.plugin.acknowledge_device_authorization(token))["accepted"]
        )
        self.assertTrue(
            asyncio.run(self.plugin.decline_device_authorization(token))["accepted"]
        )
        self.assertTrue(
            asyncio.run(
                self.plugin.confirm_device_authorization(token, True, "authorize")
            )["requested"]
        )
        self.assertTrue(
            asyncio.run(
                self.plugin.confirm_device_authorization(token, True, "enroll")
            )["requested"]
        )
        self.plugin._device_authorization.acknowledge.assert_called_once_with(token)
        self.plugin._device_authorization.decline.assert_called_once_with(token)
        self.assertEqual(
            [
                unittest.mock.call(token, consent=True, action="authorize"),
                unittest.mock.call(token, consent=True, action="enroll"),
            ],
            self.plugin._device_authorization.confirm.call_args_list,
        )

    def test_runtime_failure_is_bounded_and_never_reflects_the_token(self):
        secret = "f" * 32
        self.plugin._device_authorization.confirm.side_effect = RuntimeError(secret)
        result = asyncio.run(
            self.plugin.confirm_device_authorization(secret, True, "authorize")
        )
        self.assertEqual("device_authorization.runtime_unavailable", result["code"])
        self.assertFalse(result["requested"])
        self.assertEqual("", result["token"])
        self.assertNotIn(secret, repr(result))

        self.plugin._device_authorization.decline.side_effect = RuntimeError(secret)
        declined = asyncio.run(self.plugin.decline_device_authorization(secret))
        self.assertFalse(declined["accepted"])
        self.assertEqual("", declined["token"])

    def test_completed_exact_claim_suppresses_a_reauthorization_prompt(self):
        self.plugin._device_authorization_observer.observe.return_value = NS(
            uuid=DOCK_UUID
        )
        claim = NS(stage="software_down", binding="b" * 64, generation="c" * 64)
        with patch.object(self.module, "WholeDockClaimStore") as store, patch.object(
            self.module, "resolve_deauthorized_transport"
        ) as resolve:
            store.return_value.load.return_value = claim
            self.plugin._reconcile_device_authorization_disconnect()
        resolve.assert_called_once_with(claim.binding, claim.generation)
        self.plugin._device_authorization.note_intentional_disconnect.assert_called_once_with(
            True, uuid=DOCK_UUID
        )

    def test_no_claim_clears_the_same_dock_after_physical_replug(self):
        self.plugin._device_authorization_observer.observe.return_value = NS(
            uuid=DOCK_UUID
        )
        with patch.object(self.module, "WholeDockClaimStore") as store:
            store.return_value.load.return_value = None
            self.plugin._reconcile_device_authorization_disconnect()
        self.plugin._device_authorization.note_intentional_disconnect.assert_called_once_with(
            False, uuid=DOCK_UUID
        )

    def test_unreadable_or_intermediate_claim_never_clears_or_files_a_report(self):
        self.plugin._device_authorization_observer.observe.return_value = NS(
            uuid=DOCK_UUID
        )
        with patch.object(self.module, "WholeDockClaimStore") as store:
            store.return_value.load.side_effect = OSError("unreadable")
            self.plugin._reconcile_device_authorization_disconnect()
        self.plugin._device_authorization.note_intentional_disconnect.assert_not_called()
        with patch.object(self.module, "WholeDockClaimStore") as store:
            store.return_value.load.return_value = NS(stage="gpu_removed")
            self.plugin._reconcile_device_authorization_disconnect()
        self.plugin._device_authorization.note_intentional_disconnect.assert_not_called()

    def test_verified_software_down_files_the_internal_device_report(self):
        self.plugin._dock_mutation_gate = lambda: NS(admit=nullcontext)
        self.plugin._return_portable_before_disconnect = Mock()
        self.plugin._device_authorization_observer.observe.return_value = NS(
            uuid=DOCK_UUID, enrolled=True
        )
        self.plugin._device_authorization_commands = Mock()
        binding = NS(
            gpu_bdf="gpu",
            audio_bdf="audio",
            usb_bdf="usb",
            router_id="router",
            binding="b" * 64,
            generation="c" * 64,
        )
        runtime = Mock()
        runtime._operation = "operation"
        runtime.execute_claimed.return_value = NS(
            code="dock_teardown.software_down", software_down=True
        )
        release = Mock()
        release.execute.return_value = NS()
        lease = Mock()
        lease.acquire.return_value.active = True
        lease.status.return_value.active = True
        with patch.object(self.module, "DrmDiscovery") as drm, patch.object(
            self.module, "resolve_whole_dock", return_value=binding
        ), patch.object(self.module, "GamescopeDiscovery"), patch.object(
            self.module,
            "resolve_gamescope_user",
            return_value=NS(context=NS(uid=1000, username="deck")),
        ), patch.object(self.module, "RootOwnedRuntimeState"), patch.object(
            self.module, "Login1SleepInhibitor", return_value=lease
        ), patch.object(
            self.module, "WholeDockRuntime", return_value=runtime
        ) as runtime_type, patch.object(
            self.module, "DeviceAuthorizationHoldStore"
        ) as hold_store_type, patch.object(
            self.module, "build_live_disconnect_runtime", return_value=release
        ):
            drm.return_value.scan.return_value = [NS(boot_vga=False, pci_bdf="gpu")]
            result = self.plugin._run_whole_dock_trial("operation")
        self.assertTrue(result.software_down)
        callback = runtime_type.call_args.kwargs["before_deauthorize"]
        self.assertIsNotNone(callback)
        hold = self.module.DeviceAuthorizationHold(
            "operation", binding.binding, binding.generation, DOCK_UUID
        )
        hold_store_type.return_value.prepare.return_value = hold
        hold_store_type.return_value.mark_manual.return_value = (
            self.module.DeviceAuthorizationHold(
                "operation", binding.binding, binding.generation, DOCK_UUID, "manual"
            )
        )
        self.plugin._device_authorization_commands.policy.side_effect = [
            "auto", "manual"
        ]
        self.plugin._device_authorization_commands.set_policy.return_value = True
        with patch.object(
            self.module,
            "DeviceAuthorizationHoldStore",
            return_value=hold_store_type.return_value,
        ):
            self.assertTrue(callback(
                "operation", binding.binding, binding.generation, lambda: True
            ))
        self.plugin._device_authorization_commands.set_policy.assert_called_once_with(
            DOCK_UUID, "manual"
        )
        self.plugin._device_authorization.note_intentional_disconnect.assert_called_once_with(
            True, uuid=DOCK_UUID
        )

    def test_remembered_trust_restores_only_after_matching_physical_absence(self):
        self.plugin._device_authorization_commands = Mock()
        self.plugin._device_authorization_commands.policy.side_effect = [
            "manual", "auto"
        ]
        self.plugin._device_authorization_commands.set_policy.return_value = True
        claim = self.module.WholeDockClaim(
            "operation", "b" * 64, "c" * 64, "software_down"
        )
        hold = self.module.DeviceAuthorizationHold(
            claim.operation,
            claim.binding,
            claim.generation,
            DOCK_UUID,
            "manual",
        )
        hold_store = Mock()
        hold_store.load_hold.return_value = hold
        with patch.object(
            self.module, "DeviceAuthorizationHoldStore", return_value=hold_store
        ):
            restored = self.plugin._restore_remembered_authorization_after_absence(
                claim, lambda: True
            )
        self.assertEqual(restored, hold)
        self.plugin._device_authorization_commands.set_policy.assert_called_once_with(
            DOCK_UUID, "auto"
        )

    def test_remembered_trust_never_restores_without_matching_absence_guard(self):
        self.plugin._device_authorization_commands = Mock()
        claim = self.module.WholeDockClaim(
            "operation", "b" * 64, "c" * 64, "software_down"
        )
        hold_store = Mock()
        hold_store.load_hold.return_value = self.module.DeviceAuthorizationHold(
            claim.operation,
            claim.binding,
            claim.generation,
            DOCK_UUID,
            "manual",
        )
        with patch.object(
            self.module, "DeviceAuthorizationHoldStore", return_value=hold_store
        ):
            restored = self.plugin._restore_remembered_authorization_after_absence(
                claim, lambda: False
            )
        self.assertIsNone(restored)
        self.plugin._device_authorization_commands.set_policy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
