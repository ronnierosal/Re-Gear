from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.adapters.steamos.commands import CommandResult
from hdm.adapters.steamos.host import HostRecord
from hdm.adapters.steamos.tdp_inventory import AsusTdpInventory
from hdm.adapters.steamos.tdp_provider import SteamOsManagerTdpProvider
from hdm.ports.presentation_activation import GamescopeUserContext


def result(output="", *, ok=True):
    return CommandResult((), 0 if ok else 1, output, "private error" if not ok else "")


class TdpProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.boot = self.root / "boot_id"
        self.boot.write_bytes(b"12345678-1234-1234-1234-123456789abc\n")
        self.user = GamescopeUserContext("gamer", 1000, 1000, Path("/home/gamer"), Path("/run/user/1000"), Path("/run/user/1000/bus"))
        self.users = Mock(return_value=self.user)
        self.host = Mock()
        self.host.scan.return_value = HostRecord("ASUSTeK COMPUTER INC.", "ROG Ally X RC72LA", "RC72LA")
        self.commands = Mock()
        self.commands.owner.return_value = result('s ":1.42"\n')
        self.commands.read.return_value = result("u 17\nu 7\nu 30\n")
        self.commands.set_limit.return_value = result()
        self.ownership = Mock(return_value=True)
        for name, values in (("ppt_pl1_spl", (17, 7, 30)), ("ppt_pl2_sppt", (25, 15, 43)), ("ppt_pl3_fppt", (30, 15, 53))):
            self.attribute(name, values)
        self.provider = SteamOsManagerTdpProvider(user_resolver=self.users, host=self.host, inventory=AsusTdpInventory(self.root), commands=self.commands, ownership_ready=self.ownership, boot_id_path=self.boot)

    def attribute(self, name, values):
        directory = self.root / "class/firmware-attributes/asus-armoury/attributes" / name
        directory.mkdir(parents=True, exist_ok=True)
        for field, value in zip(("current_value", "min_value", "max_value"), values):
            (directory / field).write_text(str(value))

    def test_agreement_retains_three_distinct_settings(self):
        observation = self.provider.observe()
        self.assertEqual(observation.code, "tdp.ready")
        self.assertEqual(observation.reading.values, (17, 25, 30))
        self.assertEqual(len(observation.reading.binding), 64)
        self.assertEqual(self.commands.owner.call_count, 2)

    def test_read_only_display_does_not_assume_ownership(self):
        self.ownership.return_value = False
        observation = self.provider.observe()
        self.assertEqual(observation.code, "tdp.ownership_unverified")
        self.assertIsNotNone(observation.reading)
        self.assertFalse(self.provider.set_limit(observation.reading, 20).attempted)
        self.commands.set_limit.assert_not_called()

    def test_default_ownership_is_unverified(self):
        provider = SteamOsManagerTdpProvider(user_resolver=self.users, host=self.host, inventory=AsusTdpInventory(self.root), commands=self.commands, boot_id_path=self.boot)
        self.assertEqual(provider.observe().code, "tdp.ownership_unverified")

    def test_invalid_dbus_outputs_never_create_reading(self):
        for output in ("", "u 17\nu 7", "u 17\nu 0\nu 30", "u 17\nu 20\nu 30", "u 17\nu 7\nu 4294967296", "u -1\nu 7\nu 30", "u NaN\nu 7\nu 30", "u 17\nu 7\nu 30\nextra", "u " + "9" * 200):
            with self.subTest(output=output):
                self.commands.read.return_value = result(output)
                self.assertIsNone(self.provider.observe().reading)

    def test_dbus_and_firmware_ranges_must_agree(self):
        for output in ("u 18\nu 7\nu 30", "u 17\nu 8\nu 30", "u 17\nu 7\nu 29"):
            self.commands.read.return_value = result(output)
            self.assertEqual(self.provider.observe().code, "tdp.source_disagreement")

    def test_boost_limits_must_be_present_positive_and_valid(self):
        for values in ((30,), (30, 0, 53), (30, "NaN", 53), (30, 31, 53), (30, 15, 2**32)):
            directory = self.root / "class/firmware-attributes/asus-armoury/attributes/ppt_pl3_fppt"
            for field in directory.iterdir():
                field.unlink()
            self.attribute("ppt_pl3_fppt", values)
            with self.subTest(values=values):
                self.assertIsNone(self.provider.observe().reading)

    def test_parallel_legacy_interface_is_not_ownership_conflict(self):
        directory = self.root / "devices/platform/asus-nb-wmi"
        directory.mkdir(parents=True)
        (directory / "ppt_pl1_spl").write_text("17")
        self.assertEqual(self.provider.observe().code, "tdp.ready")

    def test_alternate_fast_alias_blocks_backend_selection(self):
        self.attribute("ppt_fppt", (30, 15, 53))
        self.assertEqual(self.provider.observe().code, "tdp.source_ambiguous")

    def test_owner_changes_during_read_are_rejected(self):
        self.commands.owner.side_effect = [result('s ":1.42"'), result('s ":1.43"')]
        self.assertEqual(self.provider.observe().code, "tdp.owner_changed")

    def test_owner_missing_failed_or_malformed_is_rejected(self):
        for response in (result(ok=False), result('s "named.owner"'), result('s ":1.42" trailing')):
            self.commands.owner.return_value = response
            self.assertIsNone(self.provider.observe().reading)

    def test_boot_host_and_user_must_be_verified(self):
        original = self.host.scan.return_value
        self.host.scan.return_value = HostRecord("ASUS", "Ally", "unknown")
        self.assertEqual(self.provider.observe().code, "tdp.host_unverified")
        self.host.scan.return_value = original
        self.users.return_value = None
        self.assertEqual(self.provider.observe().code, "tdp.user_unverified")
        self.users.return_value = self.user
        self.boot.write_text("x" * 100)
        self.assertEqual(self.provider.observe().code, "tdp.boot_unverified")

    def test_changed_owner_boot_uid_or_values_blocks_write(self):
        expected = self.provider.observe().reading
        changes = (
            lambda: setattr(self.commands.owner, "return_value", result('s ":1.99"')),
            lambda: self.boot.write_text("87654321-1234-1234-1234-123456789abc"),
            lambda: setattr(self.users, "return_value", replace(self.user, uid=1001)),
            lambda: self.attribute("ppt_pl2_sppt", (26, 15, 43)),
        )
        for change in changes:
            self.commands.owner.return_value = result('s ":1.42"')
            self.boot.write_bytes(b"12345678-1234-1234-1234-123456789abc\n")
            self.users.return_value = self.user
            self.attribute("ppt_pl2_sppt", (25, 15, 43))
            change()
            outcome = self.provider.set_limit(expected, 20)
            self.assertFalse(outcome.attempted)
        self.commands.set_limit.assert_not_called()

    def test_invalid_target_never_dispatches(self):
        expected = self.provider.observe().reading
        for watts in (0, 6, 31, True, 15.5):
            self.assertFalse(self.provider.set_limit(expected, watts).attempted)
        self.commands.set_limit.assert_not_called()

    def test_read_failure_or_exception_during_revalidation_never_writes(self):
        expected = self.provider.observe().reading
        self.commands.read.return_value = result(ok=False)
        self.assertFalse(self.provider.set_limit(expected, 20).attempted)
        self.commands.read.side_effect = RuntimeError("private detail")
        outcome = self.provider.set_limit(expected, 20)
        self.assertEqual(outcome.code, "tdp.observation_invalid")
        self.assertFalse(outcome.attempted)
        self.commands.set_limit.assert_not_called()

    def test_boost_target_must_fit_even_if_sustained_target_fits(self):
        self.attribute("ppt_pl2_sppt", (20, 15, 20))
        expected = self.provider.observe().reading
        self.assertEqual(self.provider.set_limit(expected, 21).code, "tdp.limit_invalid")
        self.commands.set_limit.assert_not_called()

    def test_forward_watts_and_reuse_freshly_bound_user(self):
        expected = self.provider.observe().reading
        self.users.reset_mock()
        outcome = self.provider.set_limit(expected, 10)
        self.assertTrue(outcome.attempted)
        self.assertTrue(outcome.accepted)
        self.users.assert_called_once_with()
        self.commands.set_limit.assert_called_once_with(self.user, 10, owner=":1.42")

    def test_failed_command_is_attempted_and_may_have_partially_applied(self):
        expected = self.provider.observe().reading
        for response in (result(ok=False), RuntimeError("private detail")):
            self.commands.set_limit.side_effect = response if isinstance(response, Exception) else None
            self.commands.set_limit.return_value = response
            outcome = self.provider.set_limit(expected, 20)
            self.assertTrue(outcome.attempted)
            self.assertFalse(outcome.accepted)
            self.assertEqual(outcome.code, "tdp.write_unverified")


if __name__ == "__main__":
    unittest.main()
