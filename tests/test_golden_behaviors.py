"""Regression tests for the golden contract gate itself."""

import copy
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_golden_behaviors as gate


class GoldenGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "evidence.md").write_text("Verified baseline", encoding="utf-8")
        (self.root / "source.py").write_text("", encoding="utf-8")
        self.path = self.root / "manifest.json"
        self.manifest = {
            "schema_version": 1,
            "baseline": {
                "id": "golden-1",
                "source_revision": "a" * 40,
                "artifact_sha256": "b" * 64,
                "evidence": "evidence.md",
            },
            "behaviors": [
                {
                    "id": "preserve",
                    "contract": "Preserve working behavior",
                    "test_ids": ["test_golden_fixture.Example.test_ok"],
                    "source_paths": ["source.py"],
                    "hardware_cases": [],
                }
            ],
        }

    def load(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")
        return gate.load_manifest(self.path, self.root)

    def fixture(self, outcome):
        module = types.ModuleType("test_golden_fixture")

        def test_ok(test):
            if outcome == "skip":
                test.skipTest("missing prerequisites")
            elif outcome == "fail":
                test.fail("regression")
            elif outcome == "error":
                raise RuntimeError("regression")

        module.Example = type(
            "Example",
            (unittest.TestCase,),
            {"__module__": module.__name__, "test_ok": test_ok},
        )
        return patch.dict(sys.modules, {module.__name__: module})

    def test_repository_golden_contracts(self):
        manifest = gate.load_manifest(gate.ROOT / "contracts/golden-behaviors.json")
        test_path = str(gate.ROOT / "tests")
        with patch.object(sys, "path", [test_path, *sys.path]):
            suite = gate.load_tests(manifest)
            output = io.StringIO()
            self.assertTrue(gate.run_tests(suite, output), output.getvalue())

    def test_valid_manifest_and_passing_test(self):
        with self.fixture("pass"):
            self.assertTrue(gate.run_tests(gate.load_tests(self.load()), io.StringIO()))

    def test_failure_error_and_skip_fail_gate(self):
        for outcome in ("fail", "error", "skip"):
            with self.subTest(outcome=outcome), self.fixture(outcome):
                self.assertFalse(
                    gate.run_tests(gate.load_tests(self.load()), io.StringIO())
                )

    def test_expected_failure_fails_gate(self):
        class ExpectedFailure(unittest.TestCase):
            @unittest.expectedFailure
            def test_regression(self):
                self.fail("Known regression must block golden clearance")

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ExpectedFailure)
        self.assertFalse(gate.run_tests(suite, io.StringIO()))

    def test_empty_suite_fails(self):
        self.assertFalse(gate.run_tests(unittest.TestSuite(), io.StringIO()))

    def test_missing_test_fails_validation(self):
        with self.fixture("pass"):
            self.manifest["behaviors"][0]["test_ids"] = [
                "test_golden_fixture.Example.test_missing"
            ]
            with self.assertRaises(gate.ContractError):
                gate.load_tests(self.load())

    def test_malformed_and_empty_manifests(self):
        originals = copy.deepcopy(self.manifest)
        variants = [
            None,
            {},
            dict(originals, schema_version=True),
            dict(originals, behaviors=[]),
            dict(originals, unexpected="field"),
        ]
        for value in variants:
            with self.subTest(value=value):
                self.manifest = value
                with self.assertRaises(gate.ContractError):
                    self.load()
        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaises(gate.ContractError):
            gate.load_manifest(self.path, self.root)

    def test_duplicate_json_fields_rejected(self):
        self.path.write_text(
            '{"schema_version": 1, "schema_version": 1}', encoding="utf-8"
        )
        with self.assertRaises(gate.ContractError):
            gate.load_manifest(self.path, self.root)

    def test_unsafe_paths_and_missing_evidence(self):
        for value in (
            "../escape",
            "/absolute",
            "C:/absolute",
            "folder\\file",
            "a//b",
            "./file",
            "missing.md",
            "*.md",
            "a\nb",
            None,
        ):
            with self.subTest(value=value):
                self.manifest["baseline"]["evidence"] = value
                with self.assertRaises(gate.ContractError):
                    self.load()

    def test_invalid_contracts(self):
        original = copy.deepcopy(self.manifest["behaviors"][0])
        for key, value in (
            ("id", "Bad ID"),
            ("contract", ""),
            ("test_ids", []),
            ("test_ids", ["test_golden_fixture.Example"]),
            ("test_ids", ["os.system"]),
            (
                "test_ids",
                [
                    "tests.test_golden_behaviors.GoldenGateTests.test_repository_golden_contracts"
                ],
            ),
            ("source_paths", ["../*.py"]),
            ("source_paths", ["missing/*.py"]),
            ("hardware_cases", "none"),
        ):
            with self.subTest(key=key, value=value):
                self.manifest["behaviors"] = [dict(original, **{key: value})]
                with self.assertRaises(gate.ContractError):
                    self.load()
        self.manifest["behaviors"] = [original, original]
        with self.assertRaises(gate.ContractError):
            self.load()

    def test_shared_tests_run_once(self):
        second = copy.deepcopy(self.manifest["behaviors"][0])
        second["id"] = "another"
        self.manifest["behaviors"].append(second)
        with self.fixture("pass"):
            self.assertEqual(gate.load_tests(self.load()).countTestCases(), 1)

    def test_base_report_does_not_filter_suite(self):
        with (
            self.fixture("pass"),
            patch.object(gate, "load_manifest", return_value=self.manifest),
            patch.object(gate, "affected", return_value=[]),
            patch.object(gate, "run_tests", return_value=True) as run,
            patch("sys.stdout", new=io.StringIO()),
        ):
            self.assertEqual(gate.main(["--base", "HEAD"]), 0)
            self.assertEqual(run.call_args.args[0].countTestCases(), 1)

    def test_validate_only_resolves_tests_without_execution(self):
        with (
            self.fixture("fail"),
            patch.object(gate, "load_manifest", return_value=self.manifest),
            patch.object(gate, "run_tests") as run,
            patch("sys.stdout", new=io.StringIO()),
        ):
            self.assertEqual(gate.main(["--validate-only"]), 0)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
