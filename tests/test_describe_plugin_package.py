"""The archive description a deployment trusts instead of rebuilding.

Every case here is a way a deployment could install the wrong bytes. The script
is read-only and makes no judgement about installability, so these tests check
that it reports what the archive actually asserts and refuses to guess when it
cannot.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "describe_plugin_package", ROOT / "scripts" / "describe_plugin_package.py"
)
assert SPEC and SPEC.loader
describe_plugin_package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(describe_plugin_package)

REVISION = "54dd03ecb7f3015281467e8c0789d4180f9ac31f"


def build(directory: Path, *, record=None, extra_record: bool = False, raw=None) -> Path:
    path = directory / "Re-Gear-0.3.73.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Re-Gear/main.py", "print('x')\n")
        if raw is not None:
            archive.writestr("Re-Gear/build_info.json", raw)
        elif record is not None:
            archive.writestr("Re-Gear/build_info.json", json.dumps(record))
        if extra_record:
            archive.writestr("Re-Gear/nested/build_info.json", json.dumps(record or {}))
    return path


class DescribeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.directory = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)

    def test_reports_the_declared_provenance_and_the_hash_of_the_bytes(self) -> None:
        path = build(
            self.directory,
            record={"schema_version": 1, "version": "0.3.73", "revision": REVISION},
        )
        described = describe_plugin_package.describe(path)
        self.assertEqual(described["revision"], REVISION)
        self.assertEqual(described["version"], "0.3.73")
        self.assertEqual(described["bytes"], path.stat().st_size)
        # The hash must be of the archive on disk, because that is what gets
        # copied to the device -- not of the record inside it.
        self.assertEqual(
            described["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
        )

    def test_an_absent_field_is_reported_empty_rather_than_defaulted(self) -> None:
        # A record with no revision must not compare equal to anything. Reporting
        # "" lets the caller's equality check fail; inventing a value would not.
        path = build(self.directory, record={"version": "0.3.73"})
        described = describe_plugin_package.describe(path)
        self.assertEqual(described["revision"], "")
        self.assertEqual(described["version"], "0.3.73")

    def test_no_build_record_is_refused(self) -> None:
        path = build(self.directory)
        with self.assertRaises(ValueError):
            describe_plugin_package.describe(path)

    def test_two_build_records_are_refused_rather_than_one_chosen(self) -> None:
        # Choosing either would let a second record decide what the archive is.
        path = build(
            self.directory,
            record={"version": "0.3.73", "revision": REVISION},
            extra_record=True,
        )
        with self.assertRaises(ValueError):
            describe_plugin_package.describe(path)

    def test_a_record_that_is_not_json_or_not_an_object_is_refused(self) -> None:
        for raw in ("{not json", '"a string"', "[1, 2]", "null"):
            with self.subTest(raw=raw):
                path = build(self.directory, raw=raw)
                with self.assertRaises(ValueError):
                    describe_plugin_package.describe(path)

    def test_an_implausibly_large_record_is_refused_before_decoding(self) -> None:
        oversized = json.dumps({"revision": REVISION, "pad": "x" * (80 * 1024)})
        path = build(self.directory, raw=oversized)
        with self.assertRaises(ValueError):
            describe_plugin_package.describe(path)

    def test_something_that_is_not_an_archive_is_refused(self) -> None:
        path = self.directory / "Re-Gear-0.3.73.zip"
        path.write_bytes(b"not a zip")
        with self.assertRaises(zipfile.BadZipFile):
            describe_plugin_package.describe(path)


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.directory = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)

    def test_a_description_is_one_json_object_on_stdout(self) -> None:
        path = build(
            self.directory,
            record={"schema_version": 1, "version": "0.3.73", "revision": REVISION},
        )
        import io
        from contextlib import redirect_stdout

        captured = io.StringIO()
        with redirect_stdout(captured):
            code = describe_plugin_package.main([str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(captured.getvalue())["revision"], REVISION)

    def test_a_failure_is_categorical_on_stderr_and_stdout_stays_empty(self) -> None:
        # A caller parses stdout as JSON. An error written there would be read as
        # a description.
        import io
        from contextlib import redirect_stderr, redirect_stdout

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = describe_plugin_package.main([str(self.directory / "absent.zip")])
        self.assertEqual(code, 1)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("Cannot describe", err.getvalue())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
