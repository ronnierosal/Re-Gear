import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("removal_inventory", Path(__file__).parents[1] / "scripts/capture_egpu_removal_capabilities.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class RemovalCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_absent_registry_is_unknown_not_empty_success(self):
        result = inventory.collect(self.root / "missing")
        self.assertEqual(result["status"], "inventory_unavailable")
        self.assertFalse(result["safe_to_unplug"])

    def test_missing_or_malformed_capability_never_means_supported(self):
        domain = self.root / "domain3"
        domain.mkdir()
        for value in (None, "", "true", "2", "1" * 5000):
            with self.subTest(value=value):
                if value is not None:
                    (domain / "deauthorization").write_text(value)
                result = inventory.collect(self.root)
                self.assertIsNone(result["domains"][0]["deauthorization_supported"])

    def test_supported_capability_does_not_authorize_removal(self):
        domain = self.root / "domain7"
        domain.mkdir()
        (domain / "deauthorization").write_text("1\n")
        result = inventory.collect(self.root)
        self.assertTrue(result["domains"][0]["deauthorization_supported"])
        self.assertFalse(result["safe_to_unplug"])
        self.assertEqual(result["gpu_router_binding"], "unverified")

    def test_unbound_router_never_guesses_domain_from_name(self):
        (self.root / "domain0").mkdir()
        router = self.root / "0-1"
        router.mkdir()
        (router / "authorized").write_text("1")
        result = inventory.collect(self.root)
        self.assertIsNone(result["routers"][0]["domain"])

    def test_explicit_unsupported_and_deauthorized_are_distinct_from_unknown(self):
        domain = self.root / "domain0"
        domain.mkdir()
        (domain / "deauthorization").write_text("0")
        router = self.root / "0-1"
        router.mkdir()
        (router / "authorized").write_text("0")
        result = inventory.collect(self.root)
        self.assertIs(result["domains"][0]["deauthorization_supported"], False)
        self.assertIs(result["routers"][0]["authorized"], False)

    def test_inventory_is_bounded(self):
        for i in range(257):
            (self.root / str(i)).mkdir()
        self.assertEqual(inventory.collect(self.root)["status"], "inventory_limit")


if __name__ == "__main__":
    unittest.main()
