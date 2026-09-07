from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_validation_artifact import main, verify_validation_artifact  # noqa: E402


REVISION = "a" * 40
ARCHIVE_NAME = "HandheldDockMode-0.2.0.zip"


class ValidationArtifactTests(unittest.TestCase):
    def test_regear_archive_preserves_legacy_install_layout(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            archive = self._artifact(root)
            renamed = archive.rename(root / "Re-Gear-0.2.0.zip")
            digest = hashlib.sha256(renamed.read_bytes()).hexdigest()
            (root / "SHA256SUMS.txt").write_text(f"{digest}  {renamed.name}\n")
            self.assertEqual(verify_validation_artifact(root)["state"], "verified")
            (root / ARCHIVE_NAME).write_bytes(renamed.read_bytes())
            self.assertEqual(verify_validation_artifact(root)["reason"], "artifact.archive_ambiguous")

    def _artifact(
        self,
        directory: Path,
        *,
        revision: str = REVISION,
        build_revision: str | None = None,
        version: str = "0.2.0",
    ) -> Path:
        archive = directory / ARCHIVE_NAME
        build_revision = build_revision or revision
        with zipfile.ZipFile(archive, "w") as value:
            value.writestr("HandheldDockMode/plugin.json", "{}")
            value.writestr(
                "HandheldDockMode/package.json", json.dumps({"version": version})
            )
            value.writestr(
                "HandheldDockMode/build_info.json",
                json.dumps(
                    {
                        "schema_version": 1,
                        "version": version,
                        "revision": build_revision,
                    }
                ),
            )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (directory / "source-revision.txt").write_text(f"{revision}\n", encoding="utf-8")
        (directory / "SHA256SUMS.txt").write_text(
            f"{digest}  out/{ARCHIVE_NAME}\n", encoding="utf-8"
        )
        return archive

    def test_exact_checksum_revision_and_embedded_build_are_verified(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            self._artifact(root)
            self.assertEqual(
                verify_validation_artifact(root),
                {"state": "verified", "version": "0.2.0", "revision": "a" * 12},
            )

    def test_checksum_and_metadata_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            archive = self._artifact(root)
            archive.write_bytes(b"not a zip")
            self.assertEqual(
                verify_validation_artifact(root)["reason"],
                "artifact.checksum_mismatch",
            )

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            self._artifact(root, build_revision="b" * 40)
            self.assertEqual(
                verify_validation_artifact(root)["reason"],
                "artifact.package_build_inconsistent",
            )

    def test_expected_public_revision_prefix_is_optional_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            self._artifact(root)
            self.assertEqual(
                verify_validation_artifact(
                    root, expected_revision_prefix="a" * 12
                )["state"],
                "verified",
            )
            self.assertEqual(
                verify_validation_artifact(
                    root, expected_revision_prefix="b" * 12
                )["reason"],
                "artifact.expected_revision_mismatch",
            )
            self.assertEqual(
                verify_validation_artifact(
                    root, expected_revision_prefix="not-a-revision"
                )["reason"],
                "artifact.expected_revision_invalid",
            )

    def test_missing_ambiguous_or_unsafe_input_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            self.assertEqual(
                verify_validation_artifact(root)["reason"],
                "artifact.archive_ambiguous",
            )
            self._artifact(root)
            (root / "HandheldDockMode-0.2.1.zip").write_bytes(b"extra")
            self.assertEqual(
                verify_validation_artifact(root)["reason"],
                "artifact.archive_ambiguous",
            )
        self.assertEqual(
            verify_validation_artifact(Path("relative"))["reason"],
            "artifact.directory_invalid",
        )

    def test_command_fails_when_the_artifact_is_not_verified(self):
        with patch.object(sys, "argv", ["verify_validation_artifact.py", "relative"]):
            self.assertEqual(main(), 1)

    def test_command_accepts_a_matching_expected_public_revision_prefix(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            self._artifact(root)
            with patch.object(
                sys,
                "argv",
                [
                    "verify_validation_artifact.py",
                    str(root),
                    "--expected-revision-prefix",
                    "a" * 12,
                ],
            ):
                self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
