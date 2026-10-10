from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.adapters.emulator_save_fixture import read_emulator_save_fixture


def metadata():
    return {
        "binding": {
            "kind": "psp_game_directory", "unit_id": "ULUS00001",
            "game_ids": ["ULUS00001"], "emulator": "ppsspp",
            "emulator_version": "fixture-v1", "native_format": "psp-savedata",
            "format_version": "fixture-format", "data_kind": "ordinary_save",
            "game_ids_confirmed": True, "game_id_provenance": "fixture-game-metadata",
        },
        "launch": {
            "source": "emudeck-shortcut", "provenance": "fixture",
            "shortcut_app_id": "9000000001", "emulator_app_id": None,
            "carrier_app_id": "1118310",
        },
        "paths": {
            "configured": "/fixture/PSP/SAVEDATA/ULUS00001",
            "canonical_target": None, "symlink_targets": [],
            "resolved": None, "confined": None,
        },
        "cloud_rule": {
            "source": None, "capture_sha256": None, "platform": None,
            "root": None, "pattern": None, "recursive": None,
            "quota_bytes": None, "matches_save_unit": None,
        },
        "complete": True,
    }


class EmulatorSaveFixtureTests(unittest.TestCase):
    def test_complete_psp_directory_keeps_all_related_members_and_slots(self):
        files = {"PARAM.SFO": b"parameters", "ICON0.PNG": b"icon", "slot1/DATA.BIN": b"a", "slot2/DATA.BIN": b"b"}
        result = read_emulator_save_fixture(metadata(), files)
        self.assertEqual(tuple(member.name for member in result.manifest.members), tuple(sorted(files)))
        self.assertTrue(result.manifest.complete)
        self.assertEqual(result.binding.game_ids, ("ULUS00001",))
        self.assertIn("cloud_rule_unverified", result.unknowns)

    def test_whole_ps2_card_and_native_carrier_rename_keep_identical_bytes(self):
        record = metadata()
        record["binding"].update(
            kind="ps2_whole_card", unit_id="shared-card",
            game_ids=["SLUS-00001", "SLUS-00002"], emulator="pcsx2", native_format="ps2-card")
        record["paths"]["configured"] = "/fixture/native/card.ps2"
        data = b"synthetic card bytes with multiple games"
        native = read_emulator_save_fixture(record, {"card": data})
        renamed = copy.deepcopy(record)
        renamed["paths"]["configured"] = "/fixture/carrier/card.srm"
        carrier = read_emulator_save_fixture(renamed, {"card": data})
        self.assertEqual(native.manifest, carrier.manifest)
        self.assertEqual(native.manifest.members[0].sha256, hashlib.sha256(data).hexdigest())
        self.assertIn("cloud_rule_unverified", carrier.unknowns)

    def test_supplied_symlink_targets_are_never_resolved(self):
        record = metadata()
        record["paths"]["symlink_targets"] = ["/fixture/escaping-target"]
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")):
            result = read_emulator_save_fixture(record, {"DATA": b"fixture"})
        self.assertIsNone(result.paths.canonical_target)
        self.assertIn("path_target_unverified", result.unknowns)
        record["paths"]["confined"] = False
        self.assertIn("path_target_unverified", read_emulator_save_fixture(record, {"DATA": b"x"}).unknowns)

    def test_input_mutations_cannot_change_inventory(self):
        record = metadata()
        files = {"DATA": b"x"}
        result = read_emulator_save_fixture(record, files)
        record["binding"]["game_ids"].append("OTHER")
        record["paths"]["symlink_targets"].append("/other")
        files.clear()
        self.assertEqual(result.binding.game_ids, ("ULUS00001",))
        self.assertEqual(result.paths.symlink_targets, ())
        self.assertEqual(len(result.manifest.members), 1)

    def test_partial_tree_stays_partial_and_unknown(self):
        record = metadata()
        record["complete"] = False
        result = read_emulator_save_fixture(record, {"PARAM.SFO": b"only metadata"})
        self.assertFalse(result.manifest.complete)
        self.assertIn("save_unit_incomplete", result.unknowns)

    def test_strict_fields_types_and_bounds(self):
        for change in (
            lambda d: d.update(writer="forbidden"),
            lambda d: d["launch"].update(unknown="field"),
            lambda d: d["paths"].update(symlink_targets=["/x"] * 17),
            lambda d: d["binding"].update(game_ids=["ULUS00001"] * 65),
            lambda d: d.update(complete="true"),
            lambda d: d["cloud_rule"].update(quota_bytes=True),
            lambda d: d["paths"].update(resolved=1),
            lambda d: d["binding"].update(emulator_version="x" * 1025),
            lambda d: d["binding"].update(game_ids_confirmed=1),
        ):
            record = metadata()
            change(record)
            with self.subTest(record=record), self.assertRaises(ValueError):
                read_emulator_save_fixture(record, {"DATA": b"x"})

    def test_arbitrary_mapping_hooks_are_not_executed(self):
        class Hostile(dict):
            def __iter__(self):
                raise AssertionError("fixture mapping executed")
        with self.assertRaises(ValueError):
            read_emulator_save_fixture(Hostile(metadata()), {"DATA": b"x"})

    def test_cloud_declaration_retains_provenance_without_live_coverage(self):
        record = metadata()
        record["cloud_rule"].update(
            source="synthetic-config", capture_sha256="a" * 64,
            platform="linux", root="/fixture/carrier", pattern="*.srm",
            recursive=True, quota_bytes=1024, matches_save_unit=True)
        result = read_emulator_save_fixture(record, {"DATA": b"x"})
        self.assertEqual(result.cloud_rule.source, "synthetic-config")
        self.assertEqual(result.cloud_rule.pattern, "*.srm")
        self.assertEqual(result.origin, "fixture")
        self.assertIsNone(result.launch.emulator_app_id)

    def test_unknown_versions_app_ids_and_launch_facts_are_not_inferred(self):
        record = metadata()
        record["binding"].update(emulator_version=None, format_version=None)
        record["launch"].update(source=None, provenance=None, carrier_app_id=None)
        result = read_emulator_save_fixture(record, {"DATA": b"x"})
        self.assertIn("version_unknown", result.unknowns)
        self.assertIn("launch_unknown", result.unknowns)
        self.assertIn("carrier_app_id_unknown", result.unknowns)
        self.assertIsNone(result.launch.carrier_app_id)

    def test_rom_labels_and_directory_suffixes_are_not_inferred_as_game_ids(self):
        for label in ("Renamed-ROM", "ULUS00001SAVE00"):
            record = metadata()
            record["binding"].update(unit_id=label, game_ids=[label])
            with self.subTest(label=label), self.assertRaises(ValueError):
                read_emulator_save_fixture(record, {"DATA": b"x"})
        record = metadata()
        record["binding"].update(game_ids_confirmed=None, game_id_provenance=None)
        result = read_emulator_save_fixture(record, {"DATA": b"x"})
        self.assertIn("game_identity_unconfirmed", result.unknowns)
        self.assertIsNone(result.binding.game_ids_confirmed)


if __name__ == "__main__":
    unittest.main()
