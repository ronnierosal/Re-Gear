from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.commands import CommandResult, ReadOnlyCommandRunner  # noqa: E402
from regear.adapters.steamos.drm import DrmDiscovery  # noqa: E402
from regear.adapters.steamos.game_scopes import (  # noqa: E402
    SystemdGameScopeDiscovery,
    parse_game_scopes,
)
from regear.adapters.steamos.gamescope import (  # noqa: E402
    GamescopeDiscovery,
    GamescopeProcessRecord,
    GamescopeScan,
    parse_process_start_time,
)
from regear.adapters.steamos.gamescope_session import (  # noqa: E402
    GamescopeSessionObservationAdapter,
)
from regear.adapters.steamos.pci import PciUsb4Discovery  # noqa: E402
from regear.domain.models import GameState  # noqa: E402


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class DrmDiscoveryTests(unittest.TestCase):
    def test_scans_cards_connectors_modes_and_hashed_edid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            device = root / "card7" / "device"
            write(device / "vendor", "0x1002\n")
            write(device / "device", "0x7480\n")
            write(device / "boot_vga", "0\n")
            write(device / "uevent", "PCI_SLOT_NAME=0000:08:00.0\n")
            connector = root / "card7-HDMI-A-9"
            write(connector / "status", "connected\n")
            write(connector / "enabled", "enabled\n")
            write(connector / "modes", "3840x2160\n1920x1080\n")
            edid = b"sanitized-edid-fixture"
            (connector / "edid").write_bytes(edid)

            cards = DrmDiscovery(root).scan()

            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0].name, "card7")
            self.assertEqual(cards[0].pci_bdf, "0000:08:00.0")
            self.assertEqual(cards[0].vendor_device, "1002:7480")
            self.assertIs(cards[0].boot_vga, False)
            self.assertEqual(cards[0].connectors[0].name, "HDMI-A-9")
            self.assertEqual(cards[0].connectors[0].modes, ("3840x2160", "1920x1080"))
            self.assertEqual(
                cards[0].connectors[0].edid_sha256,
                hashlib.sha256(edid).hexdigest(),
            )

    def test_missing_sysfs_is_an_empty_inventory(self):
        self.assertEqual(DrmDiscovery(Path("missing-drm-root")).scan(), ())


