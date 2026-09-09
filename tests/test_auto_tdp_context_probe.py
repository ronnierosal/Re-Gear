import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_tdp_control as fixtures
from hdm.adapters.steamos.auto_tdp_host import AutoTdpHostContext

spec = importlib.util.spec_from_file_location("auto_tdp_context_probe", Path(__file__).resolve().parents[1] / "scripts/probe_auto_tdp_context.py")
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


class AutoTdpContextProbeTests(unittest.TestCase):
    def setUp(self):
        self.provider, self.host = Mock(), Mock()
        self.provider.observe.return_value = SimpleNamespace(reading=fixtures.reading())
        self.host.observe.return_value = AutoTdpHostContext("auto_tdp.host_context_observed", "a" * 64)

    def test_stable_read_only_observation_exports_key_without_admission(self):
        result = probe_module.probe(self.provider, self.host)
        self.assertEqual(result["host_context_key"], "a" * 64)
        self.assertFalse(result["authorizes_control"])
        self.assertEqual([call[0] for call in self.provider.mock_calls], ["observe", "observe"])

    def test_changed_reading_or_host_context_never_exports_key(self):
        self.provider.observe.side_effect = [SimpleNamespace(reading=fixtures.reading()), SimpleNamespace(reading=fixtures.reading(20, 20, 20))]
        self.assertIsNone(probe_module.probe(self.provider, self.host)["host_context_key"])
        self.provider.observe.side_effect = None
        self.host.observe.side_effect = [AutoTdpHostContext("observed", "a" * 64), AutoTdpHostContext("observed", "b" * 64)]
        self.assertIsNone(probe_module.probe(self.provider, self.host)["host_context_key"])

    def test_missing_reading_and_private_exceptions_are_categorical(self):
        self.provider.observe.return_value = SimpleNamespace(reading=None)
        self.assertIsNone(probe_module.probe(self.provider, self.host)["host_context_key"])
        self.provider.observe.side_effect = OSError("private path and address")
        self.assertNotIn("private", str(probe_module.probe(self.provider, self.host)))

    def test_default_provider_does_not_claim_writer_ownership(self):
        with patch.object(probe_module, "SteamOsManagerTdpProvider", return_value=self.provider) as factory:
            probe_module.probe(host=self.host)
            self.assertEqual(set(factory.call_args.kwargs), {"user_resolver"})
