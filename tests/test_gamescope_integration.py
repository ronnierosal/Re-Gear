from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from hdm.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402


class GamescopeIntegrationStoreTests(unittest.TestCase):
    def make_store(self, root: Path, *, effective_uid=0):
        user_uid = getattr(os, "getuid", lambda: 1000)()
        user_gid = getattr(os, "getgid", lambda: 1000)()
        home = root / "home" / "deck"
        home.mkdir(parents=True)
        plugin = root / "plugin"
        shim = plugin / "bin" / "gamescope"
        shim.parent.mkdir(parents=True)
        shim.write_text(
            '#!/usr/bin/python3\n"""Handheld Dock Mode Gamescope argument shim."""\n',
            encoding="utf-8",
        )
        if os.name != "nt":
            shim.chmod(0o755)
        user = GamescopeUserContext(
            "deck",
            user_uid,
            user_gid,
            home,
            Path("/run/user") / str(user_uid),
            Path("/run/user") / str(user_uid) / "bus",
        )
        owned = []
        store = GamescopeIntegrationStore(
            plugin_root=plugin,
            user=user,
            effective_uid=lambda: effective_uid,
            set_owner=lambda path, uid, gid: owned.append((path, uid, gid)),
        )
        return store, owned

    def test_activate_is_exact_idempotent_and_deactivate_is_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            store, owned = self.make_store(Path(directory))
            first = store.activate()
            self.assertTrue(first.ok)
            self.assertTrue(first.changed)
            self.assertTrue(store.target.is_file())
            self.assertIn("HDM_STATE_ROOT=", store.target.read_text(encoding="utf-8"))
            self.assertTrue(store.state_root.is_dir())
            self.assertTrue(owned)

            second = store.activate()
            self.assertTrue(second.ok)
            self.assertFalse(second.changed)

            removed = store.deactivate()
            self.assertTrue(removed.changed)
            self.assertFalse(store.target.exists())
            self.assertTrue(store.state_root.is_dir())

    def test_matching_dropin_with_missing_state_root_is_repaired_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            self.assertTrue(store.activate().ok)
            original = store.target.read_bytes()
            store.state_root.rmdir()
            repaired = store.activate()
            self.assertTrue(repaired.ok)
            self.assertTrue(repaired.changed)
            self.assertEqual(store.target.read_bytes(), original)

    def test_competing_path_override_fails_closed_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            store.target.parent.mkdir(parents=True)
            conflict = store.target.parent / "50-egpubridge.conf"
            conflict.write_text(
                '[Service]\nEnvironment="PATH=/other/bin:/usr/bin"\n',
                encoding="utf-8",
            )
            result = store.activate()
            self.assertFalse(result.ok)
            self.assertEqual(result.status.error_code, "path_override_conflict")
            self.assertEqual(result.status.conflicts, ("50-egpubridge.conf",))
            self.assertFalse(store.target.exists())

    def test_unknown_environment_file_also_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            store.target.parent.mkdir(parents=True)
            (store.target.parent / "other.conf").write_text(
                "[Service]\nEnvironmentFile=/somewhere/unknown\n", encoding="utf-8"
            )
            self.assertEqual(store.status().error_code, "path_override_conflict")

    def test_whitespace_and_pass_environment_path_conflicts_fail_closed(self):
        values = (
            "[Service]\nEnvironment = \"PATH=/other\"\n",
            "[Service]\nPassEnvironment = PATH\n",
            "[Service]\nUnsetEnvironment = PATH\n",
        )
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                store, _ = self.make_store(Path(directory))
                store.target.parent.mkdir(parents=True)
                (store.target.parent / "other.conf").write_text(value, encoding="utf-8")
                self.assertEqual(store.status().error_code, "path_override_conflict")

    def test_modified_managed_file_is_never_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            store.target.parent.mkdir(parents=True)
            store.target.write_text("user content\n", encoding="utf-8")
            self.assertEqual(store.activate().status.error_code, "managed_dropin_modified")
            self.assertFalse(store.deactivate().changed)
            self.assertEqual(store.target.read_text(encoding="utf-8"), "user content\n")

    def test_non_root_activation_and_missing_shim_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory), effective_uid=1000)
            self.assertEqual(store.activate().status.error_code, "root_required")
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            (store._plugin_root / "bin" / "gamescope").unlink()
            self.assertEqual(store.activate().status.error_code, "shim_unavailable")

    def test_symlinked_dropin_root_is_rejected_when_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            real = Path(directory) / "real"
            real.mkdir()
            store.target.parent.parent.mkdir(parents=True)
            try:
                store.target.parent.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable on this host")
            self.assertEqual(store.status().error_code, "inspection_failed")


