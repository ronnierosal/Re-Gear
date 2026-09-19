from pathlib import Path
import os
import shlex
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IdentityBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "scripts/install_regear_identity_migrator.sh").read_text(
            encoding="utf-8"
        )

    def test_installs_only_regear_live_deploy_authority(self):
        self.assertIn("NEW_ROOT=/var/lib/regear/deploy", self.source)
        self.assertIn("NEW_RULE=/etc/sudoers.d/regear-deploy-plugin", self.source)
        self.assertIn('"$NEW_HELPER" --self-check', self.source)
        self.assertIn('"$NEW_MIGRATOR" status', self.source)
        self.assertIn(
            '/usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_HELPER" --self-check',
            self.source,
        )
        self.assertIn(
            '/usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_MIGRATOR" status',
            self.source,
        )
        self.assertIn("visudo -cf", self.source)

    def test_sudo_policy_allows_only_exact_migrator_commands(self):
        for command in ("status", "apply", "rollback"):
            self.assertIn(
                "deck ALL=(root) NOPASSWD: "
                f"/var/lib/regear/deploy/regear-migrate-identity {command}",
                self.source,
            )
        self.assertNotIn(
            "NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity\n", self.source
        )

    def test_preserves_exact_rollback_authority_before_retiring_old_paths(self):
        backup = self.source.index("sha256sum previous-helper previous-public-key.pem")
        prepared = self.source.index("write_phase PREPARED")
        publish = self.source.index('install_if_absent_or_exact "$BACKUP/candidate-helper"')
        validate = self.source.index('"$NEW_MIGRATOR" status >/dev/null')
        retire = self.source.index('rm -f "$OLD_RULE" "$OLD_HELPER" "$OLD_KEY"')
        committed = self.source.index("write_phase COMMITTED")
        self.assertLess(backup, publish)
        self.assertLess(prepared, publish)
        self.assertLess(publish, validate)
        self.assertLess(validate, retire)
        self.assertLess(retire, committed)

    def test_current_rollback_hashes_include_migrator(self):
        self.assertIn(
            'same_or_absent "$BACKUP/candidate-migrator" "$NEW_MIGRATOR"',
            self.source,
        )
        self.assertIn(
            'rm -f "$NEW_RULE" "$NEW_HELPER" "$NEW_MIGRATOR" "$NEW_KEY"',
            self.source,
        )

    def test_candidates_are_snapshotted_and_verified_by_previous_root_key(self):
        self.assertIn('STAGED_HELPER_SIG=/home/deck/regear-deploy-plugin.sig', self.source)
        self.assertIn('STAGED_MIGRATOR_SIG=/home/deck/regear-migrate-identity.sig', self.source)
        self.assertIn('/usr/bin/openssl pkeyutl -verify -pubin', self.source)
        snapshot = self.source.index('install -m 0755 "$STAGED_HELPER" "$BACKUP_PREPARE/candidate-helper"')
        verify = self.source.index('verify_payload "$BACKUP_PREPARE"', snapshot)
        publish = self.source.index('install_if_absent_or_exact "$BACKUP/candidate-helper"')
        self.assertLess(snapshot, verify)
        self.assertLess(verify, publish)

    def test_phase_journal_allows_resume_and_rollback_before_commit(self):
        for phase in ("PREPARED", "CURRENT_VERIFIED", "RETIRING_FORMER", "OLD_RETIRED", "COMMITTED"):
            self.assertIn(phase, self.source)
        self.assertIn("PREPARED|CURRENT_VERIFIED|RETIRING_FORMER|OLD_RETIRED|COMMITTED", self.source)
        self.assertNotIn("bootstrap backup already exists", self.source)

    def test_prepare_is_fully_verified_before_atomic_publication(self):
        populate = self.source.index('install -p -m 0755 "$OLD_HELPER" "$BACKUP_PREPARE/previous-helper"')
        archive = self.source.index('archive_former_private "$BACKUP_PREPARE"')
        verify = self.source.index('verify_payload "$BACKUP_PREPARE"', archive)
        sync = self.source.index('sync -f "$BACKUP_PREPARE"', verify)
        publish = self.source.index('mv "$BACKUP_PREPARE" "$BACKUP"', sync)
        parent_sync = self.source.index('sync -f /var/lib/regear', publish)
        prepared = self.source.index("write_phase PREPARED", parent_sync)
        self.assertLess(populate, archive)
        self.assertLess(archive, verify)
        self.assertLess(verify, sync)
        self.assertLess(sync, publish)
        self.assertLess(publish, parent_sync)
        self.assertLess(parent_sync, prepared)

    def test_interrupted_prepare_is_replaced_only_after_root_private_validation(self):
        clear = self.source.index("clear_prepare()")
        validate = self.source.index('private_directory_safe "$BACKUP_PREPARE"', clear)
        remove = self.source.index('rm -rf -- "$BACKUP_PREPARE"', validate)
        create = self.source.index('mkdir -m 0700 "$BACKUP_PREPARE"', remove)
        self.assertLess(validate, remove)
        self.assertLess(remove, create)
        recovery = self.source.index('if test ! -e "$PHASE" && test ! -L "$PHASE"')
        self.assertLess(
            self.source.index('verify_payload "$BACKUP"', recovery),
            self.source.index("write_phase PREPARED", recovery),
        )

    def test_restore_checks_former_root_link_before_mkdir(self):
        restore = self.source.index("restore_former()")
        link_check = self.source.index('test ! -L "$OLD_ROOT"', restore)
        mkdir = self.source.index('mkdir -p "$OLD_ROOT"', restore)
        self.assertLess(link_check, mkdir)

    def test_private_archive_contract_is_crash_resumable_and_collision_safe(self):
        self.assertIn("former-private.names", self.source)
        self.assertIn("former-private.tar", self.source)
        self.assertIn("private.sha256", self.source)
        self.assertIn("compare_one_former_private", self.source)
        self.assertIn("verify_former_private_subset", self.source)
        self.assertIn('write_phase RETIRING_FORMER', self.source)
        self.assertIn('test -e "$path" || test -L "$path"', self.source)
        self.assertIn("--numeric-owner --acls --xattrs", self.source)

    def test_bootstrap_has_no_service_or_hardware_commands(self):
        commands = "\n".join(
            line for line in self.source.splitlines() if not line.lstrip().startswith("#")
        ).casefold()
        for forbidden in (
            "systemctl",
            "gamescope",
            "shutdown",
            "suspend",
            "/sys/",
            "boltctl",
        ):
            self.assertNotIn(forbidden, commands)


