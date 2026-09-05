import json
import os
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from hdm.delivery.auto_tdp_preferences import (
    FILENAME,
    MAX_BYTES,
    FileAutoTdpPreferences,
    decode_auto_tdp_preferences,
    encode_auto_tdp_preferences,
)
from hdm.domain.auto_tdp import AutoTdpPolicy
from hdm.domain.auto_tdp_preferences import AutoTdpModePreference, AutoTdpPreferenceSet
from hdm.domain.control_plane import PlacementState


class AutoTdpPreferenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = FileAutoTdpPreferences(self.root)
        self.target = self.root / FILENAME
        self.portable = AutoTdpPolicy(7, 18, 40)
        self.docked = AutoTdpPolicy(10, 22, 50)

    def test_missing_has_no_defaults_or_side_effect(self):
        result = self.storage.load()
        self.assertEqual(result.code, "auto_tdp_preferences.missing")
        self.assertIsNone(result.preferences)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_save_and_load_exact_policy(self):
        saved = self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, self.portable))
        self.assertEqual(saved.code, "auto_tdp_preferences.saved")
        loaded = FileAutoTdpPreferences(self.root).load()
        self.assertEqual(loaded.code, "auto_tdp_preferences.loaded")
        self.assertEqual(loaded.preferences, saved.preferences)
        self.assertEqual(loaded.preferences.preferences[0].policy, self.portable)
        payload = self.target.read_text(encoding="ascii")
        self.assertNotIn("enabled", payload)
        self.assertNotIn("thermal", payload)
        self.assertNotIn("admission", payload)

    def test_save_mode_preserves_other_modes_and_replaces_only_exact_mode(self):
        self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, self.portable))
        self.storage.save_preference(AutoTdpModePreference(PlacementState.DOCKED_IGPU, self.docked))
        replacement = AutoTdpPolicy(8, 19, 45)
        result = self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, replacement))
        by_mode = {item.placement: item.policy for item in result.preferences.preferences}
        self.assertEqual(by_mode, {
            PlacementState.PORTABLE: replacement,
            PlacementState.DOCKED_IGPU: self.docked,
        })
        self.assertEqual(self.storage.load().preferences, result.preferences)

    def test_single_instance_serializes_concurrent_read_modify_write(self):
        requests = (
            AutoTdpModePreference(PlacementState.PORTABLE, self.portable),
            AutoTdpModePreference(PlacementState.BOOSTED_HANDHELD, AutoTdpPolicy(9, 21, 45)),
            AutoTdpModePreference(PlacementState.DOCKED_IGPU, self.docked),
            AutoTdpModePreference(PlacementState.DOCKED_EGPU, AutoTdpPolicy(8, 16, 30)),
        )
        gate = threading.Barrier(len(requests))
        results = []
        def save(item):
            gate.wait(timeout=2)
            results.append(self.storage.save_preference(item).code)
        threads = [threading.Thread(target=save, args=(item,)) for item in requests]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(results, ["auto_tdp_preferences.saved"] * len(requests))
        stored = self.storage.load().preferences
        self.assertEqual({item.placement for item in stored.preferences}, {item.placement for item in requests})

    def test_only_player_fields_are_explicit_and_roundtrip(self):
        policy = AutoTdpPolicy(6, 20, 48.0)
        result = self.storage.save_preference(AutoTdpModePreference(PlacementState.BOOSTED_HANDHELD, policy))
        raw = json.loads(self.target.read_bytes())
        self.assertEqual(set(raw["preferences"][0]), {"placement", "target_fps", "minimum_watts", "maximum_watts"})
        self.assertEqual(result.preferences.preferences[0].policy, policy)

    def test_custom_policy_tuning_is_rejected_without_silent_loss(self):
        for policy in (
            AutoTdpPolicy(6, 20, 48, deadband_fps=1),
            AutoTdpPolicy(6, 20, 48, step_watts=2),
            AutoTdpPolicy(6, 20, 48, settling_ms=6000),
            AutoTdpPolicy(6, 20, 48, maximum_sample_age_ms=1500),
            AutoTdpPolicy(6, 20, 48, missed_target_samples=4),
            AutoTdpPolicy(6, 20, 48, stable_target_samples=7),
        ):
            with self.subTest(policy=policy):
                result = self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, policy))
                self.assertEqual(result.code, "auto_tdp_preferences.save_failed")
                self.assertFalse(self.target.exists())

    def test_decoder_rejects_unknown_missing_duplicate_schema_and_empty(self):
        valid = json.loads(encode_auto_tdp_preferences(AutoTdpPreferenceSet((
            AutoTdpModePreference(PlacementState.PORTABLE, self.portable),
        ))))
        invalid = []
        extra = deepcopy(valid); extra["extra"] = True; invalid.append(extra)
        missing = deepcopy(valid); missing.pop("preferences"); invalid.append(missing)
        boolean = deepcopy(valid); boolean["schema_version"] = True; invalid.append(boolean)
        wrong = deepcopy(valid); wrong["schema_version"] = 2; invalid.append(wrong)
        empty = deepcopy(valid); empty["preferences"] = []; invalid.append(empty)
        row_extra = deepcopy(valid); row_extra["preferences"][0]["extra"] = 1; invalid.append(row_extra)
        policy_extra = deepcopy(valid); policy_extra["preferences"][0]["extra"] = 1; invalid.append(policy_extra)
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    decode_auto_tdp_preferences(json.dumps(value).encode())
        raw = encode_auto_tdp_preferences(AutoTdpPreferenceSet((AutoTdpModePreference(PlacementState.PORTABLE, self.portable),)))
        duplicate = raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
        with self.assertRaises(ValueError):
            decode_auto_tdp_preferences(duplicate)

    def test_duplicate_placement_and_invalid_policy_are_rejected(self):
        policy = {"minimum_watts": 7, "maximum_watts": 18, "target_fps": 40}
        row = {"placement": "portable", **policy}
        for rows in (
            [row, row],
            [{"placement": "unknown", **policy}],
            [{"placement": "portable", **policy, "minimum_watts": True}],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                decode_auto_tdp_preferences(json.dumps({"schema_version": 1, "preferences": rows}).encode())

    def test_byte_bound_non_bytes_and_malformed_are_rejected(self):
        for raw in ("{}", b"x" * (MAX_BYTES + 1), b"not json", b"\xff"):
            with self.subTest(raw_type=type(raw), length=len(raw)), self.assertRaises((ValueError, UnicodeError)):
                decode_auto_tdp_preferences(raw)

    def test_invalid_existing_file_is_not_overwritten(self):
        self.target.write_bytes(b"private corrupt data")
        before = self.target.read_bytes()
        result = self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, self.portable))
        self.assertEqual(result.code, "auto_tdp_preferences.save_failed")
        self.assertEqual(self.target.read_bytes(), before)

    def test_invalid_save_request_has_no_file_side_effect(self):
        for value in (object(), None, "portable"):
            with self.subTest(value=value):
                result = self.storage.save_preference(value)
                self.assertEqual(result.code, "auto_tdp_preferences.save_failed")
                self.assertFalse(self.target.exists())

    def test_replace_failure_preserves_prior_file_and_removes_temporary(self):
        self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, self.portable))
        before = self.target.read_bytes()
        with patch("hdm.delivery.auto_tdp_preferences.os.replace", side_effect=OSError("private failure")):
            result = self.storage.save_preference(AutoTdpModePreference(PlacementState.DOCKED_IGPU, self.docked))
        self.assertEqual(result.code, "auto_tdp_preferences.save_failed")
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual([path.name for path in self.root.iterdir()], [FILENAME])

    def test_directory_target_is_rejected_for_load_and_save(self):
        self.target.mkdir()
        self.assertEqual(self.storage.load().code, "auto_tdp_preferences.invalid")
        self.assertEqual(self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, self.portable)).code, "auto_tdp_preferences.save_failed")

    @unittest.skipUnless(os.name == "posix", "POSIX ownership and symlink semantics")
    def test_group_writable_file_root_and_symlink_are_rejected(self):
        self.storage.save_preference(AutoTdpModePreference(PlacementState.PORTABLE, self.portable))
        self.target.chmod(0o660)
        self.assertEqual(self.storage.load().code, "auto_tdp_preferences.invalid")
        self.target.chmod(0o600)
        self.root.chmod(0o770)
        self.assertEqual(self.storage.load().code, "auto_tdp_preferences.invalid")
        self.root.chmod(0o700)
        other = self.root / "other.json"
        self.target.rename(other)
        self.target.symlink_to(other)
        self.assertEqual(self.storage.load().code, "auto_tdp_preferences.invalid")


if __name__ == "__main__":
    unittest.main()
