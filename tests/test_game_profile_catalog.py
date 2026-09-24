"""The local profile catalog: strict decoding, provenance and admission."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import game_optimization_fixtures as ofx  # noqa: E402
import game_profile_engine_fixtures as fx  # noqa: E402
from regear.delivery.game_profile_catalog import (  # noqa: E402
    MAX_ENTRY_BYTES,
    CatalogError,
    ProfileSource,
    decode_entry,
    load_catalog,
)
from regear.domain.mode_profiles import ExperienceTarget  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.semantic_profiles import InternalRender, Resolution, ValidationStatus  # noqa: E402

PORTABLE, TV = OperatingMode.PORTABLE, OperatingMode.TV_DOCKED


def validated(source="local", evidence="evidence-1", modes=("portable",)):
    return ofx.entry(
        validation="validated",
        provenance={"source": source, "evidence_id": evidence, "validated_modes": list(modes)},
    )


class DecodeTests(unittest.TestCase):
    def test_fixture_entry_decodes_to_the_engine_fixture_document(self):
        entry = decode_entry(ofx.entry())
        self.assertEqual(entry.document, fx.document())
        self.assertIs(entry.provenance.source, ProfileSource.LOCAL)

    def test_unknown_fields_are_refused_at_every_level(self):
        cases = [
            ofx.entry(config_path="/home/deck/x.ini"),
            ofx.entry(provenance={"source": "local", "command": "rm"}),
        ]
        profiles = ofx.entry()
        profiles["profiles"]["portable"]["balanced"]["key"] = "sg.TextureQuality"
        cases.append(profiles)
        for value in cases:
            with self.assertRaises(CatalogError):
                decode_entry(value)

    def test_identifiers_cannot_carry_paths(self):
        for field_name in ("mapping_id", "tested_game_version"):
            with self.assertRaises(CatalogError):
                decode_entry(ofx.entry(**{field_name: "../../etc/passwd"}))

    def test_invalid_values_are_refused(self):
        bad = [
            ofx.entry(catalog_version=1),  # before the resolution split
            ofx.entry(catalog_version=3),
            ofx.entry(steam_app_id="0"),
            ofx.entry(profile_version="1"),
            ofx.entry(validation="trust-me"),
            ofx.entry(profiles={}),
            ofx.entry(profiles={"unknown": {"balanced": {}}}),
            ofx.entry(profiles={"degraded": {"balanced": {}}}),
            ofx.entry(profiles={"portable": {"balanced": {"graphics": {"textures": "ultra"}}}}),
            ofx.entry(profiles={"portable": {"balanced": {"game_output_resolution": [1280]}}}),
            ofx.entry(profiles={"portable": {"balanced": {"target_fps": 45.5}}}),
            ofx.entry(profiles={"portable": {"balanced": {"upscaling": "auto-ish"}}}),
        ]
        for value in bad:
            with self.subTest(value=str(value)[:80]), self.assertRaises(CatalogError):
                decode_entry(value)


class ResolutionFieldTests(unittest.TestCase):
    def profile(self, **fields):
        value = ofx.entry(profiles={"portable": {"balanced": fields}})
        return decode_entry(value).document.profile(PORTABLE, ExperienceTarget.BALANCED)

    def test_game_output_and_internal_render_are_separate_fields(self):
        profile = self.profile(game_output_resolution=[1920, 1080], internal_render=[1440, 810])
        self.assertEqual(profile.game_output_resolution, Resolution(1920, 1080))
        self.assertEqual(profile.internal_render, Resolution(1440, 810))
        self.assertIs(self.profile(internal_render="dynamic").internal_render, InternalRender.DYNAMIC)
        self.assertIsNone(self.profile().internal_render)

    def test_the_old_single_resolution_field_is_refused(self):
        with self.assertRaisesRegex(CatalogError, "unknown fields: resolution"):
            self.profile(resolution=[1920, 1080])

    def test_bad_internal_values_are_refused(self):
        for bad in ("auto", [1440], 75, [1440.0, 810]):
            with self.subTest(bad), self.assertRaises(CatalogError):
                self.profile(internal_render=bad)


class AdmissionTests(unittest.TestCase):
    def test_non_validated_claims_pass_through_unchanged(self):
        entry = decode_entry(ofx.entry())
        document, reasons = entry.admitted(PORTABLE)
        self.assertIs(document.metadata.validation, ValidationStatus.FIXTURE)
        self.assertEqual(reasons, ())

    def test_local_validated_claim_is_admitted_only_for_covered_modes(self):
        entry = decode_entry(validated())
        self.assertIs(entry.admitted(PORTABLE)[0].metadata.validation, ValidationStatus.VALIDATED)
        document, reasons = entry.admitted(TV)
        self.assertIs(document.metadata.validation, ValidationStatus.UNVALIDATED)
        self.assertIn("does not cover tv_docked", reasons[0])

    def test_community_claims_are_candidates_never_authority(self):
        for source in ("community", "community_reviewed"):
            entry = decode_entry(validated(source=source))
            document, reasons = entry.admitted(PORTABLE)
            self.assertIs(document.metadata.validation, ValidationStatus.UNVALIDATED)
            self.assertTrue(any("candidate" in reason for reason in reasons))

    def test_validation_without_evidence_is_not_admitted(self):
        entry = decode_entry(validated(evidence=""))
        self.assertIs(entry.admitted(PORTABLE)[0].metadata.validation, ValidationStatus.UNVALIDATED)

    def test_regear_reviewed_evidence_is_admitted(self):
        entry = decode_entry(validated(source="regear_reviewed"))
        self.assertIs(entry.admitted(PORTABLE)[0].metadata.validation, ValidationStatus.VALIDATED)


class LoadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name) / "catalog"

    def test_missing_directory_is_an_empty_catalog(self):
        self.assertEqual(load_catalog(self.directory).entries, {})

    def test_bad_entry_is_rejected_and_the_rest_still_load(self):
        ofx.write_catalog(self.directory, ofx.ENTRY)
        (self.directory / f"{ofx.OTHER_APP_ID}.json").write_text("{nope", encoding="utf-8")
        (self.directory / "notes.json").write_text("{}", encoding="utf-8")
        loaded = load_catalog(self.directory)
        self.assertEqual(set(loaded.entries), {ofx.APP_ID})
        self.assertEqual({name for name, _ in loaded.rejected},
                         {f"{ofx.OTHER_APP_ID}.json", "notes.json"})

    def test_file_name_must_match_the_game(self):
        self.directory.mkdir()
        (self.directory / f"{ofx.OTHER_APP_ID}.json").write_text(
            __import__("json").dumps(ofx.ENTRY), encoding="utf-8"
        )
        loaded = load_catalog(self.directory)
        self.assertEqual(loaded.entries, {})
        self.assertIn("disagree", loaded.rejected[0][1])

    def test_oversized_entry_is_rejected(self):
        self.directory.mkdir()
        (self.directory / f"{ofx.APP_ID}.json").write_bytes(b" " * (MAX_ENTRY_BYTES + 1))
        self.assertIn("oversized", load_catalog(self.directory).rejected[0][1])


if __name__ == "__main__":
    unittest.main()
