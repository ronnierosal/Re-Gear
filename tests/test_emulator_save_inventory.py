from __future__ import annotations

import hashlib
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.domain.emulator_save_inventory import (
    MAX_FILE_BYTES, MAX_FILES, MAX_UNIT_BYTES, CloudRuleEvidence,
    EmulatorSaveInventory, LaunchIdentity, SaveBinding, SaveDataKind,
    SaveManifest, SaveMember, SavePathEvidence, SaveUnitKind, build_save_manifest,
)


def binding(kind=SaveUnitKind.PSP_GAME_DIRECTORY, **changes):
    values = dict(
        kind=kind, unit_id="ULUS00001", game_ids=("ULUS00001",),
        emulator="ppsspp", emulator_version="fixture-v1",
        native_format="psp-savedata", format_version="fixture-format",
    )
    if kind is SaveUnitKind.PS2_WHOLE_CARD:
        values.update(
            unit_id="shared-card-1", game_ids=("SLUS-00001", "SLUS-00002"),
            emulator="pcsx2", native_format="ps2-card",
        )
    values.update(changes)
    return SaveBinding(**values)


class EmulatorSaveInventoryTests(unittest.TestCase):
    def test_tree_hash_is_order_independent_and_sensitive_to_members_and_names(self):
        unit = binding()
        files = {"slot/DATA.BIN": b"save", "PARAM.SFO": b"metadata"}
        first = build_save_manifest(unit, files, complete=True)
        second = build_save_manifest(unit, dict(reversed(tuple(files.items()))), complete=True)
        self.assertEqual(first, second)
        self.assertNotEqual(first.sha256, build_save_manifest(
            unit, {"slot/DATA.BIN": b"save"}, complete=False).sha256)
        self.assertNotEqual(first.sha256, build_save_manifest(
            unit, {"other/DATA.BIN": b"save", "PARAM.SFO": b"metadata"}, complete=True).sha256)
        self.assertEqual(first.members[1].sha256, hashlib.sha256(b"save").hexdigest())

    def test_transport_path_change_does_not_convert_card_bytes(self):
        unit = binding(SaveUnitKind.PS2_WHOLE_CARD)
        data = b"synthetic whole card containing two games"
        manifest = build_save_manifest(unit, {"card": data}, complete=True)
        self.assertEqual(manifest.members[0].sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest.binding.game_ids, ("SLUS-00001", "SLUS-00002"))
        with self.assertRaisesRegex(ValueError, "whole card"):
            build_save_manifest(unit, {"game1": b"a", "game2": b"b"}, complete=True)

    def test_psp_identity_comes_from_game_id_not_rom_name(self):
        with self.assertRaisesRegex(ValueError, "game ID"):
            binding(unit_id="Renamed-ROM")
        self.assertEqual(binding().unit_id, "ULUS00001")

    def test_manifest_is_immutable_and_does_not_retain_mutable_input(self):
        files = {"DATA.BIN": b"original"}
        manifest = build_save_manifest(binding(), files, complete=True)
        digest = manifest.sha256
        files["DATA.BIN"] = b"edited"
        self.assertEqual(manifest.sha256, digest)
        with self.assertRaises(FrozenInstanceError):
            manifest.complete = False

    def test_invalid_members_and_ambiguous_names_are_rejected(self):
        for name in ("../save", "/save", "a//b", "a/./b", "C:save", "a\\b", "bad\nname"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                build_save_manifest(binding(), {name: b"fixture"}, complete=True)
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            build_save_manifest(binding(), {"DATA": b"a", "data": b"b"}, complete=True)
        with self.assertRaises(ValueError):
            build_save_manifest(binding(), {"DATA": bytearray(b"a")}, complete=True)

    def test_bounds_are_checked_before_hashing(self):
        with self.assertRaises(ValueError):
            build_save_manifest(binding(), {str(i): b"" for i in range(MAX_FILES + 1)}, complete=True)
        with patch("regear.domain.emulator_save_inventory.MAX_FILE_BYTES", 2):
            with self.assertRaises(ValueError):
                build_save_manifest(binding(), {"DATA": b"abc"}, complete=True)
        with patch("regear.domain.emulator_save_inventory.MAX_UNIT_BYTES", 3):
            with self.assertRaises(ValueError):
                build_save_manifest(binding(), {"A": b"aa", "B": b"bb"}, complete=True)
        self.assertGreaterEqual(MAX_FILE_BYTES, 8 * 1024 * 1024)
        self.assertGreaterEqual(MAX_UNIT_BYTES, MAX_FILE_BYTES)

    def test_corrupt_digest_and_incomplete_declaration_are_distinct(self):
        manifest = build_save_manifest(binding(), {"DATA": b"x"}, complete=False)
        self.assertFalse(manifest.complete)
        with self.assertRaisesRegex(ValueError, "corrupt"):
            replace(manifest, sha256="0" * 64)
        with self.assertRaises(ValueError):
            replace(manifest, complete=1)
        with self.assertRaises(ValueError):
            SaveMember("DATA", True, "0" * 64)

    def test_separate_app_ids_paths_and_unknown_rule_provenance(self):
        unit = binding(emulator_version=None, format_version=None)
        launch = LaunchIdentity("emudeck-shortcut", "fixture", "9000000001", None, "1118310")
        paths = SavePathEvidence("/fixture/native/card.ps2", "/fixture/target/card.ps2")
        rule = CloudRuleEvidence(None, None, None, None, "*.srm", None, None, None)
        inv = EmulatorSaveInventory(
            unit, launch, paths, rule, build_save_manifest(unit, {"DATA": b"x"}, complete=True))
        self.assertNotEqual(inv.launch.shortcut_app_id, inv.launch.carrier_app_id)
        self.assertIsNone(inv.launch.emulator_app_id)
        self.assertIn("cloud_rule_unverified", inv.unknowns)
        self.assertIn("path_target_unverified", inv.unknowns)
        self.assertIn("version_unknown", inv.unknowns)
        self.assertEqual(inv.origin, "fixture")
        with self.assertRaises(ValueError):
            replace(inv, origin="live")
        with self.assertRaises(ValueError):
            replace(inv, manifest=replace(inv.manifest, binding=binding(unit_id="ULUS00002", game_ids=("ULUS00002",))))

    def test_bad_or_cyclic_metadata_does_not_become_verified(self):
        with self.assertRaises(ValueError):
            SavePathEvidence("/fixture/a", "/fixture/b", ("/fixture/b", "/fixture/b"))
        with self.assertRaises(ValueError):
            SavePathEvidence(None, None, [], True, True)
        with self.assertRaises(ValueError):
            LaunchIdentity(None, None, True, None, None)
        with self.assertRaises(ValueError):
            CloudRuleEvidence("fixture", "bad", "linux", "/fixture", "*", True, 1, True)

    def test_save_states_remain_explicitly_separate(self):
        ordinary = binding()
        state = replace(ordinary, data_kind=SaveDataKind.SAVE_STATE)
        self.assertNotEqual(state, ordinary)


if __name__ == "__main__":
    unittest.main()