class GamescopeDiscoveryTests(unittest.TestCase):
    def test_parses_live_process_arguments_without_shelling_out(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = root / "47959"
            process.mkdir()
            argv = (
                "/usr/bin/gamescope",
                "-e",
                "-O",
                "HDMI-A-9",
                "--prefer-vk-device=1002:7480",
            )
            (process / "cmdline").write_bytes(b"\0".join(part.encode() for part in argv) + b"\0")
            (process / "environ").write_bytes(
                b"MESA_VK_DEVICE_SELECT=1002:7480\0SECRET_TOKEN=must-not-be-retained\0"
            )
            stat_fields = ["S", "1"] + ["0"] * 17 + ["424242"]
            (process / "stat").write_text(
                f"47959 (gamescope session) {' '.join(stat_fields)}",
                encoding="utf-8",
            )

            result = GamescopeDiscovery(root).scan()

            self.assertTrue(result.ok)
            self.assertEqual(result.process.pid, 47959)
            self.assertEqual(result.process.output_order, ("HDMI-A-9",))
            self.assertEqual(result.process.prefer_vk_device, "1002:7480")
            self.assertEqual(result.process.mesa_vk_device_select, "1002:7480")
            self.assertTrue(result.process.environment_readable)
            self.assertIsInstance(result.process.uid, int)
            self.assertEqual(result.process.start_time_ticks, 424242)
            self.assertNotIn("must-not-be-retained", repr(result.process))

    def test_stat_parser_handles_parentheses_and_rejects_pid_mismatch(self):
        fields = ["S", "1"] + ["0"] * 17 + ["987654"]
        value = f"42 (gamescope (session)) {' '.join(fields)}"

        self.assertEqual(parse_process_start_time(value, 42), 987654)
        self.assertEqual(parse_process_start_time(value, 43), 0)

    def test_session_generation_binds_pid_start_time_and_uid(self):
        class Discovery:
            def __init__(self, record):
                self.record = record

            def scan(self):
                return GamescopeScan(self.record, 1)

        first = GamescopeProcessRecord(
            42, ("/usr/bin/gamescope", "-e"), uid=1000, start_time_ticks=100
        )
        restarted = GamescopeProcessRecord(
            42, ("/usr/bin/gamescope", "-e"), uid=1000, start_time_ticks=200
        )

        observed = GamescopeSessionObservationAdapter(Discovery(first)).observe()
        changed = GamescopeSessionObservationAdapter(Discovery(restarted)).observe()
        unknown = GamescopeSessionObservationAdapter(
            Discovery(GamescopeProcessRecord(42, ("gamescope", "-e"), uid=1000))
        ).observe()

        self.assertTrue(observed.exact)
        self.assertEqual(len(observed.generation), 64)
        self.assertNotEqual(observed.generation, changed.generation)
        self.assertFalse(unknown.exact)
        self.assertEqual(unknown.code, "gamescope.session_identity_unverified")

    def test_multiple_gamescope_processes_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for pid in ("10", "20"):
                process = root / pid
                process.mkdir()
                (process / "cmdline").write_bytes(b"/usr/bin/gamescope\0-e\0")
                (process / "environ").write_bytes(b"XDG_SESSION_TYPE=wayland\0")
            result = GamescopeDiscovery(root).scan()
            self.assertFalse(result.ok)
            self.assertEqual(result.candidate_count, 2)
            self.assertIn("Multiple", result.error)

    def test_ignores_nested_gamescope_without_steam_session_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = root / "10"
            session.mkdir()
            (session / "cmdline").write_bytes(b"/usr/bin/gamescope\0-e\0-O\0*,eDP-1\0")
            (session / "environ").write_bytes(b"XDG_SESSION_TYPE=wayland\0")
            nested = root / "20"
            nested.mkdir()
            (nested / "cmdline").write_bytes(b"/usr/bin/gamescope\0-f\0--\0game\0")
            (nested / "environ").write_bytes(b"XDG_SESSION_TYPE=wayland\0")

            result = GamescopeDiscovery(root).scan()

            self.assertTrue(result.ok)
            self.assertEqual(result.process.pid, 10)


class GameScopeDiscoveryTests(unittest.TestCase):
    def test_reads_game_scope_from_the_gamescope_users_cgroup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_slice = (
                root
                / "user.slice"
                / "user-1000.slice"
                / "user@1000.service"
                / "app.slice"
            )
            (app_slice / "app-steam-app2909400-43899.scope").mkdir(parents=True)

            class UnusedRunner:
                def run(self, argv):
                    raise AssertionError("cgroup discovery must not invoke systemctl")

            result = SystemdGameScopeDiscovery(
                UnusedRunner(),
                cgroup_root=root,
            ).scan(user_uid=1000)

            self.assertEqual(result.state, GameState.RUNNING)
            self.assertEqual(result.scopes, ("app-steam-app2909400-43899.scope",))
            self.assertEqual(result.app_ids, ("2909400",))
            self.assertEqual(result.active_app_id, "2909400")

    def test_empty_readable_user_cgroup_means_idle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                root
                / "user.slice"
                / "user-1000.slice"
                / "user@1000.service"
                / "app.slice"
            ).mkdir(parents=True)

            result = SystemdGameScopeDiscovery(cgroup_root=root).scan(user_uid=1000)

            self.assertEqual(result.state, GameState.IDLE)

    def test_recognizes_legacy_current_and_unknown_current_scopes(self):
        output = """
app-steam-123.scope loaded active running legacy
steam-app-456.scope loaded active running legacy-two
app-steam-app2909400-43899.scope loaded active running current
app-steam-appfuture.scope loaded active running future
gamescope-session.scope loaded active running compositor
"""
        result = parse_game_scopes(output)
        self.assertEqual(result.state, GameState.RUNNING)
        self.assertEqual(len(result.scopes), 4)
        self.assertEqual(result.app_ids, ("123", "456", "2909400"))
        self.assertEqual(result.unparsed_current_scopes, ("app-steam-appfuture.scope",))
        self.assertEqual(result.active_app_id, "")

    def test_duplicate_scope_for_one_app_retains_one_unambiguous_appid(self):
        result = parse_game_scopes(
            "app-steam-app1234-first.scope loaded active running\n"
            "app-steam-app1234-second.scope loaded active running\n"
        )
        self.assertEqual(result.app_ids, ("1234",))
        self.assertEqual(result.active_app_id, "1234")

    def test_multiple_apps_or_future_scope_keep_identity_unknown(self):
        multiple = parse_game_scopes(
            "app-steam-app1234-first.scope loaded active running\n"
            "app-steam-app5678-second.scope loaded active running\n"
        )
        self.assertEqual(multiple.state, GameState.RUNNING)
        self.assertEqual(multiple.active_app_id, "")
        future = parse_game_scopes(
            "app-steam-app1234-first.scope loaded active running\n"
            "app-steam-appfuture.scope loaded active running\n"
        )
        self.assertEqual(future.active_app_id, "")

    def test_unrelated_scopes_mean_idle(self):
        result = parse_game_scopes("gamescope-session.scope loaded active running\n")
        self.assertEqual(result.state, GameState.IDLE)

    def test_query_failure_is_unknown_and_fail_closed(self):
        class FailedRunner:
            def run(self, argv):
                return CommandResult(tuple(argv), 1, "", "user bus unavailable")

        result = SystemdGameScopeDiscovery(FailedRunner()).scan()
        self.assertEqual(result.state, GameState.UNKNOWN)
        self.assertIn("Could not verify", result.error)

    def test_root_queries_the_gamescope_owners_user_manager(self):
        class CapturingRunner:
            argv = ()

            def run(self, argv):
                self.argv = tuple(argv)
                return CommandResult(tuple(argv), 0, "", "")

        runner = CapturingRunner()
        result = SystemdGameScopeDiscovery(
            runner,
            effective_uid=lambda: 0,
            username_for_uid=lambda uid: "deck" if uid == 1000 else "unexpected",
        ).scan(user_uid=1000)

        self.assertEqual(result.state, GameState.IDLE)
        self.assertEqual(runner.argv[0:4], ("/usr/bin/runuser", "-u", "deck", "--"))
        self.assertIn("XDG_RUNTIME_DIR=/run/user/1000", runner.argv)

    def test_invalid_gamescope_username_fails_closed(self):
        class UnusedRunner:
            def run(self, argv):
                raise AssertionError("invalid user context must not run")

        result = SystemdGameScopeDiscovery(
            UnusedRunner(),
            effective_uid=lambda: 0,
            username_for_uid=lambda uid: "deck;touch /tmp/nope",
        ).scan(user_uid=1000)

        self.assertEqual(result.state, GameState.UNKNOWN)
        self.assertIn("Could not resolve", result.error)


