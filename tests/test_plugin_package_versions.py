from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_plugin_package import (  # noqa: E402
    VERSION_SITES,
    VERSION_SOURCE,
    declared_versions,
    version_failures,
)


AGREED = {relative: "0.2.0" for relative in VERSION_SITES}


class VersionFailureTests(unittest.TestCase):
    def test_agreeing_declarations_pass(self):
        self.assertEqual(version_failures(dict(AGREED)), [])

    def test_a_release_bump_that_misses_a_site_is_reported(self):
        """The 0.3.55 candidate bumped only the two packaging files."""
        versions = dict(AGREED)
        versions["package.json"] = "0.3.55"
        versions["pyproject.toml"] = "0.3.55"
        failures = version_failures(versions)
        self.assertEqual(len(failures), 2)
        self.assertTrue(any("main.py" in failure for failure in failures))
        self.assertTrue(
            any("backend/hdm/delivery/build_info.py" in failure for failure in failures)
        )
        for failure in failures:
            self.assertIn("0.3.55", failure)

    def test_the_source_of_truth_is_package_json(self):
        versions = dict(AGREED)
        versions["main.py"] = "9.9.9"
        failure = version_failures(versions)[0]
        self.assertIn("main.py declares version '9.9.9'", failure)
        self.assertIn(f"{VERSION_SOURCE} declares '0.2.0'", failure)

    def test_an_unreadable_declaration_fails_closed(self):
        """Moving a literal must break the check, never disable it."""
        versions = dict(AGREED)
        versions["main.py"] = None
        self.assertEqual(
            version_failures(versions),
            ["could not read the declared version in main.py"],
        )

    def test_a_missing_declaration_fails_closed(self):
        versions = dict(AGREED)
        del versions["pyproject.toml"]
        self.assertEqual(
            version_failures(versions),
            ["missing version declaration in pyproject.toml"],
        )


class DeclaredVersionTests(unittest.TestCase):
    def test_every_reader_finds_the_literal_in_the_real_tree(self):
        sources = {
            relative: (ROOT / relative).read_text(encoding="utf-8")
            for relative in VERSION_SITES
        }
        versions = declared_versions(sources)
        self.assertEqual(sorted(versions), sorted(VERSION_SITES))
        for relative, version in versions.items():
            with self.subTest(relative=relative):
                self.assertIsNotNone(version, f"no version literal found in {relative}")

    def test_the_checked_in_tree_agrees(self):
        sources = {
            relative: (ROOT / relative).read_text(encoding="utf-8")
            for relative in VERSION_SITES
        }
        self.assertEqual(version_failures(declared_versions(sources)), [])

    def test_malformed_sources_are_reported_rather_than_raised(self):
        versions = declared_versions(
            {relative: "@ not parseable @" for relative in VERSION_SITES}
        )
        self.assertEqual(set(versions.values()), {None})


if __name__ == "__main__":
    unittest.main()
