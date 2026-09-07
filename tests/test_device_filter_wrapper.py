from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.hdm.delivery import gamescope_wrapper as gamescope, steam_trial_wrapper as steam
from backend.hdm.delivery import device_filter_wrapper as gate
from backend.hdm.delivery.device_filter_arm import FilterArm
from backend.hdm.delivery.device_filter_protocol import FilterGrant


_consume_steam_environment = steam.consume_steam_environment


class WrapperEntryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.environment = {"HDM_STATE_ROOT": self.temp, "INVOCATION_ID": "e" * 32}
        self.stack.enter_context(patch.dict(gamescope.os.environ, self.environment, clear=True))
        self.execute = self.stack.enter_context(patch.object(gamescope.os, "execve"))
        self.arm = SimpleNamespace(operation="op")
        self.latch = self.stack.enter_context(patch.object(gate, "latch_filter_arm", return_value=self.arm))
        self.authorize = self.stack.enter_context(patch.object(gate, "authorize_filter_launch"))
        for module in (gamescope, steam):
            self.stack.enter_context(patch.object(module, "_boot_identity", return_value=("boot", "a" * 64)))
            self.stack.enter_context(patch.object(module, "_load_config", return_value=None))
        self.stack.enter_context(patch.object(gamescope, "_connected_connectors", return_value=()))
        self.stack.enter_context(patch.object(gamescope, "_present_vendor_devices", return_value=()))
        self.stack.enter_context(patch.object(gamescope, "_verified_egpu_binding_sha256", return_value="b" * 64))
        self.candidate = self.stack.enter_context(patch("backend.hdm.delivery.portable_trial_launch.consume_launch_candidate",
            return_value=((), self.environment)))
        self.receipt = self.stack.enter_context(patch("backend.hdm.delivery.portable_trial_store.PortableTrialStore.publish_gamescope_launch"))
        self.steam_candidate = self.stack.enter_context(patch.object(steam, "consume_steam_environment", return_value=self.environment))

    def test_unreadable_arm_never_executes_either_wrapper(self):
        self.latch.side_effect = OSError("arm unreadable")
        for module in (gamescope, steam):
            self.assertEqual(module.main(), 78)
        self.execute.assert_not_called()
        self.candidate.assert_not_called()

    def test_armed_selector_failure_does_not_fall_back(self):
        self.candidate.side_effect = ValueError("consumed")
        self.steam_candidate.side_effect = ValueError("consumed")
        for module in (gamescope, steam):
            self.assertEqual(module.main(), 78)
        self.authorize.assert_not_called()
        self.execute.assert_not_called()

    def test_failed_handshake_never_executes_or_publishes_receipt(self):
        self.authorize.side_effect = TimeoutError("no backend")
        for module in (gamescope, steam):
            self.assertEqual(module.main(), 78)
        self.execute.assert_not_called()
        self.receipt.assert_not_called()

    def test_gamescope_grant_precedes_receipt_and_exec(self):
        events = []
        self.authorize.side_effect = lambda *a, **k: events.append("grant")
        self.receipt.side_effect = lambda *a, **k: events.append("receipt")
        self.execute.side_effect = lambda *a, **k: events.append("exec")
        self.assertEqual(gamescope.main(), 127)
        self.assertEqual(events, ["grant", "receipt", "exec"])
        self.assertEqual(self.candidate.call_args.kwargs["expected_operation"], "op")
        self.assertIs(self.candidate.call_args.kwargs["defer_receipt"], True)

    def test_unarmed_launch_does_not_contact_listener(self):
        self.latch.return_value = None
        self.assertEqual(gamescope.main(), 127)
        self.assertEqual(steam.main(), 127)
        self.authorize.assert_not_called()
        self.assertEqual(self.execute.call_count, 2)

    def test_steam_strict_missing_claim_raises(self):
        with patch("backend.hdm.delivery.steam_trial_wrapper.PortableTrialStore.consume_steam", return_value=None):
            with self.assertRaises(ValueError):
                _consume_steam_environment(Path(self.temp), config=None,
                    environment={}, raw_boot_id="boot", expected_operation="op")


class GateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.config = gamescope.GamescopeLaunchConfig("a" * 64, "portable", "eDP-1")
        self.arm = FilterArm(1, "op", "gamescope-session.service", 1000,
            hashlib.sha256(b"boot").hexdigest(), "b" * 64, gate.config_hash(self.config), "d" * 32, 100)
        self.store = Mock()
        self.store.read.return_value = self.arm
        self.stack.enter_context(patch.object(gate, "FilterArmStore", return_value=self.store))
        self.stack.enter_context(patch.object(gate.os, "getuid", return_value=1000, create=True))
        self.stack.enter_context(patch.object(gate.time, "monotonic", return_value=10))
        self.stack.enter_context(patch.object(gamescope, "_load_config", return_value=self.config))
        self.stack.enter_context(patch.object(gamescope, "_verified_egpu_binding_sha256", return_value="b" * 64))
        self.request = self.stack.enter_context(patch.object(gate, "request_grant",
            side_effect=lambda request, **kw: FilterGrant(**asdict(request), revision=4, status="granted")))

    def authorize(self):
        return gate.authorize_filter_launch(self.arm, state_root=Path.cwd(), raw_boot_id="boot",
                                           environment={"INVOCATION_ID": "e" * 32}, candidate_config=self.config)

    def test_valid_arm_is_rechecked_after_correlated_reply(self):
        self.assertEqual(self.authorize().revision, 4)
        self.assertEqual(self.store.read.call_count, 2)
        self.request.assert_called_once()
        self.assertEqual(self.request.call_args.kwargs["deadline"], 15)

    def test_changed_or_missing_arm_blocks_without_retry(self):
        self.store.read.side_effect = [self.arm, None]
        with self.assertRaises(ValueError): self.authorize()
        self.request.assert_called_once()

    def test_stale_config_or_old_invocation_prevents_request(self):
        self.arm = replace(self.arm, config_hash="f" * 64)
        self.store.read.return_value = self.arm
        with self.assertRaises(ValueError): self.authorize()
        self.request.assert_not_called()

    def test_config_changed_to_armed_value_after_candidate_still_blocks(self):
        later = gamescope.GamescopeLaunchConfig("a" * 64, "portable", "eDP-2")
        self.arm = replace(self.arm, config_hash=gate.config_hash(later))
        self.store.read.return_value = self.arm
        with patch.object(gamescope, "_load_config", return_value=later):
            with self.assertRaises(ValueError): self.authorize()
        self.request.assert_not_called()
