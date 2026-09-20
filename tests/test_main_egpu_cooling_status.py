"""Read-only eGPU cooling projection on the live disconnect status RPC."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from regear.domain.prepared_egpu_disconnect import EgpuCoolingEvidence
from tests.test_main_process_delivery import load_main_module


class MainEgpuCoolingStatusTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)

    def _evidence(self, **changes):
        values = {
            "attachment_binding": "a" * 64,
            "generation": "b" * 64,
            "gpu_bdf": "0000:18:00.0",
            "device_present": True,
            "driver_name": "amdgpu",
            "scan_complete": True,
            "temperatures_c": (51.0, 54.5),
            "fan_rpm": 1840,
            "automatic_fan_control": True,
        }
        values.update(changes)
        return EgpuCoolingEvidence(**values)

    def test_exact_current_topology_drives_read_only_cooling_scan(self):
        binding = NS(
            gpu_bdf="0000:18:00.0",
            binding="a" * 64,
            generation="b" * 64,
        )
        discovery = Mock()
        discovery.scan.return_value = self._evidence()
        with patch.object(self.module, "DrmDiscovery") as drm, \
                patch.object(self.module, "resolve_whole_dock", return_value=binding), \
                patch.object(self.module, "EgpuCoolingDiscovery", return_value=discovery):
            drm.return_value.scan.return_value = [
                NS(boot_vga=True, pci_bdf="0000:04:00.0"),
                NS(boot_vga=False, pci_bdf="0000:18:00.0"),
            ]
            payload = self.plugin._egpu_cooling_status()

        discovery.scan.assert_called_once_with(
            gpu_bdf=binding.gpu_bdf,
            attachment_binding=binding.binding,
            generation=binding.generation,
        )
        self.assertEqual(payload, {
            "schema_version": 1,
            "state": "observed",
            "code": "egpu_cooling.observed",
            "device_present": True,
            "driver_name": "amdgpu",
            "scan_complete": True,
            "temperatures_c": [51.0, 54.5],
            "fan_rpm": 1840,
            "automatic_fan_control": True,
        })
        self.assertNotIn("attachment_binding", payload)
        self.assertNotIn("generation", payload)
        self.assertNotIn("gpu_bdf", payload)

    def test_incomplete_scan_is_reported_without_becoming_a_ready_gate(self):
        binding = NS(
            gpu_bdf="0000:18:00.0",
            binding="a" * 64,
            generation="b" * 64,
        )
        discovery = Mock()
        discovery.scan.return_value = self._evidence(
            scan_complete=False,
            temperatures_c=(),
            fan_rpm=None,
            automatic_fan_control=None,
        )
        with patch.object(self.module, "DrmDiscovery") as drm, \
                patch.object(self.module, "resolve_whole_dock", return_value=binding), \
                patch.object(self.module, "EgpuCoolingDiscovery", return_value=discovery):
            drm.return_value.scan.return_value = [
                NS(boot_vga=False, pci_bdf="0000:18:00.0")
            ]
            payload = self.plugin._egpu_cooling_status()

        self.assertEqual(payload["state"], "incomplete")
        self.assertEqual(payload["code"], "egpu_cooling.evidence_incomplete")
        self.assertFalse(payload["scan_complete"])

    def test_ambiguous_topology_is_unavailable_and_does_not_scan_hwmon(self):
        with patch.object(self.module, "DrmDiscovery") as drm, \
                patch.object(self.module, "resolve_whole_dock") as topology, \
                patch.object(self.module, "EgpuCoolingDiscovery") as cooling:
            drm.return_value.scan.return_value = []
            payload = self.plugin._egpu_cooling_status()

        self.assertEqual(payload["state"], "unavailable")
        self.assertEqual(payload["code"], "egpu_cooling.topology_unavailable")
        topology.assert_not_called()
        cooling.assert_not_called()

    def test_disconnect_status_adds_cooling_without_changing_runtime_decision(self):
        runtime = Mock()
        status = NS()
        runtime.status.return_value = status
        self.plugin._egpu_cooling_status = Mock(return_value={"state": "observed"})
        self.plugin._live_disconnect_runtime = Mock(return_value=runtime)
        with patch.object(
            self.module,
            "disconnect_status_to_payload",
            return_value={"availability": "attemptable", "code": "existing"},
        ) as project:
            payload = asyncio.run(self.plugin.get_egpu_disconnect_status())

        self.assertEqual(payload, {
            "availability": "attemptable",
            "code": "existing",
            "cooling": {"state": "observed"},
        })
        runtime.status.assert_called_once_with()
        project.assert_called_once_with(status)
        self.assertFalse(hasattr(runtime, "execute") and runtime.execute.called)

    def test_cooling_remains_visible_when_session_runtime_is_unavailable(self):
        self.plugin._egpu_cooling_status = Mock(return_value={"state": "observed"})
        self.plugin._live_disconnect_runtime = Mock(return_value=None)

        payload = asyncio.run(self.plugin.get_egpu_disconnect_status())

        self.assertEqual(payload["code"], "live_disconnect.session_unavailable")
        self.assertEqual(payload["cooling"], {"state": "observed"})


if __name__ == "__main__":
    unittest.main()
