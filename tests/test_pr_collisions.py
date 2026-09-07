from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_pr_collisions import (  # noqa: E402
    Collision,
    classify,
    contended_files,
    main,
    render,
)


class ClassifyTests(unittest.TestCase):
    def test_build_artifacts_are_called_out(self) -> None:
        risk, reason = classify("dist/index.js")
        self.assertEqual(risk, "build-artifact")
        self.assertIn("silently discard", reason)

    def test_subprocess_boundary_is_safety_critical(self) -> None:
        risk, _ = classify("backend/hdm/adapters/steamos/commands.py")
        self.assertEqual(risk, "safety-critical")

    def test_domain_prefix_matches_nested_modules(self) -> None:
        risk, _ = classify("backend/hdm/domain/transition.py")
        self.assertEqual(risk, "safety-critical")

    def test_unlisted_paths_are_shared(self) -> None:
        risk, _ = classify("backend/hdm/application/whatever.py")
        self.assertEqual(risk, "shared")

    def test_prefix_does_not_match_unrelated_sibling(self) -> None:
        risk, _ = classify("backend/hdm/domain_notes.md")
        self.assertEqual(risk, "shared")


class ContendedFilesTests(unittest.TestCase):
    def test_single_owner_is_not_contention(self) -> None:
        self.assertEqual(contended_files({1: ("a.py",), 2: ("b.py",)}), ())

    def test_reports_shared_path_with_sorted_owners(self) -> None:
        collisions = contended_files({7: ("a.py",), 3: ("a.py",)})
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0].path, "a.py")
        self.assertEqual(collisions[0].pull_requests, (3, 7))
        self.assertEqual(collisions[0].claim_count, 2)

    def test_orders_by_contention_then_path(self) -> None:
        claims = {
            1: ("hot.py", "warm.py", "aaa.py"),
            2: ("hot.py", "warm.py", "aaa.py"),
            3: ("hot.py",),
        }
        paths = [collision.path for collision in contended_files(claims)]
        self.assertEqual(paths, ["hot.py", "aaa.py", "warm.py"])

    def test_accepts_string_keys_from_json(self) -> None:
        collisions = contended_files({"4": ("a.py",), "5": ("a.py",)})
        self.assertEqual(collisions[0].pull_requests, (4, 5))

    def test_empty_input_is_clean(self) -> None:
        self.assertEqual(contended_files({}), ())


class RenderTests(unittest.TestCase):
    def test_clean_result_is_stated_plainly(self) -> None:
        self.assertIn("No file-level contention", render(()))

    def test_report_names_path_owners_and_risk(self) -> None:
        output = render(
            (Collision("dist/index.js", (1, 2), "build-artifact", "because"),)
        )
        self.assertIn("dist/index.js [build-artifact]", output)
        self.assertIn("#1, #2", output)
        self.assertIn("because", output)


class MainTests(unittest.TestCase):
    @staticmethod
    def _run(argv: list[str]) -> int:
        """Run the entry point without leaking its report into test output."""
        with contextlib.redirect_stdout(io.StringIO()):
            return main(argv)

    def _claims_file(self, payload: dict[str, list[str]]) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_clean_repository_succeeds(self) -> None:
        path = self._claims_file({"1": ["a.py"], "2": ["b.py"]})
        self.assertEqual(self._run(["--claims", path, "--strict"]), 0)

    def test_strict_fails_on_contention(self) -> None:
        path = self._claims_file({"1": ["a.py"], "2": ["a.py"]})
        self.assertEqual(self._run(["--claims", path, "--strict"]), 1)

    def test_contention_reported_without_strict_still_succeeds(self) -> None:
        path = self._claims_file({"1": ["a.py"], "2": ["a.py"]})
        self.assertEqual(self._run(["--claims", path]), 0)

    def test_risk_filter_ignores_unselected_classes(self) -> None:
        path = self._claims_file({"1": ["a.py"], "2": ["a.py"]})
        self.assertEqual(
            self._run(["--claims", path, "--strict", "--risk", "safety-critical"]), 0
        )

    def test_risk_filter_fails_on_selected_class(self) -> None:
        path = self._claims_file({"1": ["dist/index.js"], "2": ["dist/index.js"]})
        self.assertEqual(
            self._run(["--claims", path, "--strict", "--risk", "build-artifact"]), 1
        )


if __name__ == "__main__":
    unittest.main()
