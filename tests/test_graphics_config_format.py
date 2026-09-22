from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import graphics_profile_fixtures as fixtures  # noqa: E402
from graphics_profile_fixtures import SAMPLE_CONFIG  # noqa: E402
from regear.domain.graphics_config_format import (  # noqa: E402
    ConfigFormatError,
    DocumentProblem,
    adapter_for,
    parse_document,
    split_address,
    unmanaged_remainder,
)


class ParseAndRenderTests(unittest.TestCase):
    def test_untouched_round_trip_is_byte_identical(self):
        document = parse_document(SAMPLE_CONFIG)
        self.assertEqual(document.render(), SAMPLE_CONFIG)

    def test_mixed_line_endings_survive(self):
        text = "[A]\r\nx=1\n[B]\ry=2"
        self.assertEqual(parse_document(text).render(), text)

    def test_values_are_addressed_by_section(self):
        values = parse_document(SAMPLE_CONFIG).values()
        self.assertEqual(values["ScalabilityGroups/sg.ResolutionQuality"], "100")
        self.assertEqual(values[fixtures.TEXTURE], "3")
        self.assertEqual(values[fixtures.MASTER_VOLUME], "0.8")

    def test_preamble_keys_use_the_empty_section(self):
        document = parse_document("solo=7\n[S]\nsolo=8\n")
        self.assertEqual(document.get("/solo"), "7")
        self.assertEqual(document.get("S/solo"), "8")

    def test_only_the_named_key_changes(self):
        document = parse_document(SAMPLE_CONFIG)
        rendered = document.with_values({fixtures.TEXTURE: "1"}).render()
        self.assertIn("sg.TextureQuality=1\n", rendered)
        before = [line for line in SAMPLE_CONFIG.splitlines() if "TextureQuality" not in line]
        after = [line for line in rendered.splitlines() if "TextureQuality" not in line]
        self.assertEqual(before, after)

    def test_spacing_around_the_separator_is_kept(self):
        document = parse_document("[G]\nShadowQuality = 2\n")
        rendered = document.with_values({"G/ShadowQuality": "3"}).render()
        self.assertEqual(rendered, "[G]\nShadowQuality = 3\n")

    def test_last_duplicate_wins_and_earlier_one_is_untouched(self):
        document = parse_document(SAMPLE_CONFIG)
        rendered = document.with_values({fixtures.SHADOW: "0"}).render()
        occurrences = [
            line for line in rendered.splitlines() if line.startswith("sg.ShadowQuality")
        ]
        self.assertEqual(occurrences, ["sg.ShadowQuality = 2", "sg.ShadowQuality = 0"])
        self.assertEqual(parse_document(rendered).get(fixtures.SHADOW), "0")

    def test_writing_an_absent_key_is_refused(self):
        document = parse_document(SAMPLE_CONFIG)
        with self.assertRaises(KeyError):
            document.with_values({"Graphics/NeverWritten": "1"})

    def test_multiline_value_is_refused(self):
        document = parse_document("[G]\nk=1\n")
        with self.assertRaises(ValueError):
            document.with_values({"G/k": "1\n2"})

    def test_unreadable_line_is_reported_not_guessed(self):
        with self.assertRaises(ConfigFormatError) as caught:
            parse_document("[G]\nthis line has no separator\n")
        self.assertIs(caught.exception.problem, DocumentProblem.UNREADABLE_LINE)

    def test_binary_content_is_refused(self):
        with self.assertRaises(ConfigFormatError) as caught:
            parse_document("[G]\nk=1\n\x00")
        self.assertIs(caught.exception.problem, DocumentProblem.NOT_TEXT)

    def test_comments_and_blank_lines_are_not_entries(self):
        document = parse_document("; note\n\n# other\n[G]\nk=1\n")
        self.assertEqual(list(document.values()), ["G/k"])

    def test_remainder_excludes_managed_keys(self):
        document = parse_document(SAMPLE_CONFIG)
        remainder = unmanaged_remainder(document, (fixtures.TEXTURE,))
        self.assertNotIn(fixtures.TEXTURE, remainder)
        self.assertIn(fixtures.MASTER_VOLUME, remainder)


class AdapterRegistryTests(unittest.TestCase):
    def test_known_suffixes_resolve(self):
        self.assertIsNotNone(adapter_for("graphics.ini"))
        self.assertIsNotNone(adapter_for("GRAPHICS.CFG"))

    def test_unknown_suffix_has_no_adapter(self):
        self.assertIsNone(adapter_for("settings.json"))
        self.assertIsNone(adapter_for("prefs.dat"))

    def test_addresses_are_validated(self):
        self.assertEqual(split_address("Graphics/Shadow"), ("Graphics", "Shadow"))
        # A section name may contain slashes; the split is at the last one,
        # because Unreal writes [/Script/Engine.GameUserSettings].
        self.assertEqual(
            split_address("/Script/Engine.GameUserSettings/sg.TextureQuality"),
            ("/Script/Engine.GameUserSettings", "sg.TextureQuality"),
        )
        with self.assertRaises(ValueError):
            split_address("Graphics")
        with self.assertRaises(ValueError):
            split_address("Graphics/has a space")


if __name__ == "__main__":
    unittest.main()