class StrandedDropInTests(unittest.TestCase):
    """Issue 167: a plugin rename must not strand an install forever.

    Found on hardware. The drop-in named the HandheldDockMode plugin path
    while the plugin was installed as Re-Gear, so `expected_text` never
    matched, status reported `managed_dropin_modified`, `session_ready`
    stayed false and connection readiness parked at `waiting_for_session`
    with no way out: activation refused on any error code, and even past
    that it only wrote when nothing was installed.
    """

    def make_store(self, root: Path, *, effective_uid=0):
        return GamescopeIntegrationStoreTests.make_store(
            self, root, effective_uid=effective_uid
        )

    def write_dropin(self, store, text: str) -> None:
        # Explicit LF: the target platform writes LF only, and letting the
        # host translate newlines produced a fixture that differed from any
        # drop-in the product would write.
        store.target.parent.mkdir(parents=True, exist_ok=True)
        store.target.write_text(text, encoding="utf-8", newline="\n")

    #: The path the drop-in named before the plugin was renamed.
    FORMER_SHIM = "/home/deck/homebrew/plugins/HandheldDockMode/bin"

    def stale_text(self, store) -> str:
        """The same rendering, for a plugin directory that has since moved.

        Rendered rather than string-patched: the store's own paths are
        platform-shaped, and editing them textually produced a fixture that
        did not represent any drop-in this project would ever have written.
        """
        return store._render(self.FORMER_SHIM)

    def test_a_rendering_for_another_plugin_path_is_stale_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            self.write_dropin(store, self.stale_text(store))
            status = store.status()
        self.assertTrue(status.installed)
        self.assertFalse(status.matches)
        self.assertEqual(status.error_code, "managed_dropin_stale")

    def test_activation_migrates_a_stale_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            self.write_dropin(store, self.stale_text(store))
            result = store.activate()
            after = store.target.read_text(encoding="utf-8")
        self.assertTrue(result.changed)
        self.assertEqual(after, store.expected_text())
        self.assertTrue(result.status.ready)

    def test_an_edited_file_is_still_refused(self):
        """The protection this narrows, not removes."""
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            self.write_dropin(
                store, store.expected_text() + 'Environment="EXTRA=1"\n'
            )
            status = store.status()
            result = store.activate()
        self.assertEqual(status.error_code, "managed_dropin_modified")
        self.assertFalse(result.changed)

    def test_a_foreign_state_root_is_not_recognised(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            text = self.stale_text(store).replace(
                "HDM_STATE_ROOT=", "HDM_STATE_ROOT=/tmp/elsewhere#"
            )
            self.write_dropin(store, text)
            status = store.status()
        self.assertEqual(status.error_code, "managed_dropin_modified")

    def test_an_altered_system_path_tail_is_not_recognised(self):
        # Only the leading shim directory may differ. A changed tail is a
        # different policy and is not ours to rewrite.
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            text = self.stale_text(store).replace("/usr/sbin:/bin:/sbin", "/usr/sbin")
            self.write_dropin(store, text)
            status = store.status()
        self.assertEqual(status.error_code, "managed_dropin_modified")

    def test_an_unrelated_file_is_not_recognised(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory))
            self.write_dropin(store, "[Service]\nEnvironment=\"PATH=/bin\"\n")
            status = store.status()
        self.assertEqual(status.error_code, "managed_dropin_modified")

    def test_migration_still_requires_root(self):
        with tempfile.TemporaryDirectory() as directory:
            store, _ = self.make_store(Path(directory), effective_uid=1000)
            self.write_dropin(store, self.stale_text(store))
            result = store.activate()
        self.assertFalse(result.changed)
        self.assertEqual(result.status.error_code, "root_required")



if __name__ == "__main__":
    unittest.main()
