from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_decky_update  # noqa: E402


REVISION = "a" * 40


class StageDeckyUpdateTests(unittest.TestCase):
    def package(self, root: Path, *, revision: str = REVISION, version: str = "0.2.0") -> Path:
        path = root / "candidate.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("HandheldDockMode/plugin.json", "{}")
            archive.writestr("HandheldDockMode/package.json", json.dumps({"version": version}))
            archive.writestr("HandheldDockMode/build_info.json", json.dumps({"schema_version": 1, "version": version, "revision": revision}))
        return path

    def test_inspection_and_fixed_filename(self):
        with tempfile.TemporaryDirectory() as value:
            package = self.package(Path(value))
            metadata = stage_decky_update.inspect_package(package)
        self.assertEqual(metadata["revision"], REVISION)
        self.assertEqual(stage_decky_update.staged_filename(metadata), "HDM-update-0.2.0-aaaaaaaaaaaa.zip")
        self.assertRegex(metadata["sha256"], r"^[0-9a-f]{64}$")

    def test_bad_metadata_and_unsafe_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            package = self.package(root, revision="uncommitted")
            with self.assertRaisesRegex(ValueError, "provenance"):
                stage_decky_update.inspect_package(package)
            unsafe = root / "unsafe.zip"
            with zipfile.ZipFile(unsafe, "w") as archive:
                archive.writestr("HandheldDockMode/../outside", "x")
                archive.writestr("HandheldDockMode/package.json", json.dumps({"version": "0.2.0"}))
                archive.writestr("HandheldDockMode/build_info.json", json.dumps({"schema_version": 1, "version": "0.2.0", "revision": REVISION}))
            with self.assertRaisesRegex(ValueError, "metadata"):
                stage_decky_update.inspect_package(unsafe)

    def test_commands_constrain_destination_and_remote_path(self):
        filename = "HDM-update-0.2.0-aaaaaaaaaaaa.zip"
        argv = stage_decky_update.build_hash_argv(host="192.0.2.146", user="deck", port=22, timeout_seconds=15, identity_file=None, filename=filename)
        self.assertEqual(argv[-3:], ["sha256sum", "--", f"/home/deck/{filename}"])
        with self.assertRaises(ValueError):
            stage_decky_update.build_hash_argv(host="bad host", user="deck", port=22, timeout_seconds=15, identity_file=None, filename=filename)
        with self.assertRaises(ValueError):
            stage_decky_update.build_hash_argv(host="192.0.2.146", user="deck", port=22, timeout_seconds=15, identity_file=None, filename="../../plugin.zip")

    def test_staging_requires_remote_digest_match(self):
        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        with tempfile.TemporaryDirectory() as value:
            package = self.package(Path(value))
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            expected_name = "HDM-update-0.2.0-aaaaaaaaaaaa.zip"
            results = [Result(), Result()]
            results[1].stdout = f"{digest}  /home/deck/{expected_name}\n"
            with patch.object(stage_decky_update.subprocess, "run", side_effect=results) as run:
                result = stage_decky_update.stage_package(package=package, host="192.0.2.146")
            self.assertEqual(result["state"], "staged")
            self.assertEqual(run.call_count, 2)

    def test_unexpected_remote_response_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected"):
            stage_decky_update.parse_remote_digest("bad\n", user="deck", filename="HDM-update-0.2.0-aaaaaaaaaaaa.zip")


if __name__ == "__main__":
    unittest.main()
