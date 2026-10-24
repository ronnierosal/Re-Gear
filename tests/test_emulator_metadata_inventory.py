from __future__ import annotations

import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.emulator_metadata_inventory import (  # noqa: E402
    CaptureResult, CloudRuleMetadata, EmulatorMetadata, GameMetadata, LaunchMetadata,
    MetadataError, MetadataInventory, Origin, Reason, Role, SaveRootEvidence,
    SourceEvidence, SteamInstallation,
)

SECRET = "PRIVATE_USERNAME_DO_NOT_PRINT"
SHA = "a" * 64


def fixture_rows():
    return [
        {"role": "emudeck", "payload": {"version": "2.4.0", "emulation_root": "/home/" + SECRET}},
        {"role": "emulator", "payload": {"name": "PPSSPP", "distribution": "flatpak",
            "version": "1.19.3", "native_format": "psp-savedata", "format_version": "1"}},
        {"role": "launch", "payload": {"source": "steam-rom-manager", "shortcut_app_id": "9000000001",
            "emulator_app_id": "222222", "carrier_app_id": "1118310", "dlc_app_id": "1234350",
            "raw_command": "/home/" + SECRET + "/launch --private"}},
        {"role": "identity", "payload": {"system": "psp", "unit_kind": "psp_game_directory",
            "unit_id": "ULUS12345", "physical_directory": "ULUS12345DATA00", "game_ids": ["ULUS12345"],
            "confirmed": True, "provenance": "synthetic-game-metadata", "selected_slots": ["slot00"]}},
    ]


def fixture_bytes(rows=None):
    return json.dumps({"schema": 1, "records": fixture_rows() if rows is None else rows}).encode()


