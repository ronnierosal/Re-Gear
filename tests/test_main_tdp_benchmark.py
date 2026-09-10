import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_main_process_delivery import load_main_module
from hdm.delivery.auto_tdp_configuration import AutoTdpConfigurationResult


class MainTdpBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module()

    def setUp(self):
        self.plugin = self.module.Plugin()
        self.config = SimpleNamespace(collection_contract=SimpleNamespace(interval_ms=1500, benchmarked=False))
        self.plugin._auto_configuration = lambda: AutoTdpConfigurationResult("auto_tdp.configuration_loaded", self.config)
        self.plugin._auto_eligibility = lambda: SimpleNamespace(ready=True)

    def test_status_and_cancel_do_not_construct_or_read_configuration(self):
        self.plugin._tdp_service = Mock(side_effect=AssertionError("must not construct"))
        self.plugin._auto_configuration = Mock(side_effect=AssertionError("must not read"))
        for request in (self.plugin.get_auto_tdp_benchmark_status, self.plugin.cancel_auto_tdp_benchmark):
            result = asyncio.run(request())
            self.assertEqual(result["code"], "auto_tdp.benchmark_idle")
            self.assertFalse(result["running"])

    def test_missing_configuration_and_unknown_game_do_not_construct(self):
        self.plugin._tdp_service = Mock(side_effect=AssertionError("must not construct"))
        self.plugin._auto_eligibility = lambda: SimpleNamespace(ready=False)
        self.assertEqual(asyncio.run(self.plugin.run_auto_tdp_benchmark())["code"], "auto_tdp.game_or_render_unverified")
        self.plugin._auto_configuration = lambda: AutoTdpConfigurationResult("auto_tdp.configuration_missing")
        self.assertEqual(asyncio.run(self.plugin.run_auto_tdp_benchmark())["code"], "auto_tdp.configuration_missing")
        self.plugin._tdp_service.assert_not_called()

    def test_unbenchmarked_configuration_uses_same_factory_without_actuator(self):
        cancel = threading.Event()
        runtime = Mock()
        runtime.run_benchmark.side_effect = lambda operation, admission_guard: operation("provider", cancel) if admission_guard() else None
        self.plugin._tdp_service = lambda: runtime
        with patch.object(self.plugin, "_configured_auto_factory") as factory, patch.object(self.module, "benchmark_auto_tdp") as measure:
            measure.return_value = {"code": "measured"}
            result = asyncio.run(self.plugin.run_auto_tdp_benchmark())
            self.assertEqual(result, {"code": "measured"})
            factory.assert_called_once_with(self.config, self.plugin._auto_eligibility)
            factory.return_value.create_evidence.assert_called_once_with("provider")
            factory.return_value.assert_not_called()
            measure.assert_called_once_with(factory.return_value.create_evidence.return_value, cancel=cancel, interval_ms=1500)
        runtime.start_auto.assert_not_called()

    def test_cancel_revokes_request_during_setup_without_stopping_auto(self):
        runtime = Mock()
        runtime.benchmark_status.return_value = {"code": "cancelled"}
        self.plugin._tdp_runtime = runtime
        def service():
            asyncio.run(self.plugin.cancel_auto_tdp_benchmark())
            return runtime
        self.plugin._tdp_service = service
        def run(operation, admission_guard):
            self.assertFalse(admission_guard())
            return {"code": "cancelled"}
        runtime.run_benchmark.side_effect = run
        self.assertEqual(asyncio.run(self.plugin.run_auto_tdp_benchmark())["code"], "cancelled")
        runtime.cancel_benchmark.assert_called_once()
        runtime.stop_auto.assert_not_called()

    def test_configuration_errors_are_redacted(self):
        self.plugin._auto_configuration = Mock(side_effect=OSError("private host and path"))
        result = asyncio.run(self.plugin.run_auto_tdp_benchmark())
        self.assertEqual(result["code"], "auto_tdp.benchmark_unavailable")
        self.assertNotIn("private", str(result))
