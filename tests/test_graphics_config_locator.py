from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import graphics_profile_fixtures as fixtures  # noqa: E402
from regear.delivery.graphics_config_locator import (  # noqa: E402
    GraphicsConfigLocator,
    LocationProblem,
    Runtime,
)
from regear.domain.models import OperatingMode  # noqa: E402


class LocatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.steam_root = fixtures.build_library(self.base)
        self.locator = GraphicsConfigLocator(self.steam_root)

    def locate(self, app_id, filename=fixtures.CONFIG_FILENAME, relative=fixtures.GAME_CONFIG_DIR):
        return self.locator.locate(app_id, filename, OperatingMode.PORTABLE, relative)

    def test_relative_steam_root_is_refused(self):
        with self.assertRaises(ValueError):
            GraphicsConfigLocator(Path("steam"))

    def test_library_roots_include_the_root_and_a_declared_library(self):
        extra = self.base / "sdcard"
        steam_root = fixtures.build_library(self.base / "second", extra_library=extra)
        roots = GraphicsConfigLocator(steam_root).library_roots()
        self.assertEqual(roots, (steam_root, extra))

    def test_declared_library_without_steamapps_is_ignored(self):
        steam_root = fixtures.build_library(self.base / "third")
        manifest = steam_root / "steamapps" / "libraryfolders.vdf"
        manifest.write_text(
            '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"/nonexistent/library"\n\t}\n}\n',
            encoding="utf-8",
        )
        self.assertEqual(GraphicsConfigLocator(steam_root).library_roots(), (steam_root,))

    def test_proton_game_resolves_into_the_prefix(self):
        outcome = self.locate(fixtures.PROTON_APP_ID)
        self.assertTrue(outcome.located)
        self.assertIs(outcome.location.runtime, Runtime.PROTON)
        self.assertEqual(
            outcome.location.config_path, fixtures.proton_config_path(self.steam_root)
        )

    def test_native_game_resolves_into_the_install_directory(self):
        outcome = self.locate(fixtures.NATIVE_APP_ID)
        self.assertTrue(outcome.located)
        self.assertIs(outcome.location.runtime, Runtime.NATIVE)
        self.assertEqual(
            outcome.location.config_path, fixtures.native_config_path(self.steam_root)
        )

    def test_identity_distinguishes_app_runtime_and_file(self):
        proton = self.locate(fixtures.PROTON_APP_ID).location
        native = self.locate(fixtures.NATIVE_APP_ID).location
        self.assertNotEqual(proton.identity, native.identity)
        self.assertTrue(proton.identity.startswith(f"{fixtures.PROTON_APP_ID}.proton."))

    def test_uninstalled_app_is_reported(self):
        outcome = self.locate("999999")
        self.assertIs(outcome.problem, LocationProblem.NOT_INSTALLED)

    def test_absent_configuration_is_reported(self):
        outcome = self.locate(fixtures.PROTON_APP_ID, filename="missing.ini")
        self.assertIs(outcome.problem, LocationProblem.CONFIG_ABSENT)

    def test_unknown_format_has_no_adapter(self):
        outcome = self.locate(fixtures.PROTON_APP_ID, filename="settings.json")
        self.assertIs(outcome.problem, LocationProblem.NO_ADAPTER)

    def test_traversal_out_of_the_prefix_is_refused(self):
        outcome = self.locate(fixtures.PROTON_APP_ID, relative="../../../../../../../../etc")
        self.assertIs(outcome.problem, LocationProblem.ESCAPES_ROOT)

    def test_symlink_pointing_outside_the_prefix_is_refused_as_escaping(self):
        # Containment is judged on the resolved target, so a link out of the
        # prefix is refused for where it really goes, not merely for being one.
        target = self.base / "outside.ini"
        target.write_text("[G]\nk=1\n", encoding="utf-8")
        link = fixtures.proton_config_path(self.steam_root).parent / "outward.ini"
        link.symlink_to(target)
        outcome = self.locate(fixtures.PROTON_APP_ID, filename="outward.ini")
        self.assertIs(outcome.problem, LocationProblem.ESCAPES_ROOT)

    def test_symlink_inside_the_prefix_is_still_not_located(self):
        inside = fixtures.proton_config_path(self.steam_root)
        link = inside.parent / "linked.ini"
        link.symlink_to(inside)
        outcome = self.locate(fixtures.PROTON_APP_ID, filename="linked.ini")
        self.assertIs(outcome.problem, LocationProblem.CONFIG_ABSENT)

    def test_malformed_app_id_raises_rather_than_searching(self):
        for value in ("", "0", "abc", "12; rm -rf /", "../620"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.locate(value)

    def test_manifest_with_a_traversing_installdir_is_ignored(self):
        manifest = (
            self.steam_root / "steamapps" / f"appmanifest_{fixtures.NATIVE_APP_ID}.acf"
        )
        manifest.write_text(
            '"AppState"\n{\n\t"installdir"\t\t"../../../etc"\n}\n', encoding="utf-8"
        )
        self.assertIsNone(self.locator.install_directory(fixtures.NATIVE_APP_ID))

    def test_locating_writes_nothing(self):
        before = sorted(path.stat().st_mtime_ns for path in self.steam_root.rglob("*"))
        names_before = sorted(str(path) for path in self.steam_root.rglob("*"))
        self.locate(fixtures.PROTON_APP_ID)
        self.assertEqual(
            sorted(path.stat().st_mtime_ns for path in self.steam_root.rglob("*")), before
        )
        self.assertEqual(
            sorted(str(path) for path in self.steam_root.rglob("*")), names_before
        )


if __name__ == "__main__":
    unittest.main()
