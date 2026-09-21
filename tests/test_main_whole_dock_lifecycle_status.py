from __future__ import annotations

import json
import sys
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.serialization import snapshot_from_dict

from tests.test_main_process_delivery import SnapshotApi, load_main_module


FIXTURES = ROOT / "tests" / "fixtures"


def fixture(name: str):
    return snapshot_from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


class WholeDockLifecycleSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module()

    def project(self, snapshot, claim):
        store = self.module.WholeDockClaimStore.return_value
        store.load.return_value = claim
        return self.module.Plugin._whole_dock_lifecycle_payload(snapshot)

    def test_software_down_is_delivered_after_external_gpu_disappears(self):
        with patch.object(self.module, "WholeDockClaimStore") as store_type:
            payload = self.project(
                fixture("portable.json"),
                SimpleNamespace(stage="software_down"),
            )
        self.assertEqual(payload["state"], "software_down")
        self.assertEqual(payload["code"], "whole_dock.software_down")
        self.assertEqual(set(payload), {"schema_version", "state", "code"})

    def test_software_down_conflicts_with_observed_external_gpu(self):
        with patch.object(self.module, "WholeDockClaimStore") as store_type:
            payload = self.project(
                fixture("tv-docked.json"),
                SimpleNamespace(stage="software_down"),
            )
        self.assertEqual(payload["state"], "conflict")
        self.assertEqual(payload["code"], "whole_dock.software_down_gpu_present")

    def test_unreadable_claim_does_not_fail_snapshot_projection(self):
        with patch.object(self.module, "WholeDockClaimStore") as store_type:
            store_type.return_value.load.side_effect = ValueError("private detail")
            payload = self.module.Plugin._whole_dock_lifecycle_payload(
                fixture("portable.json")
            )
        self.assertEqual(
            payload,
            {
                "schema_version": 1,
                "state": "unknown",
                "code": "whole_dock.claim_unreadable",
            },
        )
        self.assertNotIn("private detail", repr(payload))

    def test_claim_is_read_from_current_runtime_state_root(self):
        with patch.object(self.module, "WholeDockClaimStore") as store_type:
            store_type.return_value.load.return_value = None
            self.module.Plugin._whole_dock_lifecycle_payload(
                fixture("portable.json")
            )
        store_type.assert_called_once_with(self.module.DEFAULT_RUNTIME_STATE_ROOT)

    def test_get_snapshot_delivers_normalized_lifecycle(self):
        snapshot = fixture("portable.json")
        plugin = self.module.Plugin()
        plugin._api = SnapshotApi(snapshot)
        with patch.object(self.module, "WholeDockClaimStore") as store_type:
            store_type.return_value.load.return_value = SimpleNamespace(
                stage="software_down"
            )
            payload = asyncio.run(plugin.get_snapshot())
        self.assertEqual(
            payload["whole_dock_lifecycle"],
            {
                "schema_version": 1,
                "state": "software_down",
                "code": "whole_dock.software_down",
            },
        )


if __name__ == "__main__":
    unittest.main()
