import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.game_scopes import GameScopeScan, parse_game_scopes
from hdm.adapters.steamos.gamescope import GamescopeProcessRecord, GamescopeScan
from hdm.adapters.steamos.gamescope_performance_target import GamescopePerformanceTargetResolver
from hdm.domain.models import GameState


class PerformanceTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        boot = self.root / "sys/kernel/random/boot_id"
        boot.parent.mkdir(parents=True)
        boot.write_bytes(b"12345678-1234-1234-1234-123456789abc\n")
        self.game = parse_game_scopes("app-steam-app570-abc.scope")
        self.gamescope = GamescopeScan(GamescopeProcessRecord(10, ("gamescope", "-e"), uid=1000, start_time_ticks=123), 1)
        self.scope_path = "/user.slice/user-1000.slice/user@1000.service/app.slice/app-steam-app570-abc.scope"
        self.process(10, scope="/user.slice/user-1000.slice/user@1000.service/session.slice/gamescope.service", ticks=123)
        self.game_process = self.process(20, ticks=456)
        self.runtime_root = self.root / "runtime"
        self.resolver = GamescopePerformanceTargetResolver(self.root, runtime_root=self.runtime_root)

    def process(self, pid, *, uid=1000, ticks=456, scope=None, environment=None):
        process = self.root / str(pid)
        process.mkdir(exist_ok=True)
        (process / "status").write_text(f"Name:\tgame\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
        (process / "stat").write_text(f"{pid} (game ) tricky) S " + "0 " * 18 + str(ticks) + " 0\n")
        (process / "cgroup").write_text("0::" + (scope or self.scope_path) + "\n")
        if environment is None:
            environment = b"GAMESCOPE_WAYLAND_DISPLAY=gamescope-0\0XDG_RUNTIME_DIR=/run/user/1000\0PRIVATE_SECRET=hidden\0"
        (process / "environ").write_bytes(environment)
        return process

    def resolve(self):
        return self.resolver.resolve(self.game, self.gamescope)

    def test_exact_scope_owner_and_environment_resolve_private_target(self):
        result = self.resolve()
        self.assertTrue(result.ok, result.code)
        self.assertEqual(result.target.socket_path, self.runtime_root / "1000/gamescope-0")
        self.assertEqual((result.target.uid, result.target.app_id, result.target.compositor_pid, result.target.process_start_ticks), (1000, 570, 10, 123))
        self.assertRegex(result.target.context_key, r"^[0-9a-f]{64}$")
        payload = json.dumps(result.to_dict())
        for private in ("hidden", "/run/user", "app-steam", "socket", "pid", "app_id"):
            self.assertNotIn(private, payload)
        self.assertNotIn("PerformanceTarget(", repr(result))

    def test_no_outer_wayland_display_fallback(self):
        (self.game_process / "environ").write_bytes(b"WAYLAND_DISPLAY=wayland-0\0XDG_RUNTIME_DIR=/run/user/1000\0")
        self.assertEqual(self.resolve().code, "performance.endpoint_unavailable")

    def test_same_scope_children_agree_and_membership_resets_context(self):
        before = self.resolve().target.context_key
        self.process(21, ticks=457)
        after = self.resolve()
        self.assertTrue(after.ok)
        self.assertNotEqual(before, after.target.context_key)
        self.assertEqual(self.resolve().target.context_key, after.target.context_key)

    def test_conflicting_same_scope_endpoints_are_ambiguous(self):
        self.process(21, environment=b"GAMESCOPE_WAYLAND_DISPLAY=gamescope-1\0XDG_RUNTIME_DIR=/run/user/1000\0")
        self.assertEqual(self.resolve().code, "performance.endpoint_ambiguous")

    def test_same_app_in_other_scope_or_user_cannot_supply_endpoint(self):
        (self.game_process / "environ").write_bytes(b"")
        self.process(21, scope=self.scope_path.replace("-abc.scope", "-other.scope"))
        self.process(22, uid=1001, scope=self.scope_path.replace("1000", "1001"))
        self.assertEqual(self.resolve().code, "performance.endpoint_unavailable")

    def test_scope_members_with_wrong_owner_fail_closed(self):
        self.process(21, uid=1001)
        self.assertEqual(self.resolve().code, "performance.target_unavailable")

    def test_invalid_environment_rejected(self):
        for environment in (
            b"GAMESCOPE_WAYLAND_DISPLAY=gamescope-0\0",
            b"GAMESCOPE_WAYLAND_DISPLAY=gamescope-0\0XDG_RUNTIME_DIR=/run/user/1001\0",
            b"GAMESCOPE_WAYLAND_DISPLAY=../socket\0XDG_RUNTIME_DIR=/run/user/1000\0",
            b"GAMESCOPE_WAYLAND_DISPLAY=/tmp/socket\0XDG_RUNTIME_DIR=/run/user/1000\0",
            b"GAMESCOPE_WAYLAND_DISPLAY=x\0GAMESCOPE_WAYLAND_DISPLAY=x\0XDG_RUNTIME_DIR=/run/user/1000\0",
            b"GAMESCOPE_WAYLAND_DISPLAY=x\0XDG_RUNTIME_DIR=/run/user/1000",
            b"x" * (self.resolver.MAX_ENVIRONMENT_BYTES + 1),
        ):
            with self.subTest(environment=environment[:70]):
                (self.game_process / "environ").write_bytes(environment)
                self.assertEqual(self.resolve().code, "performance.target_unavailable")

    def test_game_and_compositor_inputs_must_be_exact(self):
        for game in (parse_game_scopes(""), parse_game_scopes("app-steam-1.scope\napp-steam-2.scope"), parse_game_scopes("app-steam-app570-abc.scope\napp-steam-app570-other.scope"), GameScopeScan(GameState.RUNNING, ("unrecognized.scope",), ("570",))):
            self.assertEqual(self.resolver.resolve(game, self.gamescope).code, "performance.game_unverified")
        for compositor in (GamescopeScan(None, 0), replace(self.gamescope, candidate_count=2), GamescopeScan(replace(self.gamescope.process, uid=0), 1), GamescopeScan(replace(self.gamescope.process, start_time_ticks=0), 1)):
            self.assertEqual(self.resolver.resolve(self.game, compositor).code, "performance.compositor_unverified")

    def test_compositor_start_time_or_uid_mismatch_rejected(self):
        for field, value in (("start_time_ticks", 124), ("uid", 1001)):
            scan = GamescopeScan(replace(self.gamescope.process, **{field: value}), 1)
            self.assertEqual(self.resolver.resolve(self.game, scan).code, "performance.context_changed")

    def test_pid_reuse_between_environment_and_stat_rejected(self):
        original = self.resolver._read
        def mutate(path, limit):
            data = original(path, limit)
            if path == self.game_process / "environ":
                (self.game_process / "stat").write_text("20 (replacement) S " + "0 " * 18 + "999 0\n")
            return data
        with patch.object(self.resolver, "_read", side_effect=mutate):
            self.assertEqual(self.resolve().code, "performance.context_changed")

    def test_game_generation_boot_and_compositor_generation_change_key(self):
        before = self.resolve().target.context_key
        self.process(20, ticks=457)
        after_game = self.resolve().target.context_key
        self.assertNotEqual(before, after_game)
        (self.root / "sys/kernel/random/boot_id").write_bytes(b"87654321-1234-1234-1234-123456789abc\n")
        after_boot = self.resolve().target.context_key
        self.assertNotEqual(after_game, after_boot)
        self.process(10, ticks=124, scope="/user.slice/user-1000.slice/user@1000.service/session.slice/gamescope.service")
        self.gamescope = GamescopeScan(replace(self.gamescope.process, start_time_ticks=124), 1)
        self.assertNotEqual(after_boot, self.resolve().target.context_key)

    def test_compositor_restart_during_game_environment_read_rejected(self):
        original = self.resolver._read
        def restart(path, limit):
            data = original(path, limit)
            if path == self.game_process / "environ":
                (self.root / "10/stat").write_text("10 (gamescope) S " + "0 " * 18 + "999 0\n")
            return data
        with patch.object(self.resolver, "_read", side_effect=restart):
            self.assertEqual(self.resolve().code, "performance.context_changed")

    def test_boot_change_during_scan_rejected(self):
        original = self.resolver._read
        def reboot(path, limit):
            data = original(path, limit)
            if path == self.game_process / "environ":
                (self.root / "sys/kernel/random/boot_id").write_bytes(b"87654321-1234-1234-1234-123456789abc\n")
            return data
        with patch.object(self.resolver, "_read", side_effect=reboot):
            self.assertEqual(self.resolve().code, "performance.context_changed")

    def test_zombie_compositor_is_not_a_live_target(self):
        path = self.root / "10/stat"
        path.write_text(path.read_text().replace(") S ", ") Z "))
        self.assertFalse(self.resolve().ok)

    def test_unrelated_process_needs_no_status_stat_or_environment_read(self):
        unrelated = self.root / "30"
        unrelated.mkdir()
        (unrelated / "cgroup").write_text("0::/system.slice/unrelated.service\n")
        self.assertTrue(self.resolve().ok)

    def test_unreadable_or_oversized_evidence_and_scan_budget_fail_closed(self):
        with patch.object(Path, "open", side_effect=PermissionError("private path")):
            self.assertEqual(self.resolve().code, "performance.target_unavailable")
        with patch.object(self.resolver, "MAX_PROC_ENTRIES", 0):
            self.assertEqual(self.resolve().code, "performance.target_unavailable")
        (self.game_process / "cgroup").write_bytes(b"x" * (self.resolver.MAX_CGROUP_BYTES + 1))
        self.assertEqual(self.resolve().code, "performance.target_unavailable")

    def test_disappearing_unrelated_process_is_tolerated(self):
        missing = self.root / "30"
        missing.mkdir()
        original = self.resolver._read
        def vanish(path, limit):
            if path == missing / "cgroup":
                missing.rmdir()
                raise FileNotFoundError()
            return original(path, limit)
        with patch.object(self.resolver, "_read", side_effect=vanish):
            self.assertTrue(self.resolve().ok)


if __name__ == "__main__":
    unittest.main()
