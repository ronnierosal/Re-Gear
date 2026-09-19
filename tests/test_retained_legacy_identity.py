"""Installed identity contract for the completed Re-Gear cutover.

Current writers must use only Re-Gear names. Former names are allowed in a
small, reviewed set of exact migration, rollback, and historical readers so an
installed device can be migrated without abandoning safety state.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos import inhibitor_guard  # noqa: E402
from regear.adapters.steamos.gamescope_user import GamescopeUserContext  # noqa: E402
from regear.delivery import (  # noqa: E402
    gamescope_integration,
    runtime_state,
    whole_dock_completion,
    whole_dock_reset,
)
from regear.delivery.gamescope_integration import GamescopeIntegrationStore  # noqa: E402


SPEC = importlib.util.spec_from_file_location(
    "ally_deploy_helper_identity", ROOT / "scripts" / "ally_deploy_helper.py"
)
assert SPEC and SPEC.loader
_helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(_helper)


def _store(root: Path) -> GamescopeIntegrationStore:
    home = root / "home" / "deck"
    home.mkdir(parents=True)
    plugin = root / "plugin" / "Re-Gear"
    shim = plugin / "bin" / "gamescope"
    shim.parent.mkdir(parents=True)
    shim.write_text("#!/usr/bin/python3\n# Re-Gear Gamescope argument shim\n", encoding="utf-8")
    uid = getattr(os, "getuid", lambda: 1000)()
    gid = getattr(os, "getgid", lambda: 1000)()
    user = GamescopeUserContext(
        "deck", uid, gid, home,
        Path("/run/user") / str(uid), Path("/run/user") / str(uid) / "bus",
    )
    return GamescopeIntegrationStore(
        plugin_root=plugin,
        user=user,
        effective_uid=lambda: 0,
        set_owner=lambda path, user_id, group_id: None,
    )


class CurrentInstalledIdentityTests(unittest.TestCase):
    def test_gamescope_current_writer_uses_only_regear_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = _store(Path(directory))
            rendered = store.expected_text()

        self.assertEqual(gamescope_integration.DROPIN_NAME, "90-regear.conf")
        self.assertEqual(
            gamescope_integration.SHIM_MARKER,
            "Re-Gear Gamescope argument shim",
        )
        self.assertEqual(store.state_root.name, "regear")
        self.assertTrue(rendered.startswith("# Managed by Re-Gear. Remove only through Re-Gear.\n"))
        self.assertIn("REGEAR_STATE_ROOT=", rendered)
        self.assertNotIn("HDM_STATE_ROOT=", rendered)
        self.assertNotIn("handheld-dock-mode", rendered)

    def test_all_current_control_callers_share_the_regear_root(self) -> None:
        expected = Path("/var/lib/regear/control")
        self.assertEqual(runtime_state.DEFAULT_RUNTIME_STATE_ROOT, expected)
        self.assertEqual(whole_dock_completion.ROOT, expected)
        self.assertEqual(whole_dock_reset.ROOT, expected)
        with self.assertRaises(ValueError):
            runtime_state.RootOwnedRuntimeState(Path("/var/lib/regear"))

    def test_current_inhibitor_and_deploy_authority_use_regear(self) -> None:
        self.assertEqual(inhibitor_guard.INHIBITOR_WHO, "Re-Gear")
        self.assertEqual(_helper.PLUGIN_NAME, "Re-Gear")
        self.assertEqual(_helper.DEPLOY_ROOT, Path("/var/lib/regear/deploy"))
        self.assertEqual(_helper.PUBLIC_KEY, Path("/var/lib/regear/deploy/deploy-public-key.pem"))
        self.assertEqual(_helper.BACKUPS.name, ".regear-deploy-backups")


class FormerIdentityBoundaryTests(unittest.TestCase):
    """Former names may be read for migration; no normal writer may emit them."""

    ALLOWED_SOURCES = frozenset(
        {
            "backend/regear/application/support_bundle.py",
            "backend/regear/delivery/gamescope_integration.py",
            "backend/regear/delivery/gamescope_wrapper.py",
            "backend/regear/delivery/identity_migration.py",
            "backend/regear/delivery/steam_trial_activation.py",
            "scripts/ally_deploy_helper.py",
            "scripts/capture_shutdown_evidence.py",
            "scripts/check_plugin_package.py",
            "scripts/community_report.py",
            "scripts/deploy_to_ally.ps1",
            "scripts/install_regear_identity_migrator.sh",
            "scripts/probe_steam_suspend_store.mjs",
            "scripts/verify_validation_artifact.py",
            "src/identity-storage.ts",
        }
    )
    FORMER_TOKENS = (
        "Handheld Dock Mode",
        "HandheldDockMode",
        "handheld-dock-mode",
        "HDM_STATE_ROOT",
        "HDM shutdown checkpoint",
        "hdm.hideAttached",
        "hdm-deploy-plugin",
        '"hdm"',
        "'hdm'",
        "(?:Re-Gear|HDM)",
    )

    def test_former_literals_are_bounded_to_migration_and_historical_readers(self) -> None:
        observed: set[str] = set()
        for root_name in ("backend", "scripts", "src", "bin"):
            for path in (ROOT / root_name).rglob("*"):
                if not path.is_file() or path.suffix in {".pyc", ".map"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if any(token in text for token in self.FORMER_TOKENS):
                    observed.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(observed, set(self.ALLOWED_SOURCES))

    def test_compatibility_names_are_not_current_targets(self) -> None:
        self.assertNotEqual(
            gamescope_integration.LEGACY_DROPIN_NAME,
            gamescope_integration.DROPIN_NAME,
        )
        self.assertNotEqual(_helper.LEGACY_NAME, _helper.PLUGIN_NAME)


if __name__ == "__main__":
    unittest.main()
