from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import remote_capture_payload


class RemoteCaptureVersionTests(unittest.TestCase):
    def test_diagnostics_preserves_current_plugin_version(self):
        # Stub every host observation: this is producer/consumer serialization,
        # not a scan of the machine running the tests.
        with (
            patch.object(remote_capture_payload, "PLUGIN_ROOT", ROOT),
            patch.object(remote_capture_payload, "_plugin_version", return_value="0.3.73"),
            patch("regear.api.DiagnosticsApi.get_snapshot", return_value={"snapshot": {}}),
            patch("regear.adapters.steamos.version_info.SteamOsVersionDiscovery.scan",
                  return_value=SimpleNamespace(steamos="test-os", kernel="test-kernel")),
            patch.object(sys, "path", list(sys.path)),
        ):
            payload = remote_capture_payload._diagnostics()
        self.assertEqual(payload["versions"], {
            "regear": "0.3.73", "decky": "unknown",
            "steamos": "test-os", "kernel": "test-kernel",
        })
