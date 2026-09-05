import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from hdm.adapters.steamos.drm import DrmDiscovery
from hdm.adapters.transition_runtime import versioned_snapshot_observation
from hdm.application.snapshot import SnapshotReport, report_to_public_dict
from hdm.domain.inference import infer_operating_mode
from hdm.domain.serialization import snapshot_from_dict, snapshot_to_dict


class GpuModelNameTests(unittest.TestCase):
    def test_optional_bounded_driver_product_name(self):
        with tempfile.TemporaryDirectory() as root:
            device = Path(root) / "card7" / "device"
            device.mkdir(parents=True)
            scan = DrmDiscovery(Path(root))
            self.assertEqual(scan.scan()[0].model_name, "")
            for raw, expected in [("Example GPU 9000\n", "Example GPU 9000"),
                                  ("unknown", ""), ("x" * 129, ""),
                                  ("GPU\x00name", ""), ("GPU\nname", ""),
                                  ("GPU\u202ename", "")]:
                (device / "product_name").write_text(raw, encoding="utf-8")
                self.assertEqual(scan.scan()[0].model_name, expected)

    def test_name_roundtrips_publicly_without_changing_gpu_identity_or_inference(self):
        raw = json.loads((ROOT / "tests/fixtures/connected-internal.json").read_text())
        original = snapshot_from_dict(raw)
        named = replace(original, gpus=tuple(replace(g, model_name="Example GPU 9000") for g in original.gpus))
        self.assertEqual(original.gpus, named.gpus)
        self.assertEqual(infer_operating_mode(original), infer_operating_mode(named))
        self.assertEqual(snapshot_to_dict(original), snapshot_to_dict(named))
        self.assertEqual(versioned_snapshot_observation(original), versioned_snapshot_observation(named))
        self.assertEqual(snapshot_from_dict(snapshot_to_dict(named, include_presentation=True)).gpus[0].model_name, "Example GPU 9000")
        gpu = report_to_public_dict(SnapshotReport(named, infer_operating_mode(named)))["snapshot"]["gpus"][0]
        self.assertEqual(gpu["model_name"], "Example GPU 9000")
        self.assertNotIn("vendor_device", gpu)
        self.assertNotIn("stable_id", gpu)
        self.assertEqual(original.gpus[0].model_name, "")
