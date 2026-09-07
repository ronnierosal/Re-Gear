import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release_candidate.py"
SPEC = importlib.util.spec_from_file_location("release_candidate", SCRIPT)
assert SPEC and SPEC.loader
release_candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_candidate)


class ReleaseCandidateTests(unittest.TestCase):
    def make_project(self, root: Path, version: str = "1.2.3") -> None:
        (root / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        (root / "pyproject.toml").write_text('[project]\nversion = "' + version + '"\n', encoding="utf-8")

    def make_archive(self, root: Path, *, version: str = "1.2.3", revision: str = "a" * 40) -> Path:
        archive = root / f"Re-Gear-{version}.zip"
        with zipfile.ZipFile(archive, "w") as value:
            value.writestr("HandheldDockMode/package.json", json.dumps({"version": version}))
            value.writestr("HandheldDockMode/build_info.json", json.dumps({"schema_version": 1, "version": version, "revision": revision}))
        return archive

    def test_candidate_captures_exact_archive_and_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_project(root)
            result = release_candidate.prepare_release_candidate(self.make_archive(root), project_root=root)
        self.assertEqual("1.2.3", result["version"])
        self.assertEqual("a" * 40, result["build"]["source_revision"])
        self.assertEqual("manual_publication_required", result["publication"]["status"])
        self.assertEqual(64, len(result["archive"]["sha256"]))

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
