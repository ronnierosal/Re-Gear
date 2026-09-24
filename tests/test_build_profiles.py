"""Exercise profile admission and archive identity without reserving releases."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_plugin, build_profiles, release_coordination


class BuildProfileTests(unittest.TestCase):
    def test_development_records_existing_runtime_without_ga_claim(self):
        profile = build_profiles.package_profile()
        self.assertEqual("development", profile["profile"])
        self.assertEqual("existing_development_surface", profile["feature_policy"])
        self.assertEqual(64, len(profile["contract_sha256"]))
        self.assertEqual(profile, build_profiles.validate_packaged_profile(profile))

    def test_profile_is_deterministic_across_contract_formatting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            contract = build_profiles.load_contract()
            path = root / "contracts/build-profiles.json"
            path.write_text(json.dumps(contract, indent=4), encoding="utf-8")
            self.assertEqual(build_profiles.package_profile(), build_profiles.package_profile(root=root))

    def test_bad_or_expanded_contract_does_not_authorize_packaging(self):
        values = [None, [], {}, {"schema_version": True, "profiles": {}}, build_profiles.load_contract()]
        values[-1]["profiles"]["production"]["package_enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            path = root / "contracts/build-profiles.json"
            for value in values:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "profile_contract_invalid"):
                        build_profiles.package_profile(root=root)

    def test_unknown_profile_is_not_development_fallback(self):
        with self.assertRaisesRegex(ValueError, "profile_unknown"):
            build_profiles.package_profile("prod")

    def test_production_refuses_before_reservation_or_git_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist.zip"
            errors = io.StringIO()
            with (
                patch.object(build_plugin, "OUTPUT", output),
                patch.object(build_plugin, "source_revision") as revision,
                patch.object(release_coordination, "reserve") as reserve,
                contextlib.redirect_stderr(errors),
                self.assertRaises(SystemExit) as raised,
            ):
                build_plugin.main(["--profile", "production"])
            self.assertEqual(1, raised.exception.code)
            self.assertIn("production_runtime_enforcement_pending", errors.getvalue())
            revision.assert_not_called()
            reserve.assert_not_called()
            self.assertFalse(output.exists())

    def test_real_archive_writer_embeds_development_profile_and_preserves_build_info(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "contracts/build-profiles.json").write_bytes(
                (build_profiles.ROOT / "contracts/build-profiles.json").read_bytes()
            )
            for relative in (*build_plugin.TOP_LEVEL_FILES, *build_plugin.READ_ONLY_PROBES,
                             *build_plugin.GENERATED_BUILD_OUTPUTS, "bin/gamescope", "bin/steam-launcher"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture\n", encoding="utf-8")
            (root / "plugin.json").write_text('{"flags":["root"]}', encoding="utf-8")
            (root / "package.json").write_text('{"version":"1.2.3"}', encoding="utf-8")
            for launcher in ("gamescope", "steam-launcher"):
                (root / "bin" / launcher).write_bytes(b"#!/usr/bin/python3\npass\n")
            output = root / "out/Re-Gear-1.2.3.zip"
            with (
                patch.object(build_plugin, "ROOT", root),
                patch.object(build_plugin, "OUTPUT", output),
                patch.object(build_plugin, "PACKAGE_VERSION", "1.2.3"),
                patch.object(build_plugin, "source_revision", return_value="a" * 40),
                patch.dict(sys.modules, {"release_coordination": release_coordination}),
                patch.object(release_coordination, "reserve") as reserve,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(0, build_plugin.main())
                reserve.assert_called_once_with("1.2.3")
                with self.assertRaisesRegex(SystemExit, "Refusing to overwrite"):
                    build_plugin.main(["--profile", "development"])
                reserve.assert_called_once_with("1.2.3")
            with zipfile.ZipFile(output) as archive:
                profile = json.loads(archive.read("Re-Gear/build_profile.json"))
                self.assertEqual(build_profiles.package_profile(root=root), profile)
                self.assertEqual({"schema_version": 1, "version": "1.2.3", "revision": "a" * 40},
                                 json.loads(archive.read("Re-Gear/build_info.json")))


if __name__ == "__main__":
    unittest.main()