class InventoryTests(unittest.TestCase):
    def test_nested_models_are_frozen_and_sensitive_repr_is_hidden(self):
        source = SourceEvidence(Role.EMULATOR, Origin.FIXTURE, SHA, SECRET)
        inventory = MetadataInventory(Origin.FIXTURE, (source,), EmulatorMetadata(SECRET, SECRET, SECRET))
        with self.assertRaises(FrozenInstanceError):
            inventory.emulator.name = "changed"
        self.assertNotIn(SECRET, repr(inventory))
        self.assertNotIn(SECRET, repr(source))
        self.assertNotIn(SECRET, repr(inventory.emulator))

    def test_source_rejects_mutable_wrong_type_or_mixed_origin(self):
        for role, origin, digest in (("emulator", Origin.FIXTURE, SHA),
                                     (Role.EMULATOR, "fixture", SHA),
                                     (Role.EMULATOR, Origin.FIXTURE, "bad")):
            with self.subTest(role=role, origin=origin, digest=digest), self.assertRaises(MetadataError):
                SourceEvidence(role, origin, digest, SECRET)
        source = SourceEvidence(Role.EMULATOR, Origin.FIXTURE, SHA, SECRET)
        for sources in ([source], (source, source)):
            with self.assertRaises(MetadataError):
                MetadataInventory(Origin.FIXTURE, sources)
        with self.assertRaises(MetadataError):
            MetadataInventory(Origin.LOCAL_METADATA, (source,))

    def test_app_ids_remain_distinct_and_boolean_coercion_rejects(self):
        launch = LaunchMetadata("srm", "9000000001", "222222", "1118310", "1234350")
        self.assertEqual((launch.shortcut_app_id, launch.emulator_app_id, launch.carrier_app_id,
                          launch.dlc_app_id), ("9000000001", "222222", "1118310", "1234350"))
        for value in (True, 1118310, "0", "1118310-secret"):
            with self.assertRaises(MetadataError):
                LaunchMetadata("srm", carrier_app_id=value)

    def test_psp_game_id_and_physical_slot_directory_are_separate(self):
        game = GameMetadata("psp", "psp_game_directory", "ULUS12345", "ULUS12345DATA00",
                            ("ULUS12345",), True, "fixture-title-metadata", ("slot00",))
        self.assertNotEqual(game.unit_id, game.physical_directory)
        self.assertEqual(game.game_ids, ("ULUS12345",))

    def test_confirmed_identity_requires_shape_and_provenance(self):
        for system, kind, unit, ids, provenance in (
            ("psp", "psp_game_directory", "Renamed-ROM", ("Renamed-ROM",), "fixture"),
            ("psp", "psp_game_directory", "ULUS12345", ("ULUS12345",), None),
            ("psp", "psp_game_directory", "ULUS12345DATA00", ("ULUS12345",), "fixture"),
            ("ps2", "ps2_whole_card", "card1", (), "fixture"),
        ):
            with self.subTest(system=system, unit=unit), self.assertRaises(MetadataError):
                GameMetadata(system, kind, unit, game_ids=ids, confirmed=True, provenance=provenance)

    def test_homebrew_and_shaped_unconfirmed_identity_remain_unknown(self):
        for unit in ("Homebrew-Name", "ULUS12345"):
            game = GameMetadata("psp", "psp_game_directory", unit, game_ids=(unit,))
            self.assertIn(Reason.GAME_IDENTITY_UNKNOWN, MetadataInventory(Origin.FIXTURE, game=game).reasons)

    def test_identity_type_and_state_separation(self):
        for confirmed in (1, 0, "true"):
            with self.assertRaises(MetadataError):
                GameMetadata("psp", "psp_game_directory", "ULUS12345", confirmed=confirmed)
        with self.assertRaises(MetadataError):
            GameMetadata([], "unknown", "unit")
        with self.assertRaises(MetadataError):
            GameMetadata("psp", "ps2_whole_card", "unit")
        game = GameMetadata("psp", "psp_game_directory", "ULUS12345", data_kind="save_state")
        self.assertIn(Reason.SAVE_STATE_SEPARATE, MetadataInventory(Origin.FIXTURE, game=game).reasons)

    def test_ps2_whole_card_membership_never_inferred(self):
        game = GameMetadata("ps2", "ps2_whole_card", "card1", selected_slots=("slot1", "slot2"))
        self.assertEqual(game.game_ids, ())
        self.assertIn(Reason.PS2_MEMBERSHIP_UNKNOWN, MetadataInventory(Origin.FIXTURE, game=game).reasons)

    def test_installation_cannot_establish_cloud_coverage(self):
        inventory = MetadataInventory(Origin.FIXTURE, installation=SteamInstallation("1118310", "555", SECRET))
        report = CaptureResult(inventory=inventory)
        self.assertEqual(report.public_summary()["cloud_coverage"], "unknown")
        self.assertIn(Reason.CLOUD_RULES_UNKNOWN, inventory.reasons)
        self.assertEqual(report.exit_code, 1)
        self.assertNotIn(SECRET, json.dumps(report.public_summary()))

    def test_even_qualified_rule_declaration_never_proves_coverage(self):
        rules = CloudRuleMetadata("1118310", "https://publisher.example/rules", "publisher_record", SHA,
            "1", "current", "linux", "AppInstall", ".", "*.sav", True, (), 1000000, 100, "0", True)
        self.assertTrue(rules.complete_declaration)
        inventory = MetadataInventory(Origin.FIXTURE, rules=rules)
        self.assertIn(Reason.CLOUD_COVERAGE_UNVERIFIED, inventory.reasons)
        self.assertIn(Reason.CLOUD_RULES_UNKNOWN, inventory.reasons)
        self.assertEqual(CaptureResult(inventory=inventory).public_summary()["cloud_coverage"], "unknown")

    def test_full_fields_without_explicit_completeness_stay_unknown(self):
        rules = CloudRuleMetadata("1118310", "https://publisher.example/rules", "publisher_record", SHA,
            "1", "current", "linux", "AppInstall", ".", "*.sav", True, (), 1000000, 100, "0")
        self.assertFalse(rules.complete_declaration)
        self.assertIn(Reason.CLOUD_RULES_UNKNOWN, MetadataInventory(Origin.FIXTURE, rules=rules).reasons)
        with self.assertRaises(MetadataError):
            CloudRuleMetadata("1118310", record_complete=1)

    def test_cached_stale_partial_and_wrong_app_rules(self):
        for category in ("steam_cache", "steamdb", "remote_cache", "unknown"):
            rules = CloudRuleMetadata("1118310", source_category=category)
            self.assertFalse(rules.complete_declaration)
        self.assertFalse(CloudRuleMetadata("1118310", freshness="stale").complete_declaration)
        with self.assertRaises(MetadataError):
            CloudRuleMetadata("1234350")
        for quota in (True, -1, "100"):
            with self.assertRaises(MetadataError):
                CloudRuleMetadata("1118310", byte_quota=quota)
        with self.assertRaises(MetadataError):
            CloudRuleMetadata("1118310", root_overrides=[])

    def test_public_versions_cannot_smuggle_private_labels(self):
        inventory = MetadataInventory(Origin.FIXTURE, emulator=EmulatorMetadata(SECRET, version=SECRET),
                                      emudeck_version="2.4.0")
        summary = CaptureResult(inventory=inventory).public_summary()
        self.assertEqual(summary["versions"], ["2.4.0"])
        self.assertNotIn(SECRET, json.dumps(summary))

    def test_private_link_targets_and_configuration_are_hidden(self):
        inventory = MetadataInventory(Origin.FIXTURE,
            save_roots=(SaveRootEvidence(SECRET, (SECRET + "-target",)),),
            configuration=(("private-field", SECRET),))
        self.assertNotIn(SECRET, json.dumps(CaptureResult(inventory=inventory).public_summary()))
        with self.assertRaises(MetadataError):
            MetadataInventory(Origin.FIXTURE, configuration=(("a", "b"), ("A", "c")))

    def test_errors_and_results_are_categorical(self):
        error = MetadataError(SECRET)
        self.assertEqual(str(error), "invalid_input")
        self.assertNotIn(SECRET, repr(error))
        with self.assertRaises(MetadataError):
            CaptureResult()
        with self.assertRaises(MetadataError):
            CaptureResult(inventory=MetadataInventory(Origin.FIXTURE), failure=Reason.INVALID_INPUT)
        self.assertEqual(CaptureResult(failure=Reason.MALFORMED_METADATA).exit_code, 2)
        self.assertEqual(CaptureResult(failure=Reason.UNSUPPORTED_SAFE_OPEN).exit_code, 1)


if __name__ == "__main__":
    unittest.main()
