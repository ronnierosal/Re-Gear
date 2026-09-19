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
        self.assertIn(
            '/usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_HELPER" --self-check',
            self.source,
        )
        self.assertIn("visudo -cf", self.source)

    def test_preserves_exact_rollback_authority_before_retiring_old_paths(self):
        backup = self.source.index('sha256sum "$BACKUP/previous-helper"')
        publish = self.source.index('install -m 0755 "$STAGED_HELPER" "$NEW_HELPER"')
        retire = self.source.index('rm -f "$OLD_RULE" "$OLD_HELPER" "$OLD_KEY"')
        committed = self.source.index(': >"$BACKUP/COMMITTED"')
        self.assertLess(backup, publish)
        self.assertLess(publish, retire)
        self.assertLess(retire, committed)

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
