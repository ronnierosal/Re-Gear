from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_regear_identity_migrator",
    ROOT / "scripts" / "build_regear_identity_migrator.py",
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class IdentityMigratorBundleTests(unittest.TestCase):
    def test_repeated_builds_are_byte_identical_and_self_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            first = builder.build(Path(directory) / "first")
            second = builder.build(Path(directory) / "second")
            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()
            self.assertEqual(
                hashlib.sha256(first_bytes).digest(),
                hashlib.sha256(second_bytes).digest(),
            )
            self.assertTrue(first_bytes.startswith(b"#!/usr/bin/python3\nPK"))

            with zipfile.ZipFile(first) as archive:
                names = archive.namelist()
                expected_package = {
                    path.relative_to(ROOT / "backend").as_posix()
                    for path in (ROOT / "backend" / "regear").rglob("*.py")
                }
                self.assertEqual(names, sorted(names))
                self.assertEqual(
                    set(names),
                    expected_package | {"__main__.py", "migrate_regear_identity.py"},
                )
                self.assertIn("__main__.py", names)
                self.assertIn("migrate_regear_identity.py", names)
                self.assertIn("regear/delivery/identity_migration.py", names)
                self.assertIn("regear/delivery/portable_trial_store.py", names)
                self.assertTrue(
                    all(
                        info.date_time == builder.FIXED_TIMESTAMP
                        for info in archive.infolist()
                    )
                )
                self.assertFalse(
                    any(
                        "__pycache__" in name or name.endswith(".pyc")
                        for name in names
                    )
                )

    def test_archive_starts_cli_without_checkout_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = builder.build(Path(directory) / "regear-migrate-identity")
            result = subprocess.run(
                [sys.executable, str(artifact), "not-a-command"],
                cwd=directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                check=False,
            )
            # Argument parsing happens after the bundled regear imports. A
            # missing dependency would fail with a traceback before this error.
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("invalid choice: 'not-a-command'", result.stderr)


if __name__ == "__main__":
    unittest.main()