class ReadOnlyCommandRunnerTests(unittest.TestCase):
    def test_rejects_a_path_resolved_systemctl(self):
        """A basename match accepted any systemctl reachable through PATH."""
        for executable in (
            "/tmp/evil/systemctl",
            "systemctl",
            "./systemctl",
            "/usr/local/bin/systemctl",
            "/usr/bin/SYSTEMCTL",
        ):
            with self.subTest(executable=executable):
                with self.assertRaisesRegex(ValueError, "not approved"):
                    ReadOnlyCommandRunner.validate(
                        (executable, *ReadOnlyCommandRunner.SYSTEMCTL_SCOPE_QUERY)
                    )

    def test_accepts_only_the_exact_absolute_systemctl(self):
        command = (
            ReadOnlyCommandRunner.SYSTEMCTL,
            *ReadOnlyCommandRunner.SYSTEMCTL_SCOPE_QUERY,
        )
        self.assertEqual(ReadOnlyCommandRunner.validate(command), command)
        self.assertEqual(ReadOnlyCommandRunner.SYSTEMCTL, "/usr/bin/systemctl")

    def test_child_gets_a_clean_environment_not_the_plugin_inheritance(self):
        """The other three runners in commands.py already do this."""
        captured = {}

        def fake_run(argv, **kwargs):
            captured.update(kwargs)

            class Done:
                returncode, stdout, stderr = 0, "", ""

            return Done()

        command = (
            ReadOnlyCommandRunner.SYSTEMCTL,
            *ReadOnlyCommandRunner.SYSTEMCTL_SCOPE_QUERY,
        )
        with patch("regear.adapters.steamos.commands.subprocess.run", fake_run):
            ReadOnlyCommandRunner().run(command)

        self.assertEqual(captured["env"], ReadOnlyCommandRunner.CLEAN_ENVIRONMENT)
        self.assertFalse(captured["shell"])

    def test_rejects_unapproved_executable(self):
        with self.assertRaisesRegex(ValueError, "not approved"):
            ReadOnlyCommandRunner.validate(("bash", "-c", "true"))

    def test_rejects_mutation_shaped_systemctl_command(self):
        with self.assertRaisesRegex(ValueError, "forbidden"):
            ReadOnlyCommandRunner.validate(("systemctl", "--user", "restart", "gamescope"))

    def test_accepts_the_scope_inventory_command(self):
        self.assertEqual(
            ReadOnlyCommandRunner.validate(SystemdGameScopeDiscovery.COMMAND),
            SystemdGameScopeDiscovery.COMMAND,
        )

    def test_accepts_only_the_strict_user_context_scope_query(self):
        command = SystemdGameScopeDiscovery.command_for_user(1000, "deck")
        self.assertEqual(ReadOnlyCommandRunner.validate(command), command)
        with self.assertRaisesRegex(ValueError, "not approved"):
            ReadOnlyCommandRunner.validate((*command[:-1], "--all"))


class PciUsb4DiscoveryTests(unittest.TestCase):
    def test_hashes_usb4_unique_id_and_does_not_return_the_raw_value(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            usb4_root = base / "usb4"
            usb4 = usb4_root / "0-1"
            write(usb4 / "authorized", "1\n")
            write(usb4 / "vendor_name", "Intel\n")
            write(usb4 / "device_name", "Tapex Creek\n")
            raw_unique_id = "private-device-identity"
            write(usb4 / "unique_id", raw_unique_id)

            discovery = PciUsb4Discovery(base / "missing-pci", usb4_root)
            usb4_records = discovery.scan_usb4()

            self.assertEqual(discovery.scan_pci(), ())
            self.assertEqual(
                usb4_records[0].unique_id_sha256,
                hashlib.sha256(raw_unique_id.encode()).hexdigest(),
            )
            self.assertNotIn(raw_unique_id, repr(usb4_records[0]))


if __name__ == "__main__":
    unittest.main()
