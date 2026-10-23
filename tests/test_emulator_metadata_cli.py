from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from test_emulator_metadata_inventory import SECRET, fixture_bytes, fixture_rows  # noqa: E402
from regear.adapters import emulator_metadata_capture as capture  # noqa: E402
from regear.delivery import emulator_metadata_cli as cli  # noqa: E402
from regear.domain.emulator_metadata_inventory import MetadataError, Reason  # noqa: E402


class CliTests(unittest.TestCase):
    def run_cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_private(self, output, *values):
        for value in (SECRET, "ULUS12345", "ULUS12345DATA00", "9000000001", "1234350", *values):
            self.assertNotIn(value, output)

    def test_help_opens_nothing_and_has_no_private_default_paths(self):
        stdout = io.StringIO()
        with patch.object(cli, "read_metadata_file", side_effect=AssertionError("help opened file")), \
             patch.object(cli, "capture_metadata", side_effect=AssertionError("help captured")), \
             patch("builtins.open", side_effect=AssertionError("help open")), redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--capture", stdout.getvalue())
        self.assert_private(stdout.getvalue())

    def test_argument_errors_never_echo_rejected_paths_or_values(self):
        for args in ([], ["--unknown", "/home/" + SECRET], ["--fixture"],
                     ["--capture", "--metadata", SECRET + "=/home/private"],
                     ["--capture", "--fixture", SECRET]):
            code, stdout, stderr = self.run_cli(args)
            self.assertEqual(code, 2)
            self.assert_private(stdout + stderr, "/home/private")
            self.assertEqual(stderr, "")
            self.assertEqual(json.loads(stdout)["status"], "invalid")

    def test_fixture_cli_preserves_redaction_and_deferred_exit(self):
        with patch.object(cli, "read_metadata_file", return_value=fixture_bytes()):
            code, stdout, stderr = self.run_cli(["--fixture", "/home/" + SECRET + "/emulator-metadata-fixture.json",
                                               "--root", "/home/" + SECRET])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["versions"], ["2.4.0", "1.19.3"])
        self.assertEqual(json.loads(stdout)["cloud_coverage"], "unknown")
        self.assert_private(stdout + stderr)

    def test_parser_or_safe_open_error_is_categorical(self):
        for reason in (Reason.READ_UNAVAILABLE, Reason.INPUT_CHANGED, Reason.UNSUPPORTED_SAFE_OPEN):
            with patch.object(cli, "read_metadata_file", side_effect=MetadataError(reason)):
                code, stdout, stderr = self.run_cli(["--fixture", "/home/" + SECRET, "--root", "/private"])
            self.assertEqual(code, 1)
            self.assert_private(stdout + stderr, "/private")
            self.assertEqual(json.loads(stdout)["reasons"], [reason.value])

    def test_fixture_mode_cannot_request_capture_or_save_evidence(self):
        with patch.object(cli, "read_metadata_file", side_effect=AssertionError("mixed mode")):
            code, stdout, stderr = self.run_cli(["--fixture", SECRET, "--save-root", SECRET])
        self.assertEqual(code, 2)
        self.assert_private(stdout + stderr)

    def test_malformed_private_fixture_reports_no_content_or_exception(self):
        rows = fixture_rows()
        rows[1]["payload"][SECRET] = "private-body"
        with patch.object(cli, "read_metadata_file", return_value=fixture_bytes(rows)):
            code, stdout, stderr = self.run_cli(["--fixture", SECRET, "--root", SECRET])
        self.assertEqual(code, 2)
        self.assert_private(stdout + stderr, "private-body")

    def test_end_to_end_explicit_capture_with_synthetic_metadata_only(self):
        with tempfile.TemporaryDirectory(prefix=SECRET) as temporary:
            root = Path(temporary)
            metadata = root / "emulator-metadata.json"
            metadata.write_bytes(json.dumps(fixture_rows()[1]["payload"]).encode())
            code, stdout, stderr = self.run_cli(["--capture", "--root", str(root),
                                               "--metadata", "emulator=" + str(metadata)])
        self.assertEqual(code, 1)
        self.assert_private(stdout + stderr, str(root), str(metadata))
        if capture.safe_open_supported():
            self.assertEqual(json.loads(stdout)["known_records"], 1)
        else:
            self.assertEqual(json.loads(stdout)["reasons"], ["unsupported_safe_open"])

    def test_end_to_end_fixture_file_has_no_public_private_identifiers(self):
        with tempfile.TemporaryDirectory(prefix=SECRET) as temporary:
            path = Path(temporary) / "emulator-metadata-fixture.json"
            path.write_bytes(fixture_bytes())
            code, stdout, stderr = self.run_cli(["--fixture", str(path), "--root", temporary])
        self.assertEqual(code, 1)
        self.assert_private(stdout + stderr, temporary)
        self.assertEqual(json.loads(stdout)["cloud_coverage"], "unknown")


if __name__ == "__main__":
    unittest.main()
