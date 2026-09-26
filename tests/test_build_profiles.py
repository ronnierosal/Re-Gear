"""Exercise profile admission and archive identity without reserving releases."""

import contextlib
import io
import hashlib
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
        profile["bundle_sha256"] = "a" * 64
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

    def test_production_has_only_approved_features(self):
        self.assertEqual(["egpu_connection", "safe_disconnect", "brightness", "volume"],
                         build_profiles.package_profile("production")["enabled_features"])

    def test_frontend_profile_rejects_mismatch_and_changed_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "contracts/build-profiles.json").write_bytes(
                (build_profiles.ROOT / "contracts/build-profiles.json").read_bytes())
            (root / "dist").mkdir()
            bundle = root / "dist/index.js"
            bundle.write_bytes(b"production bundle")
            stamp = build_profiles.package_profile("production", root=root)
            stamp["bundle_sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
            (root / "dist/build_profile.json").write_text(json.dumps(stamp))
            self.assertEqual(stamp, build_profiles.frontend_profile("production", root=root))
            with self.assertRaisesRegex(ValueError, "frontend_profile_mismatch"):
                build_profiles.frontend_profile("development", root=root)
            bundle.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "frontend_profile_mismatch"):
                build_profiles.frontend_profile("production", root=root)

    def test_real_archive_writer_embeds_each_profile_and_preserves_build_info(self):
        for selected in build_profiles.PROFILE_NAMES:
            with self.subTest(profile=selected):
                self.check_archive_profile(selected)

    def check_archive_profile(self, selected):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "contracts").mkdir()
            (root / "contracts/build-profiles.json").write_bytes(
                (build_profiles.ROOT / "contracts/build-profiles.json").read_bytes()
            )
            for relative in (*build_plugin.TOP_LEVEL_FILES, *build_plugin.READ_ONLY_PROBES,
                             *build_plugin.GENERATED_BUILD_OUTPUTS, "bin/gamescope", "bin/steam-launcher", build_profiles.PROFILE_CONFIG_PATH):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture\n", encoding="utf-8")
            (root / "plugin.json").write_text('{"flags":["root"]}', encoding="utf-8")
            (root / "package.json").write_text('{"version":"1.2.3"}', encoding="utf-8")
            for launcher in ("gamescope", "steam-launcher"):
                (root / "bin" / launcher).write_bytes(b"#!/usr/bin/python3\npass\n")
            stamp = build_profiles.package_profile(selected, root=root)
            stamp["bundle_sha256"] = hashlib.sha256((root / "dist/index.js").read_bytes()).hexdigest()
            (root / "dist/build_profile.json").write_text(json.dumps(stamp))
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
                other = "production" if selected == "development" else "development"
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    build_plugin.main(["--profile", other])
                reserve.assert_not_called()
                self.assertFalse(output.parent.exists())
                self.assertEqual(0, build_plugin.main(["--profile", selected]))
                reserve.assert_called_once_with("1.2.3")
                with self.assertRaisesRegex(SystemExit, "Refusing to overwrite"):
                    build_plugin.main(["--profile", selected])
                reserve.assert_called_once_with("1.2.3")
            with zipfile.ZipFile(output) as archive:
                profile = json.loads(archive.read("Re-Gear/build_profile.json"))
                self.assertEqual(stamp, profile)
                self.assertEqual(build_profiles.backend_config_bytes(selected),
                                 archive.read("Re-Gear/" + build_profiles.PROFILE_CONFIG_PATH))
                self.assertEqual({"schema_version": 1, "version": "1.2.3", "revision": "a" * 40},
                                 json.loads(archive.read("Re-Gear/build_info.json")))


if __name__ == "__main__":
    unittest.main()
