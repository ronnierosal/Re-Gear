"""Static and extraction-contract tests for the root-side developer helper."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ally_hdm_deploy_helper", ROOT / "scripts" / "ally_hdm_deploy_helper.py")
assert SPEC and SPEC.loader
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


REVISION = "a" * 40
LINUX_ROOT = sys.platform == "linux" and os.geteuid() == 0


def write_package(path: Path, *, revision: str = REVISION, extra: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Re-Gear/plugin.json", "{}")
        archive.writestr("Re-Gear/main.py", "# test\n")
        archive.writestr("Re-Gear/package.json", json.dumps({"version": "0.2.0"}))
        archive.writestr("Re-Gear/build_info.json", json.dumps({"schema_version": 1, "version": "0.2.0", "revision": revision}))
        if extra is not None:
            archive.writestr(extra, "x")


class AllyDeployHelperTests(unittest.TestCase):
    def test_legacy_or_both_installations_refuse_before_reading_package(self):
        for new_present in (False, True):
            with self.subTest(new_present=new_present), tempfile.TemporaryDirectory() as temp:
                parent = Path(temp)
                (parent / "HandheldDockMode").mkdir()
                if new_present:
                    (parent / "Re-Gear").mkdir()
                with patch.object(helper, "PLUGIN_PARENT", parent), patch.object(helper, "fixed_download") as download:
                    with self.assertRaisesRegex(helper.DeploymentError, "supervised cutover"):
                        helper.install("Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip", "Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip.sig")
                    download.assert_not_called()

    @unittest.skipUnless(LINUX_ROOT, "requires Linux root descriptor semantics")
    def test_fresh_install_and_update_target_only_new_identity(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as temp:
                parent = Path(temp)
                target = parent / "Re-Gear"
                if existing:
                    target.mkdir()
                    (target / "old.txt").write_text("old")
                package = parent / "Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip"
                write_package(package)
                (parent / (package.name + ".sig")).write_bytes(b"signature")
                with patch.multiple(helper, PACKAGE_ROOT=parent, PLUGIN_PARENT=parent, TARGET=target, BACKUPS=parent / "backups"), patch.object(helper, "verify_signature"), patch.object(helper, "restart_plugin_loader"):
                    result = helper.install(package.name, package.name + ".sig")
                self.assertEqual(result["state"], "installed")
                self.assertTrue((target / "main.py").is_file())
                self.assertFalse((parent / "HandheldDockMode").exists())
                if existing:
                    self.assertEqual((Path(result["backup"]) / "old.txt").read_text(), "old")

    @unittest.skipUnless(LINUX_ROOT, "requires Linux root descriptor semantics")
    def test_update_loader_failure_restores_exact_old_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            target = parent / "Re-Gear"
            target.mkdir()
            (target / "old.txt").write_text("old")
            package = parent / "Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip"
            write_package(package)
            (parent / (package.name + ".sig")).write_bytes(b"signature")
            with patch.multiple(helper, PACKAGE_ROOT=parent, PLUGIN_PARENT=parent, TARGET=target, BACKUPS=parent / "backups"), patch.object(helper, "verify_signature"), patch.object(helper, "restart_plugin_loader", side_effect=[helper.DeploymentError("failed"), None]):
                with self.assertRaisesRegex(helper.DeploymentError, "rollback attempted"):
                    helper.install(package.name, package.name + ".sig")
            self.assertEqual((target / "old.txt").read_text(), "old")
            self.assertFalse((target / "main.py").exists())

    def test_legacy_and_mixed_archive_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "candidate.zip"
            for mixed in (False, True):
                with zipfile.ZipFile(package, "w") as archive:
                    archive.writestr("HandheldDockMode/main.py", "old")
                    if mixed:
                        archive.writestr("Re-Gear/main.py", "new")
                with self.assertRaisesRegex(helper.DeploymentError, "layout"):
                    helper.validate_and_extract(package, root / "unpacked", "0.2.0", "a" * 12)

    def test_rejects_path_arguments_before_touching_downloads(self):
        with self.assertRaises(helper.DeploymentError):
            helper.fixed_download("../Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip", ".zip")

    def test_extracts_only_complete_prefix_matched_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip"
            write_package(package)
            staged = helper.validate_and_extract(package, root / "unpacked", "0.2.0", "a" * 12)
            self.assertTrue((staged / "main.py").is_file())

    def test_rejects_revision_that_does_not_match_filename_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip"
            write_package(package, revision="b" * 40)
            with self.assertRaisesRegex(helper.DeploymentError, "provenance"):
                helper.validate_and_extract(package, root / "unpacked", "0.2.0", "a" * 12)

    def test_rejects_archive_escape_member(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip"
            write_package(package, extra="Re-Gear/../../outside")
            with self.assertRaisesRegex(helper.DeploymentError, "layout"):
                helper.validate_and_extract(package, root / "unpacked", "0.2.0", "a" * 12)

    def test_installer_has_constrained_sudo_command_and_no_session_actions(self):
        installer = (ROOT / "scripts" / "install_ally_deploy_helper.sh").read_text(encoding="utf-8")
        self.assertIn("install -d -m 0700 /var/lib/handheld-dock-mode", installer)
        self.assertIn("deck ALL=(root) NOPASSWD: /var/lib/handheld-dock-mode/hdm-deploy-plugin", installer)
        self.assertIn("helper itself rejects every argument", installer)
        self.assertNotIn("/usr/local", installer)
        self.assertNotIn("systemctl", installer)
        commands = "\n".join(
            line for line in installer.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("gamescope", commands.casefold())

    def test_helper_restarts_only_the_fixed_plugin_loader_after_replacement(self):
        source = (ROOT / "scripts" / "ally_hdm_deploy_helper.py").read_text(encoding="utf-8")
        self.assertIn('("restart", "plugin_loader.service")', source)
        self.assertIn('("is-active", "--quiet", "plugin_loader.service")', source)
        self.assertIn("plugin loader restart failed; rollback attempted", source)
        self.assertNotIn("gamescope-session", source.casefold())


@unittest.skipUnless(LINUX_ROOT, "requires Linux root descriptor semantics")
class PrivilegedInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.parent = self.root / "plugins"
        self.parent.mkdir()
        self.target = self.parent / "Re-Gear"
        self.backups = self.parent / "backups"
        self.package = self.root / "Re-Gear-update-0.2.0-aaaaaaaaaaaa.zip"
        self.signature = self.root / (self.package.name + ".sig")
        write_package(self.package)
        self.signature.write_bytes(b"signature")
        overrides = patch.multiple(helper, PACKAGE_ROOT=self.root, PLUGIN_PARENT=self.parent,
                                   TARGET=self.target, BACKUPS=self.backups)
        overrides.start()
        self.addCleanup(overrides.stop)
        restart = patch.object(helper, "restart_plugin_loader")
        self.restart = restart.start()
        self.addCleanup(restart.stop)

    def install(self):
        return helper.install(self.package.name, self.signature.name)

    def old_tree(self):
        self.target.mkdir()
        (self.target / "old.txt").write_bytes(b"exact old bytes\x00")

    def assert_old_tree(self, target=None):
        target = target or self.target
        self.assertEqual((target / "old.txt").read_bytes(), b"exact old bytes\x00")
        self.assertFalse((target / "main.py").exists())

    def test_input_inode_edits_after_verification_do_not_change_extracted_bytes(self):
        def verified(package, signature, **kwargs):
            self.assertNotEqual(package, self.package)
            self.assertEqual(signature.read_bytes(), b"signature")
            # Mutate the SAME inode, which retaining a source fd cannot prevent.
            self.package.write_bytes(b"attacker replaced the verified inode")
            self.signature.write_bytes(b"changed")
        with patch.object(helper, "verify_signature", side_effect=verified):
            self.install()
        self.assertEqual((self.target / "main.py").read_text(), "# test\n")

    def test_signature_failure_never_extracts_or_restarts(self):
        self.old_tree()
        with patch.object(helper, "verify_signature", side_effect=helper.DeploymentError("bad signature")), patch.object(helper, "validate_and_extract") as extract:
            with self.assertRaisesRegex(helper.DeploymentError, "bad signature"):
                self.install()
            extract.assert_not_called()
        self.restart.assert_not_called()
        self.assert_old_tree()

    def test_copy_limit_rejects_growth_after_initial_stat(self):
        original_fstat = os.fstat
        source_inode = self.package.stat().st_ino
        limit = self.package.stat().st_size
        destination = self.root / "snapshot"
        def grow(fd):
            status = original_fstat(fd)
            if status.st_ino == source_inode:
                with self.package.open("ab") as output:
                    output.write(b"growth beyond limit")
            return status
        with patch.object(helper.os, "fstat", side_effect=grow):
            with self.assertRaisesRegex(helper.DeploymentError, "size"):
                helper.snapshot_download(self.package.name, destination, limit)
        self.assertLessEqual(destination.stat().st_size, limit)

    def test_permissive_caller_umask_does_not_publish_writable_code(self):
        previous = os.umask(0)
        try:
            with patch.object(helper, "verify_signature"):
                self.install()
        finally:
            os.umask(previous)
        self.assertEqual(self.target.stat().st_mode & 0o022, 0)
        self.assertEqual((self.target / "main.py").stat().st_mode & 0o022, 0)

    def test_download_symlink_and_fifo_rejected_before_verification(self):
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind):
                self.package.unlink()
                if kind == "symlink":
                    self.package.symlink_to(self.signature)
                else:
                    os.mkfifo(self.package)
                with patch.object(helper, "verify_signature") as verify:
                    with self.assertRaises((OSError, helper.DeploymentError)):
                        self.install()
                    verify.assert_not_called()
                self.package.unlink()
                write_package(self.package)

    def test_unsafe_preexisting_backup_directory_rejected_without_repair(self):
        for mode, owner in ((0o777, 0), (0o700, 65534)):
            with self.subTest(mode=mode, owner=owner):
                self.backups.mkdir(mode=mode)
                self.backups.chmod(mode)
                os.chown(self.backups, owner, owner)
                with patch.object(helper, "verify_signature") as verify:
                    with self.assertRaisesRegex(helper.DeploymentError, "backup authority"):
                        self.install()
                    verify.assert_not_called()
                self.assertEqual(self.backups.stat().st_uid, owner)
                self.assertEqual(self.backups.stat().st_mode & 0o777, mode)
                self.backups.rmdir()

    def test_backup_symlink_rejected_without_touching_destination(self):
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "marker"
        marker.write_text("unchanged")
        self.backups.symlink_to(outside, target_is_directory=True)
        with patch.object(helper, "verify_signature") as verify:
            with self.assertRaises(OSError):
                self.install()
            verify.assert_not_called()
        self.assertEqual(marker.read_text(), "unchanged")

    def test_intermediate_plugin_parent_symlink_is_rejected(self):
        outside = self.root / "outside"
        (outside / "plugins").mkdir(parents=True)
        marker = outside / "plugins" / "marker"
        marker.write_text("unchanged")
        link = self.root / "homebrew"
        link.symlink_to(outside, target_is_directory=True)
        with patch.object(helper, "PLUGIN_PARENT", link / "plugins"), patch.object(helper, "verify_signature") as verify:
            with self.assertRaises(OSError):
                self.install()
            verify.assert_not_called()
        self.assertEqual(list((outside / "plugins").iterdir()), [marker])

    def test_renamed_backup_parent_cannot_substitute_extracted_stage(self):
        original_extract = helper.validate_and_extract
        moved = self.parent / "moved-backups"
        def swap(package, stage, *args):
            result = original_extract(package, stage, *args)
            self.backups.rename(moved)
            decoy = self.backups / stage.name / "Re-Gear"
            decoy.mkdir(parents=True)
            (decoy / "main.py").write_text("attacker")
            return result
        with patch.object(helper, "verify_signature"), patch.object(helper, "validate_and_extract", side_effect=swap):
            self.install()
        self.assertEqual((self.target / "main.py").read_text(), "# test\n")
        self.assertEqual(next(self.backups.glob("*/Re-Gear/main.py")).read_text(), "attacker")
        self.assertEqual(list(moved.iterdir()), [])

    def test_loader_failure_rolls_back_through_renamed_backup_directory(self):
        self.old_tree()
        moved = self.parent / "moved-backups"
        def fail():
            if self.restart.call_count == 1:
                self.backups.rename(moved)
                self.backups.mkdir()
                raise helper.DeploymentError("failed")
        self.restart.side_effect = fail
        with patch.object(helper, "verify_signature"):
            with self.assertRaisesRegex(helper.DeploymentError, "rollback attempted"):
                self.install()
        self.assert_old_tree()
        self.assertEqual(list(self.backups.iterdir()), [])
        self.assertEqual(len(list(moved.glob("*.loader-failed-*"))), 1)

    def test_parent_path_swap_does_not_redirect_publication_or_rollback(self):
        self.old_tree()
        original_extract = helper.validate_and_extract
        moved = self.root / "moved-plugins"
        def swap(*args):
            result = original_extract(*args)
            self.parent.rename(moved)
            self.target.mkdir(parents=True)
            (self.target / "main.py").write_text("decoy")
            return result
        self.restart.side_effect = [helper.DeploymentError("failed"), None]
        with patch.object(helper, "verify_signature"), patch.object(helper, "validate_and_extract", side_effect=swap):
            with self.assertRaisesRegex(helper.DeploymentError, "rollback attempted"):
                self.install()
        self.assert_old_tree(moved / "Re-Gear")
        self.assertEqual((self.target / "main.py").read_text(), "decoy")

    def test_publication_failure_restores_old_tree(self):
        self.old_tree()
        replace = os.replace
        def fail_stage(source, destination, **kwargs):
            if str(source).startswith(".stage-"):
                raise OSError("publication failed")
            return replace(source, destination, **kwargs)
        with patch.object(helper, "verify_signature"), patch.object(helper.os, "replace", side_effect=fail_stage):
            with self.assertRaisesRegex(helper.DeploymentError, "replacement failed"):
                self.install()
        self.assert_old_tree()
        self.restart.assert_not_called()

    def test_known_limitation_successful_restart_can_read_swapped_canonical_parent(self):
        # Characterize the unresolved loader execution boundary, not a fixed
        # security property: retained fds confine publication but cannot bind
        # an independent service's future canonical-path opens.
        original_extract = helper.validate_and_extract
        moved = self.root / "moved-plugins"
        loaded = []
        def swap(*args):
            result = original_extract(*args)
            self.parent.rename(moved)
            self.target.mkdir(parents=True)
            (self.target / "main.py").write_text("unverified decoy")
            return result
        def successful_loader():
            loaded.append((self.target / "main.py").read_text())
        self.restart.side_effect = successful_loader
        with patch.object(helper, "verify_signature"), patch.object(helper, "validate_and_extract", side_effect=swap):
            result = self.install()
        self.assertEqual(result["state"], "installed")
        self.assertEqual(result["loader"], "active")
        self.assertEqual((moved / "Re-Gear" / "main.py").read_text(), "# test\n")
        self.assertEqual(loaded, ["unverified decoy"])

    def test_fresh_loader_failure_removes_failed_install(self):
        self.restart.side_effect = [helper.DeploymentError("failed"), None]
        with patch.object(helper, "verify_signature"):
            with self.assertRaisesRegex(helper.DeploymentError, "rollback attempted"):
                self.install()
        self.assertFalse(self.target.exists())
        self.assertEqual(len(list(self.backups.glob("*.loader-failed-*"))), 1)

    def test_snapshots_and_stage_deny_unprivileged_writes(self):
        self.root.chmod(0o755)
        self.parent.chmod(0o777)
        def verified(package, signature, **kwargs):
            # Address the actual directory entry: /proc/self in a child would
            # refer to that child's fd table, not the helper's retained fd.
            on_disk = self.backups / package.parent.name / package.name
            result = subprocess.run([sys.executable, "-c",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'attack')", str(on_disk)],
                user=65534, group=65534, extra_groups=(), capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"PermissionError", result.stderr)
        with patch.object(helper, "verify_signature", side_effect=verified):
            self.install()

    def test_real_ed25519_verification_uses_protected_snapshot_fds(self):
        key, public = self.root / "private.pem", self.root / "public.pem"
        for arguments in (
            ["genpkey", "-algorithm", "ED25519", "-out", str(key)],
            ["pkey", "-in", str(key), "-pubout", "-out", str(public)],
            ["pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(self.package), "-out", str(self.signature)],
        ):
            subprocess.run(["/usr/bin/openssl", *arguments], check=True, capture_output=True, timeout=15)
        with patch.object(helper, "PUBLIC_KEY", public):
            self.install()
            self.signature.write_bytes(b"tampered signature")
            with self.assertRaisesRegex(helper.DeploymentError, "signature verification failed"):
                self.install()
        self.assertEqual((self.target / "main.py").read_text(), "# test\n")
