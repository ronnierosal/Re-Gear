from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.snapshot import SnapshotReport, report_to_public_dict  # noqa: E402
from regear.domain.inference import infer_operating_mode  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402


class PublicSnapshotTests(unittest.TestCase):
    def test_decky_payload_removes_executable_and_hardware_identity(self):
        value = json.loads(
            (ROOT / "tests" / "fixtures" / "connected-internal.json").read_text(
                encoding="utf-8"
            )
        )
        private = "private-identity-sentinel"
        value["gpus"][0]["stable_id"] = private
        value["gpus"][0]["vendor_device"] = "1002:private"
        value["displays"][0]["stable_id"] = private
        value["displays"][0]["connector"] = "HDMI-A-private"
        value["gamescope"]["pid"] = 12345
        value["gamescope"]["output_order"] = ["HDMI-A-private"]
        value["gamescope"]["render_gpu_stable_id"] = private
        value["gamescope"]["render_vendor_device"] = "1002:private"
        value["disconnect_readiness"] = {
            "applicable": True,
            "scan_complete": True,
            "ready": False,
            "egpu_stable_id": private,
            "clients": [
                {
                    "instance_id": private,
                    "pid": 9876,
                    "name": "ordinary-client",
                    "kind": "user",
                    "resources": ["drm_render"],
                    "close_eligible": True,
                    "reason": "User process outside a Steam game scope",
                    "process_start_time": "987654321",
                }
            ],
            "storage_devices": 0,
            "storage_in_use": False,
            "error": "",
        }
        snapshot = snapshot_from_dict(value)
        payload = report_to_public_dict(
            SnapshotReport(snapshot, infer_operating_mode(snapshot))
        )
        encoded = json.dumps(payload, sort_keys=True)
        for forbidden in (
            private,
            "1002:private",
            "HDMI-A-private",
            "12345",
            "9876",
            "987654321",
        ):
            self.assertNotIn(forbidden, encoded)
        client = payload["snapshot"]["disconnect_readiness"]["clients"][0]
        self.assertEqual(client["name"], "ordinary-client")
        self.assertEqual(client["resources"], ["drm_render"])
        profiles = payload["diagnostics"]["hardware_profiles"]
        self.assertEqual(profiles["schema_version"], 1)
        self.assertEqual(profiles["host"]["status"], "exact")
        self.assertEqual(profiles["egpu"]["status"], "unknown")
        self.assertEqual(payload["delivery_schema_version"], 2)
        self.assertEqual(payload["health"]["state"], "ready")
        self.assertNotIn(private, payload["health"])


if __name__ == "__main__":
    unittest.main()
