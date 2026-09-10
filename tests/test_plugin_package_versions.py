from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_plugin_package import (  # noqa: E402
    VERSION_SITES,
    VERSION_SOURCE,
    _main_version,
    declared_versions,
    version_failures,
)


AGREED = {relative: "0.2.0" for relative in VERSION_SITES}


LEGACY_MAIN = '''
class Plugin:
    def _support_versions(self):
        return {"hdm": "0.3.72", "decky": "3.2.8"}
'''

CURRENT_MAIN = '''
class Plugin:
    def _support_versions(self):
        return {"regear": "0.3.73", "decky": "3.2.8"}
'''


class SupportVersionKeyTests(unittest.TestCase):
    """The key naming this project's own version moved with the rename.

    The checker reads a `main.py`, and a `main.py` from before the rename
    still says `"hdm"`. Dropping that read would make this check silently
    unable to answer for an older build.
    """

    def test_the_current_key_is_read(self):
        self.assertEqual(_main_version(CURRENT_MAIN), "0.3.73")

    def test_a_pre_rename_main_is_still_readable(self):
        self.assertEqual(_main_version(LEGACY_MAIN), "0.3.72")

    def test_an_unrelated_mapping_still_cannot_answer(self):
        """Widening the key set must not widen the scope it is read from."""
        source = '''
class Plugin:
    def _unrelated(self):
        return {"regear": "9.9.9", "hdm": "9.9.9"}
'''
        self.assertIsNone(_main_version(source))


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
            any("backend/regear/delivery/build_info.py" in failure for failure in failures)
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

    def test_an_absent_file_is_left_to_required_files(self):
        """`REQUIRED_FILES` owns existence; this check owns agreement.

        Narrowed roots (see `test_launcher_packaging`) exercise one rule at a
        time, so reporting absence here would fire on every such root.
        """
        versions = dict(AGREED)
        del versions["pyproject.toml"]
        self.assertEqual(version_failures(versions), [])

    def test_a_present_but_disagreeing_file_still_fails_when_others_are_absent(self):
        versions = {"package.json": "0.3.51", "main.py": "0.2.0"}
        failures = version_failures(versions)
        self.assertEqual(len(failures), 1)
        self.assertIn("main.py declares version '0.2.0'", failures[0])

    def test_no_source_of_truth_means_nothing_to_compare(self):
        self.assertEqual(version_failures({"main.py": "0.3.51"}), [])


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
