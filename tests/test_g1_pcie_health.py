import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("health", Path(__file__).resolve().parents[1] / "scripts/capture_g1_pcie_health.py")
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)


class HealthTests(unittest.TestCase):
    def test_missing_inventory_and_absent_gpu_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(health.collect(root)["status"], "g1_absent")
            self.assertEqual(health.collect(root / "missing")["status"], "pci_unavailable")

    def test_missing_malformed_and_zero_counters_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "counter"
            self.assertIsNone(health.counters(p))
            for bad in ("", "ACSViol -1", "ACSViol unknown", "ACSViol 1\nACSViol 2", "ACSViol " + str(2**64)):
                p.write_text(bad)
                self.assertIsNone(health.counters(p))
            p.write_text("ACSViol 0\nTOTAL_ERR_NONFATAL 0\n")
            self.assertEqual(health.counters(p), {"ACSViol": 0, "TOTAL_ERR_NONFATAL": 0})

    def test_ambiguous_gpu_is_not_chosen_by_enumeration_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("gpu-a", "gpu-b"):
                p = root / name
                p.mkdir()
                (p / "vendor").write_text("0x1002")
                (p / "device").write_text("0x7480")
            self.assertEqual(health.collect(root)["status"], "g1_ambiguous")
