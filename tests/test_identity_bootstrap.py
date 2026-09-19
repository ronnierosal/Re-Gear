from pathlib import Path
import copy
import hashlib
import json
import os
import shlex
import shutil
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
        for command in ("status", "reconcile-runtime", "apply", "rollback"):
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

    def test_rotation_is_explicit_and_pins_the_new_public_key_fingerprint(self):
        self.assertIn("install-rotated <new-public-key-sha256>", self.source)
        self.assertIn("STAGED_CURRENT_KEY=/home/deck/regear-deploy-public-key.pem", self.source)
        self.assertIn('valid_fingerprint "$REQUESTED_KEY_FINGERPRINT"', self.source)
        self.assertIn(
            'test "$(public_key_fingerprint "$authority/candidate-public-key.pem")" = "$fingerprint"',
            self.source,
        )
        self.assertIn(
            'verify_signature "$authority" "$authority/candidate-helper"',
            self.source,
        )
        self.assertIn(
            '-inkey "$authority/candidate-public-key.pem"', self.source
        )
        self.assertIn(
            "rotation candidate must differ from the former public key", self.source
        )

    def test_bootstrap_rejects_missing_or_extra_arguments_before_dispatch(self):
        self.assertIn("ARGUMENT_COUNT=$#", self.source)
        self.assertIn("0:install|1:install|1:rollback|2:install-rotated", self.source)
        self.assertIn("with no extra arguments", self.source)

    def test_rotation_snapshots_old_and_new_keys_before_publication(self):
        old = self.source.index(
            'install -p -m 0644 "$OLD_KEY" "$BACKUP_PREPARE/previous-public-key.pem"'
        )
        new = self.source.index(
            'install -m 0644 "$STAGED_CURRENT_KEY" "$BACKUP_PREPARE/candidate-public-key.pem"'
        )
        trust = self.source.index('>"$BACKUP_PREPARE/trust-mode"', new)
        verify = self.source.index('verify_payload "$BACKUP_PREPARE"', trust)
        publish = self.source.index(
            'install_if_absent_or_exact "$BACKUP/candidate-public-key.pem" "$NEW_KEY"'
        )
        self.assertLess(old, new)
        self.assertLess(new, trust)
        self.assertLess(trust, verify)
        self.assertLess(verify, publish)

    def test_resume_requires_the_original_trust_mode_and_fingerprint(self):
        self.assertIn('verify_trust_mode "$BACKUP" "$(expected_trust_mode)"', self.source)
        self.assertIn("bootstrap trust mode does not match this invocation", self.source)
        self.assertIn("candidate-public-key.pem trust-mode >candidate.sha256", self.source)

    def test_rollback_restores_the_former_key_not_the_rotated_key(self):
        self.assertIn(
            'install_if_absent_or_exact "$BACKUP/previous-public-key.pem" "$OLD_KEY" 0644',
            self.source,
        )
        self.assertIn(
            'same_or_absent "$BACKUP/candidate-public-key.pem" "$NEW_KEY"',
            self.source,
        )

    def test_phase_journal_allows_resume_and_rollback_before_commit(self):
        for phase in ("PREPARED", "CURRENT_VERIFIED", "RETIRING_FORMER", "OLD_RETIRED", "COMMITTED"):
            self.assertIn(phase, self.source)
        self.assertIn("PREPARED|CURRENT_VERIFIED|RETIRING_FORMER|OLD_RETIRED|COMMITTED", self.source)
        self.assertNotIn("bootstrap backup already exists", self.source)

    def test_committed_install_rerun_is_read_only_and_keeps_committed_phase(self):
        case = self.source.index('COMMITTED) verify_committed_authority ;;')
        self.assertGreater(case, self.source.index("install_authority()"))
        verify_start = self.source.index("verify_committed_authority()")
        verify_end = self.source.index("\n}", verify_start)
        verify_body = self.source[verify_start:verify_end]
        self.assertNotIn("write_phase", verify_body)
        self.assertNotIn("install_if_absent_or_exact", verify_body)
        self.assertNotIn("publish_current", verify_body)

    def test_bootstrap_rollback_requires_current_migrator_rollback_first(self):
        rollback = self.source.index("rollback_authority()")
        dependency = self.source.index("require_identity_rollback_first", rollback)
        restore = self.source.index("restore_former", dependency)
        remove = self.source.index("remove_current", restore)
        self.assertLess(dependency, restore)
        self.assertLess(restore, remove)
        self.assertIn('value.get("combined_journal_phase") in {None, "rolled_back"}', self.source)
        self.assertIn('value.get("journal_phase") in {None, "rolled_back"}', self.source)
        self.assertIn('dropin.get("journal_phase") in {None, "rolled_back"}', self.source)
        self.assertIn('dropin.get("current") == "absent"', self.source)
        self.assertIn(
            'value.get("control_conflict_phase") in {None, "committed"}',
            self.source,
        )

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
        # A read-only field in the migrator status payload is evidence, not a
        # Gamescope command or service operation.
        commands = commands.replace('value["gamescope_dropin"]', "")
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

    def create_keypair(self, directory: Path, name: str) -> tuple[Path, Path]:
        private = directory / f"{name}-private.pem"
        public = directory / f"{name}-public.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)
            ],
            check=True,
            capture_output=True,
        )
        return private, public

    def run_trust_fixture(self, authority: Path, commands: str):
        script = (
            self.functions
            + "\nroot_safe() { regular_no_link \"$1\"; }\n"
            + commands
            + "\n"
        )
        return subprocess.run(
            ["/bin/sh"], input=script, text=True, capture_output=True, check=False
        )

    def test_rotation_crypto_fixture_pins_distinct_key_and_exact_signatures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "authority"
            authority.mkdir()
            old_private, old_public = self.create_keypair(root, "old")
            new_private, new_public = self.create_keypair(root, "new")
            payload = authority / "candidate-helper"
            payload.write_bytes(b"candidate helper\n")
            signature = authority / "candidate-helper.sig"
            subprocess.run(
                [
                    "openssl", "pkeyutl", "-sign", "-inkey", str(new_private),
                    "-rawin", "-in", str(payload), "-out", str(signature),
                ],
                check=True,
                capture_output=True,
            )
            shutil.copy2(old_public, authority / "previous-public-key.pem")
            shutil.copy2(new_public, authority / "candidate-public-key.pem")
            fingerprint = hashlib.sha256(new_public.read_bytes()).hexdigest()
            (authority / "trust-mode").write_text(
                f"rotated:{fingerprint}\n", encoding="ascii"
            )
            result = self.run_trust_fixture(
                authority,
                f'verify_trust_mode {shlex.quote(str(authority))} rotated:{fingerprint}\n'
                f'verify_signature {shlex.quote(str(authority))} '
                f'{shlex.quote(str(payload))} {shlex.quote(str(signature))}',
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            reformatted_old = old_public.read_bytes().replace(b"\n", b"\r\n")
            (authority / "candidate-public-key.pem").write_bytes(reformatted_old)
            old_fingerprint = hashlib.sha256(reformatted_old).hexdigest()
            (authority / "trust-mode").write_text(
                f"rotated:{old_fingerprint}\n", encoding="ascii"
            )
            same = self.run_trust_fixture(
                authority, f'verify_trust_mode {shlex.quote(str(authority))}'
            )
            self.assertNotEqual(same.returncode, 0)
            self.assertIn("must differ", same.stderr)

    def test_rotation_crypto_fixture_refuses_wrong_fingerprint_and_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "authority"
            authority.mkdir()
            old_private, old_public = self.create_keypair(root, "old")
            _, new_public = self.create_keypair(root, "new")
            shutil.copy2(old_public, authority / "previous-public-key.pem")
            shutil.copy2(new_public, authority / "candidate-public-key.pem")
            (authority / "trust-mode").write_text(
                f"rotated:{'0' * 64}\n", encoding="ascii"
            )
            mismatch = self.run_trust_fixture(
                authority, f'verify_trust_mode {shlex.quote(str(authority))}'
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("fingerprint changed", mismatch.stderr)

            payload = authority / "candidate-helper"
            payload.write_bytes(b"candidate helper\n")
            signature = authority / "candidate-helper.sig"
            subprocess.run(
                [
                    "openssl", "pkeyutl", "-sign", "-inkey", str(old_private),
                    "-rawin", "-in", str(payload), "-out", str(signature),
                ],
                check=True,
                capture_output=True,
            )
            wrong = self.run_trust_fixture(
                authority,
                f'verify_signature {shlex.quote(str(authority))} '
                f'{shlex.quote(str(payload))} {shlex.quote(str(signature))}',
            )
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn("signature verification failed", wrong.stderr)

    def test_rotation_cli_rejects_missing_and_extra_arguments(self):
        script = ROOT / "scripts" / "install_regear_identity_migrator.sh"
        missing = subprocess.run(
            ["/bin/sh", str(script), "install-rotated"],
            text=True,
            capture_output=True,
            check=False,
        )
        extra = subprocess.run(
            ["/bin/sh", str(script), "install-rotated", "0" * 64, "extra"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertNotEqual(extra.returncode, 0)
        self.assertIn("no extra arguments", missing.stderr)
        self.assertIn("no extra arguments", extra.stderr)

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

    def test_reverse_order_guard_accepts_only_rolled_back_or_never_applied_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backup = root / "backup"
            backup.mkdir(mode=0o700)
            migrator = backup / "candidate-migrator"

            def run_status(payload: str):
                migrator.write_text(
                    "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(payload) + "\n",
                    encoding="utf-8",
                )
                migrator.chmod(0o700)
                script = (
                    self.functions
                    + "\nBACKUP=" + shlex.quote(str(backup))
                    + "\nCONTROL_ROOT=" + shlex.quote(str(root / "control"))
                    + "\nrequire_identity_rollback_first\n"
                )
                return subprocess.run(
                    ["/bin/sh"], input=script, text=True, capture_output=True, check=False
                )

            safe = {
                "locations": {"runtime": "old_only", "user": "old_only"},
                "journal_phase": "rolled_back",
                "combined_journal_phase": "rolled_back",
                "gamescope_dropin": {
                    "current": "absent",
                    "former": "former",
                    "journal_phase": "rolled_back",
                },
            }
            self.assertEqual(run_status(json.dumps(safe)).returncode, 0)

            state_applied = copy.deepcopy(safe)
            state_applied["journal_phase"] = "committed"
            combined_applied = copy.deepcopy(safe)
            combined_applied["combined_journal_phase"] = "committed"
            dropin_applied = copy.deepcopy(safe)
            dropin_applied["gamescope_dropin"]["journal_phase"] = "committed"
            current_dropin = copy.deepcopy(safe)
            current_dropin["gamescope_dropin"]["current"] = "current"
            applied_variants = (
                state_applied,
                combined_applied,
                dropin_applied,
                current_dropin,
            )
            for applied in applied_variants:
                with self.subTest(applied=applied):
                    refused = run_status(json.dumps(applied))
                    self.assertNotEqual(refused.returncode, 0)
                    self.assertIn("migrator rollback first", refused.stderr)

            (root / "control").mkdir()
            refused = run_status(json.dumps(safe))
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("control identity is still active", refused.stderr)


if __name__ == "__main__":
    unittest.main()
