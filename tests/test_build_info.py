from __future__ import annotations

import json
import sys
import tempfile
import unittest
from subprocess import CompletedProcess
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from hdm.delivery.build_info import load_public_build_info  # noqa: E402
from scripts import build_plugin  # noqa: E402
from scripts.build_plugin import build_info_bytes  # noqa: E402


class BuildInfoTests(unittest.TestCase):
    def test_clean_revision_is_shortened_only_for_public_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revision = "a" * 40
            (root / "build_info.json").write_bytes(build_info_bytes(revision))

            self.assertEqual(
                load_public_build_info(root),
                {"schema_version": 1, "version": build_plugin.PACKAGE_VERSION, "revision": "a" * 12},
            )

    def test_uncommitted_and_invalid_metadata_never_claim_a_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build_info.json").write_bytes(build_info_bytes("uncommitted"))
            self.assertEqual(load_public_build_info(root)["revision"], "uncommitted")

            (root / "build_info.json").write_text(
                json.dumps({"schema_version": 1, "version": "0.2.0", "revision": "not-a-commit"}),
                encoding="utf-8",
            )
            self.assertEqual(load_public_build_info(root)["revision"], "unavailable")

    def test_archive_metadata_refuses_invalid_revisions(self):
        with self.assertRaisesRegex(ValueError, "revision"):
            build_info_bytes("private-workstation-data")

    def test_untracked_source_never_claims_a_clean_archive_revision(self):
        with patch.object(
            build_plugin,
            "_git_status",
            return_value=CompletedProcess(
                ("git", "status"), 0, stdout="?? backend/hdm/untracked.py\n"
            ),
        ) as status:
            self.assertEqual(build_plugin.source_revision(), "uncommitted")
        status.assert_called_once_with(
            "status", "--porcelain=v1", "--untracked-files=all"
        )

    def test_clean_porcelain_status_requires_a_valid_head(self):
        with patch.object(
            build_plugin,
            "_git_status",
            side_effect=(
                CompletedProcess(("git", "status"), 0, stdout=""),
                CompletedProcess(("git", "rev-parse", "HEAD"), 0, stdout="a" * 40),
            ),
        ):
            self.assertEqual(build_plugin.source_revision(), "a" * 40)

    def test_only_expected_generated_ui_outputs_are_accepted_after_build(self):
        with patch.object(
            build_plugin,
            "_git_status",
            side_effect=(
                CompletedProcess(
                    ("git", "status"),
                    0,
                    stdout=" M dist/index.js\n M dist/index.js.map\n",
                ),
                CompletedProcess(("git", "rev-parse", "HEAD"), 0, stdout="a" * 40),
            ),
        ):
            self.assertEqual(build_plugin.source_revision(), "a" * 40)

    def test_any_other_dirty_path_still_refuses_a_clean_revision(self):
        for status in (
            " M src/index.tsx\n",
            "M  dist/index.js\n",
            "?? dist/untracked.js\n",
            "R  dist/index.js -> dist/renamed.js\n",
        ):
            with self.subTest(status=status), patch.object(
                build_plugin,
                "_git_status",
                return_value=CompletedProcess(("git", "status"), 0, stdout=status),
            ):
                self.assertEqual(build_plugin.source_revision(), "uncommitted")


if __name__ == "__main__":
    unittest.main()
