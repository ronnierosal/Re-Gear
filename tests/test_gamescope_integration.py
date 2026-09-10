from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from regear.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402
from regear.delivery.user_directory import UserDirectory  # noqa: E402


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

    def legacy_dropin_text(self, store, root: Path) -> str:
        """The exact file an install written under the old plugin name still has.

        It differs from the current rendering only in the plugin directory, which
        is what the rename moved.
        """
        current = (root / "plugin" / "bin").as_posix()
        legacy = (root / "HandheldDockMode" / "bin").as_posix()
        text = store.expected_text()
        self.assertIn(current, text)
        return text.replace(current, legacy)

    def test_dropin_from_a_previous_plugin_name_is_migrated_not_stranded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self.make_store(root)
            store.target.parent.mkdir(parents=True)
            stranded = self.legacy_dropin_text(store, root)
            store.target.write_text(stranded, encoding="utf-8", newline="\n")

            before = store.status()
            self.assertTrue(before.installed)
            self.assertFalse(before.matches)
            self.assertFalse(before.ready)
            self.assertEqual(before.error_code, "managed_dropin_superseded")

            result = store.activate()
            self.assertTrue(result.ok, result.status)
            self.assertEqual(
                store.target.read_text(encoding="utf-8"), store.expected_text()
            )
            after = store.status()
            self.assertTrue(after.ready)
            self.assertEqual(after.error_code, "")

            # Migration must leave the drop-in reversible through Re-Gear.
            self.assertTrue(store.deactivate().changed)
            self.assertFalse(store.target.exists())

    def test_managed_marker_with_an_unknown_plugin_path_is_still_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self.make_store(root)
            store.target.parent.mkdir(parents=True)
            # Carries our marker, but renders a directory we never shipped.
            foreign = store.expected_text().replace(
                (root / "plugin" / "bin").as_posix(), "/opt/somewhere/bin"
            )
            store.target.write_text(foreign, encoding="utf-8", newline="\n")

            self.assertEqual(store.status().error_code, "managed_dropin_modified")
            self.assertFalse(store.activate().ok)
            self.assertEqual(store.target.read_text(encoding="utf-8"), foreign)

    def test_failed_upgrade_publication_restores_prior_dropin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self.make_store(root)
            store.target.parent.mkdir(parents=True)
            prior = self.legacy_dropin_text(store, root).encode()
            store.target.write_bytes(prior)
            publish = UserDirectory.publish
            def fail_new(target, name, data, mode):
                if data == store.expected_text().encode():
                    raise OSError("injected publication failure")
                return publish(target, name, data, mode)
            with patch.object(UserDirectory, "publish", fail_new):
                self.assertFalse(store.activate().ok)
            self.assertEqual(store.target.read_bytes(), prior)
            self.assertTrue(store.activate().ok)

    def test_failed_rollback_publication_retains_prepared_file_and_retry_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self.make_store(root)
            store.target.parent.mkdir(parents=True)
            prior = self.legacy_dropin_text(store, root).encode()
            store.target.write_bytes(prior)
            self.assertTrue(store.activate().ok)
            publish = UserDirectory.publish
            def fail_prior(target, name, data, mode):
                if data == prior:
                    raise OSError("injected rollback publication failure")
                return publish(target, name, data, mode)
            with patch.object(UserDirectory, "publish", fail_prior):
                self.assertFalse(store.rollback_activation().changed)
            self.assertEqual(store.target.read_bytes(), store.expected_text().encode())
            self.assertTrue(store.rollback_activation().changed)
            self.assertEqual(store.target.read_bytes(), prior)

    def test_persistent_rollback_publication_failure_can_recover_absent_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = self.make_store(root)
            store.target.parent.mkdir(parents=True)
            prior = self.legacy_dropin_text(store, root).encode()
            store.target.write_bytes(prior)
            self.assertTrue(store.activate().ok)
            with patch.object(UserDirectory, "publish", side_effect=OSError("persistent failure")):
                self.assertFalse(store.rollback_activation().changed)
            self.assertFalse(store.target.exists())
            self.assertEqual(store._activation_rollback[0], prior)
            self.assertTrue(store.rollback_activation().changed)
            self.assertEqual(store.target.read_bytes(), prior)

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


if __name__ == "__main__":
    unittest.main()
#: The stranded drop-in observed on the tested Ally X while validating #161.
#: Byte-for-byte what an install written under the old plugin name still has;
#: it differs from the current rendering only in the plugin directory.
DEVICE_STRANDED_DROPIN = (
    "# Managed by Handheld Dock Mode. Remove only through HDM.\n"
    "[Service]\n"
    'Environment="PATH=/home/deck/homebrew/plugins/HandheldDockMode/bin:'
    '/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin"\n'
    'Environment="HDM_STATE_ROOT=/home/deck/.local/share/handheld-dock-mode"\n'
)

#: Those device paths are absolute only on POSIX; Windows cannot represent them
#: as absolute, and the store rejects non-absolute roots by design.
REQUIRES_POSIX_PATHS = unittest.skipUnless(
    os.name != "nt", "absolute POSIX paths are unavailable on this host"
)


@REQUIRES_POSIX_PATHS
class StrandedDeviceDropinTests(unittest.TestCase):
    """Pin the exact file that stranded display switching on the Ally."""

    def make_device_store(self):
        home = Path("/home/deck")
        user = GamescopeUserContext(
            "deck", 1000, 1000, home, Path("/run/user/1000"), Path("/run/user/1000/bus")
        )
        return GamescopeIntegrationStore(
            plugin_root=Path("/home/deck/homebrew/plugins/Re-Gear"),
            user=user,
            effective_uid=lambda: 0,
            set_owner=lambda path, uid, gid: None,
        )

    def test_observed_dropin_is_recognised_as_our_own_prior_rendering(self):
        store = self.make_device_store()
        self.assertEqual(len(DEVICE_STRANDED_DROPIN.encode("utf-8")), 269)
        # It genuinely does not match the current rendering -- that is the bug.
        self.assertNotEqual(store.expected_text(), DEVICE_STRANDED_DROPIN)
        # ...but it is ours, so it is migratable rather than a player edit.
        self.assertIn(DEVICE_STRANDED_DROPIN, store._superseded_renderings())

    def test_current_rendering_points_at_the_new_plugin_directory(self):
        store = self.make_device_store()
        self.assertIn("/home/deck/homebrew/plugins/Re-Gear/bin", store.expected_text())
