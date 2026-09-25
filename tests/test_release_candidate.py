import importlib.util
import json
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts import build_profiles


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release_candidate.py"
SPEC = importlib.util.spec_from_file_location("release_candidate", SCRIPT)
assert SPEC and SPEC.loader
release_candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_candidate)


class ReleaseCandidateTests(unittest.TestCase):
    def make_project(self, root: Path, version: str = "1.2.3") -> None:
        (root / "contracts").mkdir()
        (root / "contracts/build-profiles.json").write_bytes(
            (build_profiles.ROOT / "contracts/build-profiles.json").read_bytes()
        )
        (root / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        (root / "pyproject.toml").write_text('[project]\nversion = "' + version + '"\n', encoding="utf-8")

    def make_archive(self, root: Path, *, version: str = "1.2.3", revision: str = "a" * 40, selected: str = "development") -> Path:
        archive = root / f"Re-Gear-{version}.zip"
        with zipfile.ZipFile(archive, "w") as value:
            value.writestr("Re-Gear/package.json", json.dumps({"version": version}))
            value.writestr("Re-Gear/build_info.json", json.dumps({"schema_version": 1, "version": version, "revision": revision}))
            profile = build_profiles.package_profile(selected, root=root)
            profile["bundle_sha256"] = hashlib.sha256(b"fixture").hexdigest()
            value.writestr("Re-Gear/build_profile.json", json.dumps(profile))
            value.writestr("Re-Gear/dist/index.js", b"fixture")
            value.writestr("Re-Gear/" + build_profiles.PROFILE_CONFIG_PATH,
                           build_profiles.backend_config_bytes(selected))
        return archive

    def test_mixed_root_is_not_a_release_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            archive = self.make_archive(root)
            with zipfile.ZipFile(archive, "a") as value:
                value.writestr("HandheldDockMode/plugin.json", "{}")
            with self.assertRaisesRegex(ValueError, "archive_metadata_invalid"):
                release_candidate.prepare_release_candidate(archive, project_root=root)

    def test_candidate_captures_exact_archive_and_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            result = release_candidate.prepare_release_candidate(self.make_archive(root), project_root=root)
        self.assertEqual("1.2.3", result["version"])
        self.assertEqual("a" * 40, result["build"]["source_revision"])
        self.assertEqual("manual_publication_required", result["publication"]["status"])
        self.assertEqual(64, len(result["archive"]["sha256"]))
        self.assertEqual("development", result["build"]["profile"]["profile"])
        self.assertIn("development", release_candidate._notes_template(result))

    def test_production_candidate_retains_approved_feature_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            result = release_candidate.prepare_release_candidate(
                self.make_archive(root, selected="production"), project_root=root)
            self.assertEqual("production", result["build"]["profile"]["profile"])
            self.assertEqual(["egpu_connection", "safe_disconnect"],
                             result["build"]["profile"]["enabled_features"])

    def test_legacy_archive_cannot_be_new_profiled_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            archive = root / "Re-Gear-1.2.3.zip"
            with zipfile.ZipFile(archive, "w") as value:
                value.writestr("Re-Gear/package.json", json.dumps({"version": "1.2.3"}))
                value.writestr("Re-Gear/build_info.json", json.dumps({
                    "schema_version": 1, "version": "1.2.3", "revision": "a" * 40,
                }))
            with self.assertRaisesRegex(ValueError, "archive_metadata_invalid"):
                release_candidate.prepare_release_candidate(archive, project_root=root)

    def test_rejects_relabelled_or_mismatched_profile(self) -> None:
        for field, replacement, reason in (
            ("profile", "production", "archive_profile_inconsistent"),
            ("contract_sha256", "0" * 64, "archive_profile_inconsistent"),
            ("feature_policy", "stable_allowlist", "archive_profile_inconsistent"),
            ("schema_version", True, "archive_profile_inconsistent"),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_project(root)
                profile = build_profiles.package_profile(root=root)
                profile["bundle_sha256"] = hashlib.sha256(b"fixture").hexdigest()
                profile[field] = replacement
                archive = root / "Re-Gear-1.2.3.zip"
                with zipfile.ZipFile(archive, "w") as value:
                    value.writestr("Re-Gear/package.json", json.dumps({"version": "1.2.3"}))
                    value.writestr("Re-Gear/build_info.json", json.dumps({
                        "schema_version": 1, "version": "1.2.3", "revision": "a" * 40,
                    }))
                    value.writestr("Re-Gear/build_profile.json", json.dumps(profile))
                    value.writestr("Re-Gear/dist/index.js", b"fixture")
                    value.writestr("Re-Gear/" + build_profiles.PROFILE_CONFIG_PATH,
                                   build_profiles.backend_config_bytes("development"))
                with self.assertRaisesRegex(ValueError, reason):
                    release_candidate.prepare_release_candidate(archive, project_root=root)

    def test_candidate_rejects_backend_or_bundle_mismatch(self):
        for changed_path, changed_bytes in (
            ("dist/index.js", b"changed"),
            (build_profiles.PROFILE_CONFIG_PATH, build_profiles.backend_config_bytes("production")),
        ):
            with self.subTest(path=changed_path), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_project(root)
                original = self.make_archive(root)
                with zipfile.ZipFile(original) as archive:
                    entries = {name: archive.read(name) for name in archive.namelist()}
                entries["Re-Gear/" + changed_path] = changed_bytes
                with zipfile.ZipFile(original, "w") as archive:
                    for name, content in entries.items():
                        archive.writestr(name, content)
                with self.assertRaisesRegex(ValueError, "archive_profile_inconsistent"):
                    release_candidate.prepare_release_candidate(original, project_root=root)

    def test_rejects_inconsistent_source_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            (root / "pyproject.toml").write_text('[project]\nversion = "1.2.4"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "release.version_inconsistent"):
                release_candidate.prepare_release_candidate(self.make_archive(root), project_root=root)

    def test_rejects_non_semantic_source_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root, "1.2.3-")
            with self.assertRaisesRegex(ValueError, "release.version_invalid"):
                release_candidate.prepare_release_candidate(self.make_archive(root, version="1.2.3-"), project_root=root)

    def test_rejects_archive_metadata_from_another_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            with self.assertRaisesRegex(ValueError, "release.archive_build_inconsistent"):
                release_candidate.prepare_release_candidate(self.make_archive(root, revision="not-a-commit"), project_root=root)
