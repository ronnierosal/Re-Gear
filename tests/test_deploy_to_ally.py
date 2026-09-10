from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DirectDeployScriptTests(unittest.TestCase):
    def source(self) -> str:
        return (ROOT / "scripts" / "deploy_to_ally.ps1").read_text(encoding="utf-8")

    def test_requires_explicit_confirmation_and_interactive_sudo_option(self):
        source = self.source()
        self.assertIn("[switch]$ConfirmDeploy", source)
        self.assertIn("[switch]$InteractiveSudo", source)
        self.assertIn("if (-not $ConfirmDeploy)", source)
        self.assertIn('$UseCorepackPnpm = -not (Get-Command "pnpm"', source)
        self.assertIn('Invoke-Checked "corepack" (@("pnpm") + $Arguments)', source)

    def test_backups_replacement_exec_bit_restart_and_provenance_are_ordered(self):
        source = self.source()
        self.assertIn("Re-Gear.backup-", source)
        self.assertIn('mv "`$PLUGIN_DIR" "`$BACKUP"', source)
        self.assertIn('chmod 0755 "`$PLUGIN_DIR/bin/gamescope"', source)
        self.assertIn("systemctl restart plugin_loader.service", source)
        self.assertLess(source.index('mv "`$STAGING/Re-Gear" "`$PLUGIN_DIR"'), source.index("systemctl restart plugin_loader.service"))
        self.assertIn("build_info.json", source)

    def test_never_targets_session_or_hardware_actions(self):
        source = self.source().casefold()
        self.assertNotIn("systemctl restart gamescope", source)
        self.assertNotIn("systemctl suspend", source)
        self.assertNotIn("reboot", source)
        self.assertNotIn("usb4", source)
        self.assertNotIn("amdgpu", source)


if __name__ == "__main__":
    unittest.main()


class IdentityCutoverGuardTests(unittest.TestCase):
    def test_legacy_refusal_precedes_staging_and_replacement(self):
        source = (Path(__file__).resolve().parents[1] / "scripts/deploy_to_ally.ps1").read_text(encoding="utf-8")
        self.assertIn('LEGACY_DIR="`$PLUGIN_PARENT/HandheldDockMode"', source)
        self.assertIn('test -e "`$LEGACY_DIR" || test -L "`$LEGACY_DIR"', source)
        self.assertLess(source.index("Legacy installation requires supervised cutover"), source.index('mkdir -p "`$PLUGIN_PARENT"'))
