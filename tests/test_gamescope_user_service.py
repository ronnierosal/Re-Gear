from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.commands import (  # noqa: E402
    UserServiceCommandRunner,
    UserServiceOperation,
)
from regear.adapters.steamos.gamescope import (  # noqa: E402
    GamescopeProcessRecord,
    GamescopeScan,
)
from regear.adapters.steamos.gamescope_user import resolve_gamescope_user  # noqa: E402


def scan(uid: int | None = 1000) -> GamescopeScan:
    return GamescopeScan(
        GamescopeProcessRecord(42, ("/usr/bin/gamescope", "-e"), uid=uid),
        1,
    )


class GamescopeUserResolutionTests(unittest.TestCase):
    @staticmethod
    def record(uid=1000, name="deck", home="/home/deck"):
        return SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=1000, pw_dir=home)

    def test_resolves_only_exact_process_owner_and_live_bus(self):
        result = resolve_gamescope_user(
            scan(),
            password_for_uid=lambda uid: self.record(uid=uid),
            session_bus_ready=lambda runtime, bus: (
                runtime == Path("/run/user/1000")
                and bus == Path("/run/user/1000/bus")
            ),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.context.username, "deck")
        self.assertEqual(result.context.home, Path("/home/deck"))

    def test_never_falls_back_when_identity_or_bus_is_unknown(self):
        cases = (
            (GamescopeScan(None, 0, "missing"), self.record(), True),
            (scan(None), self.record(), True),
            (scan(0), self.record(uid=0, name="root", home="/root"), True),
            (scan(), self.record(name="deck;bad"), True),
            (scan(), self.record(home="/other/deck"), True),
            (scan(), self.record(), False),
        )
        for value, record, bus_ready in cases:
            with self.subTest(value=value, record=record, bus_ready=bus_ready):
                result = resolve_gamescope_user(
                    value,
                    password_for_uid=lambda uid, record=record: record,
                    session_bus_ready=lambda runtime, bus, ready=bus_ready: ready,
                )
                self.assertFalse(result.ok)


class UserServiceCommandRunnerTests(unittest.TestCase):
    def test_builds_only_fixed_root_to_user_commands(self):
        self.assertEqual(
            UserServiceCommandRunner.argv(
                UserServiceOperation.RESTART_GAMESCOPE_SESSION,
                uid=1000,
                username="deck",
            ),
            (
                "/usr/bin/runuser",
                "-u",
                "deck",
                "--",
                "/usr/bin/env",
                "XDG_RUNTIME_DIR=/run/user/1000",
                "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
                "/usr/bin/systemctl",
                "--user",
                "--no-block",
                "restart",
                "gamescope-session.target",
            ),
        )
        with self.assertRaisesRegex(ValueError, "username"):
            UserServiceCommandRunner.argv(
                UserServiceOperation.DAEMON_RELOAD,
                uid=1000,
                username="deck;touch",
            )

    def test_runner_is_root_only_shell_free_and_environment_sanitized(self):
        completed = SimpleNamespace(returncode=0, stdout=b"loaded\n", stderr=b"")
        runner = UserServiceCommandRunner(effective_uid=lambda: 0)
        with patch(
            "regear.adapters.steamos.commands.subprocess.run", return_value=completed
        ) as invoke:
            result = runner.run(
                UserServiceOperation.VERIFY_GAMESCOPE_UNIT,
                uid=1000,
                username="deck",
            )
        self.assertTrue(result.ok)
        _, kwargs = invoke.call_args
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["env"], runner.CLEAN_ENVIRONMENT)
        self.assertEqual(result.output, "loaded")

        blocked = UserServiceCommandRunner(effective_uid=lambda: 1000).run(
            UserServiceOperation.DAEMON_RELOAD,
            uid=1000,
            username="deck",
        )
        self.assertEqual(blocked.error_code, "root_required")

    def test_runner_returns_only_bounded_categorical_failures(self):
        runner = UserServiceCommandRunner(effective_uid=lambda: 0)
        cases = (
            (
                SimpleNamespace(returncode=1, stdout=b"", stderr=b"private detail"),
                "nonzero_exit",
            ),
            (
                SimpleNamespace(
                    returncode=0,
                    stdout=b"x" * (runner.MAX_OUTPUT_BYTES + 1),
                    stderr=b"",
                ),
                "output_too_large",
            ),
        )
        for completed, expected in cases:
            with self.subTest(expected=expected), patch(
                "regear.adapters.steamos.commands.subprocess.run",
                return_value=completed,
            ):
                result = runner.run(
                    UserServiceOperation.DAEMON_RELOAD,
                    uid=1000,
                    username="deck",
                )
                self.assertEqual(result.error_code, expected)
                self.assertEqual(result.output, "")

        with patch(
            "regear.adapters.steamos.commands.subprocess.run",
            side_effect=subprocess.TimeoutExpired(("systemctl",), 8),
        ):
            result = runner.run(
                UserServiceOperation.DAEMON_RELOAD,
                uid=1000,
                username="deck",
            )
        self.assertEqual(result.error_code, "timeout")


if __name__ == "__main__":
    unittest.main()
