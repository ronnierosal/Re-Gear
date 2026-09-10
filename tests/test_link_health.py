from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.link_health import PcieLinkHealthDiscovery  # noqa: E402
from regear.domain.models import Confidence, EgpuLinkState  # noqa: E402


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class PcieLinkHealthDiscoveryTests(unittest.TestCase):
    BDF = "0000:04:00.0"

    def test_reads_only_positive_current_link_metrics_as_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / self.BDF.replace(":", "_")
            write(path / "current_link_speed", "16.0 GT/s PCIe\n")
            write(path / "current_link_width", "x4\n")
            observed = PcieLinkHealthDiscovery(
                path_resolver=lambda _bdf: path
            ).observe(self.BDF)
            self.assertTrue(observed.applicable)
            self.assertEqual(observed.state, EgpuLinkState.UP)
            self.assertEqual(observed.confidence, Confidence.OBSERVED)
            self.assertEqual(observed.reason, "egpu.link_observed")
            self.assertEqual(observed.speed_gtps, 16.0)
            self.assertEqual(observed.width_lanes, 4)

    def test_accepts_kernel_bare_lane_count_as_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / self.BDF.replace(":", "_")
            write(path / "current_link_speed", "2.5 GT/s PCIe\n")
            write(path / "current_link_width", "4\n")
            observed = PcieLinkHealthDiscovery(
                path_resolver=lambda _bdf: path
            ).observe(self.BDF)
            self.assertEqual(observed.state, EgpuLinkState.UP)
            self.assertEqual(observed.confidence, Confidence.OBSERVED)
            self.assertEqual(observed.speed_gtps, 2.5)
            self.assertEqual(observed.width_lanes, 4)

    def test_zero_metric_reports_down_without_claiming_removal_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / self.BDF.replace(":", "_")
            write(path / "current_link_speed", "0.0 GT/s PCIe\n")
            write(path / "current_link_width", "x0\n")
            observed = PcieLinkHealthDiscovery(
                path_resolver=lambda _bdf: path
            ).observe(self.BDF)
            self.assertEqual(observed.state, EgpuLinkState.DOWN)
            self.assertEqual(observed.reason, "egpu.link_down")
            self.assertEqual(observed.speed_gtps, 0.0)
            self.assertEqual(observed.width_lanes, 0)

    def test_missing_or_unparseable_metrics_fail_closed_as_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / self.BDF.replace(":", "_")
            collector = PcieLinkHealthDiscovery(path_resolver=lambda _bdf: path)
            missing = collector.observe(self.BDF)
            self.assertEqual(missing.state, EgpuLinkState.UNKNOWN)
            self.assertEqual(missing.error, "egpu.link_metrics_unavailable")
            write(path / "current_link_speed", "fast\n")
            write(path / "current_link_width", "wide\n")
            invalid = collector.observe(self.BDF)
            self.assertEqual(invalid.state, EgpuLinkState.UNKNOWN)
            self.assertEqual(invalid.error, "egpu.link_metrics_unparseable")

    def test_invalid_identity_never_reads_a_path(self):
        observed = PcieLinkHealthDiscovery(Path("/missing")).observe("not-a-bdf")
        self.assertFalse(observed.applicable)
        self.assertEqual(observed.state, EgpuLinkState.UNKNOWN)
        self.assertEqual(observed.error, "egpu.link_bridge_identity_invalid")


if __name__ == "__main__":
    unittest.main()
