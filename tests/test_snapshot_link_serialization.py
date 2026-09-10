from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.serialization import snapshot_from_dict, snapshot_to_dict  # noqa: E402


class SnapshotLinkSerializationTests(unittest.TestCase):
    def _fixture(self) -> dict:
        return json.loads(
            (ROOT / "tests" / "fixtures" / "tv-docked.json").read_text(
                encoding="utf-8"
            )
        )

    def test_round_trips_observed_link_metrics_without_claiming_link_quality(self):
        value = self._fixture()
        value["egpu_link"] = {
            "applicable": True,
            "state": "up",
            "confidence": "observed",
            "reason": "egpu.link_observed",
            "speed_gtps": 16.0,
            "width_lanes": 4,
        }

        round_tripped = snapshot_to_dict(snapshot_from_dict(value))

        self.assertEqual(round_tripped["egpu_link"]["speed_gtps"], 16.0)
        self.assertEqual(round_tripped["egpu_link"]["width_lanes"], 4)

    def test_rejects_invalid_link_metric_types(self):
        value = self._fixture()
        value["egpu_link"] = {
            "applicable": True,
            "state": "up",
            "confidence": "observed",
            "speed_gtps": "16.0",
            "width_lanes": 4,
        }
        with self.assertRaisesRegex(ValueError, "egpu_link.speed_gtps"):
            snapshot_from_dict(value)

        value = copy.deepcopy(value)
        value["egpu_link"]["speed_gtps"] = 16.0
        value["egpu_link"]["width_lanes"] = -1
        with self.assertRaisesRegex(ValueError, "egpu_link.width_lanes"):
            snapshot_from_dict(value)

    def test_legacy_snapshot_without_metrics_remains_supported(self):
        snapshot = snapshot_from_dict(self._fixture())

        self.assertIsNone(snapshot.egpu_link.speed_gtps)
        self.assertIsNone(snapshot.egpu_link.width_lanes)


if __name__ == "__main__":
    unittest.main()