@unittest.skipUnless(os.name == "posix" and Path("/usr/bin/tar").is_file(), "GNU tar fixture requires Linux")
class FormerPrivateArchiveFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / "scripts/install_regear_identity_migrator.sh").read_text(encoding="utf-8")
        cls.functions = source.split('\ncase "$ACTION" in', 1)[0]

    def run_helper(self, plugin_parent: Path, backup: Path, commands: str):
        script = (
            self.functions
            + "\nPLUGIN_PARENT=" + shlex.quote(str(plugin_parent))
            + "\nBACKUP=" + shlex.quote(str(backup))
            + "\n" + commands + "\n"
        )
        return subprocess.run(
            ["/bin/sh"], input=script, text=True, capture_output=True, check=False
        )

    def test_archive_retire_resume_and_rollback_preserve_tree_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            backup = root / "backup"
            plugins.mkdir()
            backup.mkdir(mode=0o700)
            first = plugins / ".hdm-deploy-backups"
            second = plugins / ".hdm-staging-20260919-120000"
            (first / "nested").mkdir(parents=True)
            second.mkdir()
            payload = first / "nested" / "payload.bin"
            payload.write_bytes(b"preserve-me")
            os.chmod(first, 0o755)
            os.chmod(first / "nested", 0o750)
            os.chmod(payload, 0o640)
            os.utime(payload, (1_700_000_000, 1_700_000_000))
            (second / "marker").write_text("staged", encoding="utf-8")

            result = self.run_helper(
                plugins,
                backup,
                'archive_former_private "$BACKUP"\n'
                'rm -rf "$PLUGIN_PARENT/.hdm-deploy-backups"\n'
                'retire_former_private\n'
                'retire_former_private\n'
                'restore_former_private',
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            restored = first / "nested" / "payload.bin"
            self.assertEqual(restored.read_bytes(), b"preserve-me")
            self.assertEqual(stat.S_IMODE(restored.stat().st_mode), 0o640)
            self.assertEqual(int(restored.stat().st_mtime), 1_700_000_000)
            self.assertTrue((second / "marker").is_file())

    def test_restore_refuses_destination_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            backup = root / "backup"
            plugins.mkdir()
            backup.mkdir(mode=0o700)
            former = plugins / ".hdm-deploy-backups"
            former.mkdir()
            (former / "value").write_text("original", encoding="utf-8")
            result = self.run_helper(
                plugins,
                backup,
                'archive_former_private "$BACKUP"\n'
                'retire_former_private\n'
                'mkdir "$PLUGIN_PARENT/.hdm-deploy-backups"\n'
                'printf changed >"$PLUGIN_PARENT/.hdm-deploy-backups/value"\n'
                'restore_former_private',
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("changed", result.stderr)

    def test_discovery_refuses_unexpected_staging_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            backup = root / "backup"
            plugins.mkdir()
            backup.mkdir(mode=0o700)
            (plugins / ".hdm-staging-untrusted").mkdir()
            result = self.run_helper(plugins, backup, 'archive_former_private "$BACKUP"')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unexpected former private directory name", result.stderr)

    def test_partial_archive_never_authorizes_retirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugins = root / "plugins"
            backup = root / "backup"
            plugins.mkdir()
            backup.mkdir(mode=0o700)
            former = plugins / ".hdm-deploy-backups"
            former.mkdir()
            (former / "value").write_text("original", encoding="utf-8")
            result = self.run_helper(
                plugins,
                backup,
                'archive_former_private "$BACKUP"\n'
                ': >"$BACKUP/former-private.tar"\n'
                'retire_former_private',
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(former.is_dir())
            self.assertEqual((former / "value").read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
