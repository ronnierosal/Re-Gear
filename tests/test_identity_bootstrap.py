from pathlib import Path
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
        snapshot = self.source.index('install -m 0755 "$STAGED_HELPER" "$BACKUP/candidate-helper"')
        verify = self.source.index('verify_signature "$BACKUP/candidate-helper"', snapshot)
        publish = self.source.index('install_if_absent_or_exact "$BACKUP/candidate-helper"')
        self.assertLess(snapshot, verify)
        self.assertLess(verify, publish)

    def test_phase_journal_allows_resume_and_rollback_before_commit(self):
        for phase in ("PREPARED", "CURRENT_VERIFIED", "OLD_RETIRED", "COMMITTED"):
            self.assertIn(phase, self.source)
        self.assertIn("PREPARED|CURRENT_VERIFIED|OLD_RETIRED|COMMITTED", self.source)
        self.assertNotIn("bootstrap backup already exists", self.source)

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


if __name__ == "__main__":
    unittest.main()
