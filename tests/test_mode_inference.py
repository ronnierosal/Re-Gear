from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.snapshot import SnapshotService  # noqa: E402
from regear.domain.inference import infer_operating_mode  # noqa: E402
from regear.domain.models import OperatingMode  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def load_fixture(name: str):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return value, snapshot_from_dict(value)


class ModeInferenceTests(unittest.TestCase):
    def test_fixture_matrix(self):
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(path=path.name):
                value, snapshot = load_fixture(path.name)
                actual = infer_operating_mode(snapshot)
                self.assertEqual(actual.mode, OperatingMode(value["expected_mode"]))

    def test_unknown_schema_version_is_rejected(self):
        value, _ = load_fixture("portable.json")
        value["schema_version"] = 99
        with self.assertRaisesRegex(ValueError, "Unsupported snapshot schema"):
            snapshot_from_dict(value)

    def test_snapshot_service_uses_the_same_inference_path(self):
        _, snapshot = load_fixture("tv-docked.json")

        class FakeDiscovery:
            def collect_snapshot(self):
                return snapshot

        report = SnapshotService(FakeDiscovery()).observe()
        self.assertIs(report.snapshot, snapshot)
        self.assertEqual(report.inference.mode, OperatingMode.TV_DOCKED)

    def test_gamescope_render_identity_conflict_is_unknown(self):
        value, _ = load_fixture("tv-docked.json")
        value["gamescope"]["render_gpu_stable_id"] = "internal-gpu"
        inference = infer_operating_mode(snapshot_from_dict(value))
        self.assertEqual(inference.mode, OperatingMode.UNKNOWN)
        self.assertIn("conflicts", inference.reasons[0])

    def test_string_boolean_is_rejected(self):
        value, _ = load_fixture("portable.json")
        value["gpus"][0]["present"] = "false"
        with self.assertRaisesRegex(ValueError, "gpu.present"):
            snapshot_from_dict(value)


if __name__ == "__main__":
    unittest.main()
