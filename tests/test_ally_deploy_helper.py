"""Static and extraction-contract tests for the root-side developer helper."""
from __future__ import annotations

import importlib.util
import json
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
