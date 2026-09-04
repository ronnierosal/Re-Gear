import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.commands import SteamOsTdpCommandRunner
from hdm.ports.presentation_activation import GamescopeUserContext


class TdpCommandTests(unittest.TestCase):
    def setUp(self):
        self.user = GamescopeUserContext(
            "deck", 1000, 1000, Path("/home/deck"),
            Path("/run/user/1000"), Path("/run/user/1000/bus"),
        )
        self.runner = SteamOsTdpCommandRunner(effective_uid=lambda: 0)
        self.prefix = (
            "/usr/bin/runuser", "-u", "deck", "--", "/usr/bin/env",
            "XDG_RUNTIME_DIR=/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
            "/usr/bin/busctl", "--user", "--auto-start=no",
            "--allow-interactive-authorization=no", "--timeout=2s",
        )
        self.address = (
            "com.steampowered.SteamOSManager1", "/com/steampowered/SteamOSManager1",
            "com.steampowered.SteamOSManager1.TdpLimit1",
        )

    @staticmethod
    def completed(stdout=b"u 17\nu 5\nu 30\n", stderr=b"", returncode=0):
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    def test_exact_read_argv_and_clean_bounded_subprocess(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed()) as run:
            result = self.runner.read(self.user)
        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "u 17\nu 5\nu 30\n")
        expected = self.prefix + ("get-property",) + self.address + ("TdpLimit", "TdpLimitMin", "TdpLimitMax")
        self.assertEqual(result.argv, expected)
        run.assert_called_once_with(
            expected, stdin=subprocess.DEVNULL, capture_output=True, check=False,
            shell=False, text=False, timeout=8.0,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )

    def test_exact_write_argv(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed(stdout=b"")) as run:
            result = self.runner.set_limit(self.user, 17, owner=":1.123")
        self.assertTrue(result.ok)
        expected = self.prefix + ("set-property", ":1.123") + self.address[1:] + ("TdpLimit", "u", "17")
        self.assertEqual(run.call_args.args[0], expected)
        self.assertEqual(result.stdout, "")

    def test_owner_required_and_strict_unique_owner_only(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run") as run:
            self.assertEqual(self.runner.set_limit(self.user, 17).error, "tdp.owner_invalid")
            for owner in (None, 123, "", "com.steampowered.SteamOSManager1", ":1", ":1.2.3", ":-1.2", ":1.2\n", ":12345678901.1", ":1.12345678901", ":１.２", "--help"):
                with self.subTest(owner=owner):
                    self.assertEqual(self.runner.set_limit(self.user, 17, owner=owner).error, "tdp.owner_invalid")
            run.assert_not_called()

    def test_exact_owner_argv(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed(stdout=b's ":1.123"\n')) as run:
            result = self.runner.owner(self.user)
        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, 's ":1.123"\n')
        self.assertEqual(run.call_args.args[0], self.prefix + (
            "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "GetNameOwner", "s", "com.steampowered.SteamOSManager1",
        ))

    def test_same_effective_user_uses_direct_env_busctl(self):
        runner = SteamOsTdpCommandRunner(effective_uid=lambda: 1000)
        with patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed()) as run:
            result = runner.read(self.user)
        self.assertTrue(result.ok)
        self.assertEqual(run.call_args.args[0][:8], self.prefix[4:])

    def test_invalid_watt_values_never_invoke_subprocess(self):
        for watts in (True, False, 0, -1, 17.0, "17", None, float("nan"), float("inf"), 1 << 32):
            with self.subTest(watts=watts), patch("hdm.adapters.steamos.commands.subprocess.run") as run:
                result = self.runner.set_limit(self.user, watts, owner=":1.123")
                self.assertEqual(result.error, "tdp.limit_invalid")
                run.assert_not_called()

    def test_uint32_wire_boundary_is_not_device_range_claim(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed(stdout=b"")) as run:
            result = self.runner.set_limit(self.user, (1 << 32) - 1, owner=":1.123")
        self.assertTrue(result.ok)
        self.assertEqual(run.call_args.args[0][-1], "4294967295")

    def test_invalid_or_mismatched_user_context_never_invokes_subprocess(self):
        invalid = [None, object(), SimpleNamespace(uid=1000, username="deck")]
        for uid in (0, -1, True, "1000", 1000.0, (1 << 32) - 1):
            invalid.append(replace(self.user, uid=uid))
        for name in (None, 123, "", "deck;id", "--help", "deck\n", "a" * 34):
            invalid.append(replace(self.user, username=name))
        invalid.extend((
            replace(self.user, runtime_directory=Path("/run/user/1001")),
            replace(self.user, bus_path=Path("/run/user/1001/bus")),
            replace(self.user, bus_path=Path("/tmp/bus")),
        ))
        for user in invalid:
            with self.subTest(user=user), patch("hdm.adapters.steamos.commands.subprocess.run") as run:
                self.assertEqual(self.runner.read(user).error, "tdp.user_invalid")
                self.assertEqual(self.runner.set_limit(user, 17, owner=":1.123").error, "tdp.user_invalid")
                run.assert_not_called()

    def test_other_effective_uid_refused(self):
        for uid in (-1, 1001, False, "0"):
            with self.subTest(uid=uid), patch("hdm.adapters.steamos.commands.subprocess.run") as run:
                runner = SteamOsTdpCommandRunner(effective_uid=lambda: uid)
                self.assertEqual(runner.read(self.user).error, "tdp.uid_mismatch")
                run.assert_not_called()

    def test_timeout_and_unavailable_errors_are_categorical(self):
        for exception, expected in (
            (subprocess.TimeoutExpired("private command", 8, output=b"private output"), "tdp.command_timeout"),
            (FileNotFoundError("private path"), "tdp.command_unavailable"),
            (subprocess.SubprocessError("private error"), "tdp.command_unavailable"),
        ):
            with self.subTest(exception=exception), patch("hdm.adapters.steamos.commands.subprocess.run", side_effect=exception):
                result = self.runner.read(self.user)
                self.assertFalse(result.ok)
                self.assertEqual(result.error, expected)
                self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_nonzero_redacts_both_streams(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed(b"private output", b"private error", 1)):
            result = self.runner.read(self.user)
        self.assertEqual(result.error, "tdp.command_failed")
        self.assertEqual((result.stdout, result.stderr), ("", ""))

    def test_combined_output_limit_applies_to_reads_and_writes(self):
        for stdout, stderr in ((b"x" * 4097, b""), (b"x" * 2048, b"x" * 2049)):
            with self.subTest(lengths=(len(stdout), len(stderr))), patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed(stdout, stderr)):
                self.assertEqual(self.runner.read(self.user).error, "tdp.output_too_large")
                self.assertEqual(self.runner.set_limit(self.user, 17, owner=":1.123").error, "tdp.output_too_large")

    def test_non_ascii_read_output_rejected(self):
        with patch("hdm.adapters.steamos.commands.subprocess.run", return_value=self.completed(b"u \xff\n")):
            self.assertEqual(self.runner.read(self.user).error, "tdp.output_invalid")


if __name__ == "__main__":
    unittest.main()
