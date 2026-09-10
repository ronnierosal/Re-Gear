from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.wake_diagnostics import (  # noqa: E402
    WakeCapabilityState,
    WakeDiagnosticsDiscovery,
)


ROOT_BDF = "0000:01:00.0"
GPU_BDF = "0000:02:00.0"
AUDIO_BDF = "0000:02:00.1"


def test_path(root: Path, bdf: str) -> Path:
    return root / bdf.replace(":", "_")


def write_attribute(root: Path, bdf: str, name: str, value: str) -> None:
    path = test_path(root, bdf) / "power" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class WakeDiagnosticsTests(unittest.TestCase):
    def test_exact_topology_is_aggregated_without_exposing_bdfs(self):
        with tempfile.TemporaryDirectory() as directory:
            sysfs = Path(directory)
            write_attribute(sysfs, ROOT_BDF, "wakeup", "enabled\n")
            write_attribute(sysfs, ROOT_BDF, "runtime_status", "active\n")
            write_attribute(sysfs, GPU_BDF, "wakeup", "disabled\n")
            write_attribute(sysfs, GPU_BDF, "runtime_status", "active\n")
            write_attribute(sysfs, AUDIO_BDF, "wakeup", "enabled\n")
            write_attribute(sysfs, AUDIO_BDF, "runtime_status", "suspended\n")
            observed = WakeDiagnosticsDiscovery(
                sysfs, lambda bdf: test_path(sysfs, bdf)
            ).observe(
                ROOT_BDF, (ROOT_BDF, GPU_BDF, AUDIO_BDF)
            )
        self.assertTrue(observed.applicable)
        self.assertEqual(observed.bridge_wakeup, WakeCapabilityState.ENABLED)
        self.assertEqual(observed.function_wakeup_enabled, 2)
        self.assertEqual(observed.function_wakeup_disabled, 1)
        self.assertEqual(observed.function_runtime_active, 2)
        self.assertEqual(observed.function_runtime_suspended, 1)
        rendered = repr(observed.to_public_dict())
        self.assertNotIn(ROOT_BDF, rendered)
        self.assertNotIn(GPU_BDF, rendered)

    def test_missing_attributes_remain_unknown_not_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            sysfs = Path(directory)
            observed = WakeDiagnosticsDiscovery(
                sysfs, lambda bdf: test_path(sysfs, bdf)
            ).observe(
                ROOT_BDF, (ROOT_BDF, GPU_BDF)
            )
        self.assertTrue(observed.applicable)
        self.assertEqual(observed.bridge_wakeup, WakeCapabilityState.UNKNOWN)
        self.assertEqual(observed.function_wakeup_unknown, 2)
        self.assertEqual(observed.function_runtime_unknown, 2)

    def test_invalid_or_ambiguous_topology_is_not_applicable(self):
        discovery = WakeDiagnosticsDiscovery(Path("unused"))
        for root, functions, reason in (
            ("bad", (GPU_BDF,), "wake.identity_unverified"),
            (ROOT_BDF, (GPU_BDF, GPU_BDF), "wake.topology_unverified"),
        ):
            with self.subTest(root=root, functions=functions):
                observed = discovery.observe(root, functions)
                self.assertFalse(observed.applicable)
                self.assertEqual(observed.reason, reason)


if __name__ == "__main__":
    unittest.main()
