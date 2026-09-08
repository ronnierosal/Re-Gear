import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from hdm.adapters.steamos.tdp_inventory import AsusTdpInventory, MAX_VALUE_BYTES


class TdpInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.firmware = self.root / "class/firmware-attributes/asus-armoury/attributes"
        self.legacy = self.root / "devices/platform/asus-nb-wmi"

    def attribute(self, name, **fields):
        directory = self.firmware / name
        directory.mkdir(parents=True, exist_ok=True)
        for field, value in fields.items():
            (directory / field).write_bytes(str(value).encode("utf-8"))

    def scan(self):
        return AsusTdpInventory(self.root).scan().to_dict()

    def row(self, name="ppt_pl1_spl", source="asus_firmware_attributes"):
        return next(row for row in self.scan()["sources"] if row["attribute"] == name and row["source"] == source)

    def test_absent_roots(self):
        result = self.scan()
        self.assertEqual(result["limits"], dict.fromkeys(("sustained", "slow", "fast"), "absent"))
        self.assertEqual(len(result["sources"]), 7)
        self.assertTrue(all(row["status"] == "absent" for row in result["sources"]))

    def test_distinct_limit_values_and_optional_default(self):
        for name, current, maximum in (("ppt_pl1_spl", 17, 30), ("ppt_pl2_sppt", 25, 43), ("ppt_pl3_fppt", 30, 53)):
            self.attribute(name, current_value=current, min_value=5, max_value=maximum)
            row = self.row(name)
            self.assertEqual(row["status"], "observed")
            self.assertEqual(row["fields"]["current_value"]["value"], current)
            self.assertEqual(row["fields"]["max_value"]["value"], maximum)
            self.assertEqual(row["fields"]["default_value"]["status"], "absent")
        self.assertEqual(self.scan()["value_kind"], "firmware_power_limit_setting")

    def test_missing_bounds_retains_current(self):
        self.attribute("ppt_pl1_spl", current_value=17)
        row = self.row()
        self.assertEqual(row["status"], "incomplete")
        self.assertEqual(row["fields"]["current_value"], {"status": "observed", "value": 17})
        self.assertEqual(row["ordering"], "incomplete")

    def test_empty_present_attribute_is_incomplete(self):
        self.attribute("ppt_pl1_spl")
        self.assertEqual(self.row()["status"], "incomplete")

    def test_malformed_nonfinite_negative_and_oversized_values(self):
        for value in ("", "NaN", "inf", "-1", "+1", "1.0", "1e2", "12 W", "12\x00", "１２", "9" * (MAX_VALUE_BYTES + 1)):
            with self.subTest(value=value):
                self.attribute("ppt_pl1_spl", current_value=value, min_value=5, max_value=30)
                row = self.row()
                self.assertEqual(row["status"], "invalid")
                self.assertEqual(row["fields"]["current_value"], {"status": "invalid", "value": None})
                self.assertEqual(row["fields"]["min_value"]["value"], 5)

    def test_strict_integer_allows_zero_and_sysfs_newline(self):
        self.attribute("ppt_pl1_spl", current_value="0\n", min_value=0, max_value="30\n")
        self.assertEqual(self.row()["status"], "observed")

    def test_invalid_bounds_do_not_erase_current(self):
        self.attribute("ppt_pl1_spl", current_value=17, min_value="NaN", max_value=30)
        row = self.row()
        self.assertEqual(row["status"], "invalid")
        self.assertEqual(row["fields"]["current_value"]["value"], 17)

    def test_ordering_checks_current_default_and_reversed_bounds(self):
        for fields in (
            dict(current_value=17, min_value=30, max_value=5),
            dict(current_value=31, min_value=5, max_value=30),
            dict(current_value=4, min_value=5, max_value=30),
            dict(current_value=17, min_value=5, max_value=30, default_value=31),
        ):
            with self.subTest(fields=fields):
                self.attribute("ppt_pl1_spl", **fields)
                self.assertEqual(self.row()["ordering"], "inconsistent")
                self.assertEqual(self.row()["status"], "invalid")

    def test_partial_bounds_still_detect_inconsistency(self):
        self.attribute("ppt_pl1_spl", current_value=17, max_value=10)
        self.assertEqual(self.row()["ordering"], "inconsistent")

    def test_both_fast_aliases_are_ambiguous_even_when_equal(self):
        for name in ("ppt_fppt", "ppt_pl3_fppt"):
            self.attribute(name, current_value=30, min_value=5, max_value=53)
        self.assertEqual(self.scan()["limits"]["fast"], "ambiguous")

    def test_legacy_current_only_and_overlapping_backend_ambiguity(self):
        self.legacy.mkdir(parents=True)
        (self.legacy / "ppt_pl1_spl").write_text("17\n")
        row = self.row(source="asus_legacy_wmi")
        self.assertEqual(row["status"], "incomplete")
        self.assertEqual(row["fields"]["current_value"]["value"], 17)
        self.attribute("ppt_pl1_spl", current_value=20, min_value=5, max_value=30)
        self.assertEqual(self.scan()["limits"]["sustained"], "ambiguous")

    def test_invalid_alias_still_prevents_silent_selection(self):
        self.attribute("ppt_fppt", current_value="NaN")
        self.attribute("ppt_pl3_fppt", current_value=30, min_value=5, max_value=53)
        self.assertEqual(self.scan()["limits"]["fast"], "ambiguous")

    def test_unreadable_input_is_invalid_and_public_output_redacted(self):
        with patch.object(Path, "open", side_effect=PermissionError("private path and raw error")):
            result = self.scan()
        self.assertTrue(all(row["status"] == "invalid" for row in result["sources"]))
        serialized = json.dumps(result)
        for forbidden in (str(self.root), "private", "PermissionError", "writable", "safe", "authorized"):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
