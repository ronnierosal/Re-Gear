import asyncio
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from test_main_process_delivery import load_main_module
import test_tdp_control as control_fixtures
from hdm.application.auto_tdp_session import AutoTdpSessionResult
from hdm.delivery.auto_tdp_configuration import AutoTdpConfiguration, AutoTdpConfigurationResult
from hdm.delivery.auto_tdp_evidence import AutoTdpEligibility
from hdm.delivery.auto_tdp_worker import AutoTdpWorkerStatus
from hdm.delivery.tdp_sensor_readiness import TdpSensorReadinessConfig
from hdm.domain.models import GameState
from hdm.domain.telemetry import TelemetryCollectionContract, TelemetryConsumer, TelemetryMetric


class Runtime:
    def __init__(self):
        self.auto_policy = None
        self.worker = None
        self.starts = []
        self.stops = 0
        self.manual = dict(ready=True, code="tdp.ready")

    def status(self):
        return self.manual

    def auto_context(self):
        return control_fixtures.reading()

    def auto_status(self):
        return self.worker

    def start_auto(self, policy, *, admission_guard=None):
        if admission_guard is not None and not admission_guard():
            return None
        self.starts.append(policy)
        self.auto_policy = policy
        self.worker = AutoTdpWorkerStatus(True, False, AutoTdpSessionResult("auto_tdp.started", True))
        return self.worker

    def stop_auto(self):
        self.stops += 1
        self.worker = AutoTdpWorkerStatus(False, False, AutoTdpSessionResult("auto_tdp.stopped", False))
        return self.worker

    def cancel_benchmark(self):
        pass


class MainAutoTdpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_main_module()

    def setUp(self):
        self.plugin = self.module.Plugin()
        self.runtime = Runtime()
        self.plugin._tdp_runtime = self.runtime
        self.plugin._tdp_service = lambda: self.runtime
        self.config = AutoTdpConfiguration("a" * 64,
            TdpSensorReadinessConfig("Tctl", "cooling_control_value", 80, 2), "synthetic-thermal",
            TelemetryCollectionContract(TelemetryConsumer.AUTO_TDP, (TelemetryMetric.FPS,), 1000, 5, True),
            "synthetic-benchmark")
        self.plugin._auto_configuration = lambda: AutoTdpConfigurationResult("auto_tdp.configuration_loaded", self.config)
        self.plugin._auto_eligibility = lambda: AutoTdpEligibility(GameState.RUNNING, True)
        host = patch.object(self.module, "AutoTdpHostDiscovery")
        self.host = host.start()
        self.addCleanup(host.stop)
        self.host.return_value.observe.return_value = SimpleNamespace(context_key="a" * 64)

    def test_status_is_read_only_and_start_forwards_policy_then_stop_revokes(self):
        status = asyncio.run(self.plugin.get_auto_tdp_status())
        self.assertTrue(status["can_start"])
        self.assertFalse(status["enabled"])
        self.assertEqual(self.runtime.starts, [])
        status = asyncio.run(self.plugin.start_auto_tdp(60, 7, 30))
        self.assertTrue(status["enabled"])
        self.assertFalse(status["can_start"])
        self.assertEqual(status["target_fps"], 60)
        self.assertEqual(self.runtime.starts[0].maximum_watts, 30)
        stopped = asyncio.run(self.plugin.stop_auto_tdp())
        self.assertFalse(stopped["enabled"])
        self.assertEqual(self.runtime.stops, 1)

    def test_missing_configuration_never_constructs_runtime(self):
        self.plugin._tdp_runtime = None
        self.plugin._auto_configuration = lambda: AutoTdpConfigurationResult("auto_tdp.configuration_missing")
        self.plugin._tdp_service = lambda: self.fail("must not construct")
        result = asyncio.run(self.plugin.get_auto_tdp_status())
        self.assertEqual(result["code"], "auto_tdp.configuration_missing")
        self.assertFalse(result["can_start"])

    def test_manual_ownership_benchmark_host_and_game_requirements_are_exposed(self):
        self.runtime.manual = dict(ready=False, code="tdp.disabled")
        self.assertEqual(asyncio.run(self.plugin.get_auto_tdp_status())["code"], "tdp.disabled")
        self.runtime.manual = dict(ready=True, code="tdp.ready")
        self.config = replace(self.config, collection_contract=replace(self.config.collection_contract, benchmarked=False))
        self.assertEqual(asyncio.run(self.plugin.get_auto_tdp_status())["code"], "telemetry.collection_cost_unbenchmarked")
        self.config = replace(self.config, collection_contract=replace(self.config.collection_contract, benchmarked=True))
        self.host.return_value.observe.return_value = SimpleNamespace(context_key="b" * 64)
        self.assertEqual(asyncio.run(self.plugin.get_auto_tdp_status())["code"], "auto_tdp.configuration_context_changed")
        self.plugin._auto_eligibility = lambda: AutoTdpEligibility(GameState.UNKNOWN, False)
        self.assertEqual(asyncio.run(self.plugin.get_auto_tdp_status())["code"], "auto_tdp.game_or_render_unverified")
        self.assertEqual(self.runtime.starts, [])

    def test_invalid_requests_and_closing_cannot_start(self):
        for args in ((float("nan"), 7, 30), (60, True, 30), (60, 30, 7)):
            self.assertEqual(asyncio.run(self.plugin.start_auto_tdp(*args))["code"], "auto_tdp.request_invalid")
        self.plugin._tdp_closing.set()
        self.assertEqual(asyncio.run(self.plugin.start_auto_tdp(60, 7, 30))["code"], "auto_tdp.closing")
        self.assertEqual(self.runtime.starts, [])

    def test_stop_does_not_need_configuration_and_errors_are_redacted(self):
        def fail():
            raise OSError("private path and address")
        self.plugin._auto_configuration = fail
        self.assertEqual(asyncio.run(self.plugin.get_auto_tdp_status())["code"], "auto_tdp.runtime_unavailable")
        self.assertEqual(asyncio.run(self.plugin.stop_auto_tdp())["code"], "auto_tdp.stopped")

    def test_stop_and_manual_intent_cancel_a_start_waiting_on_readiness(self):
        for action in ("stop", "apply", "restore", "disable"):
            with self.subTest(action=action):
                entered, release = threading.Event(), threading.Event()
                def readiness():
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError("test readiness release missing")
                    return dict(can_start=True)
                self.plugin._auto_tdp_status_sync = readiness
                async def manual(*args):
                    return {}
                self.plugin._tdp_call = manual
                responses = []
                thread = threading.Thread(target=lambda: responses.append(asyncio.run(self.plugin.start_auto_tdp(60, 7, 30))))
                thread.start()
                try:
                    self.assertTrue(entered.wait(1))
                    request = {"stop": self.plugin.stop_auto_tdp, "apply": lambda: self.plugin.apply_tdp_limit(20),
                               "restore": self.plugin.restore_tdp_limit, "disable": lambda: self.plugin.set_tdp_enabled(False)}[action]
                    asyncio.run(request())
                finally:
                    release.set()
                    thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(responses[0]["code"], "auto_tdp.stopped")
                self.assertEqual(self.runtime.starts, [])

    def test_factory_uses_loaded_configuration_and_cancellation_aware_eligibility(self):
        with patch.object(self.module, "AutoTdpSessionFactory") as factory:
            self.plugin._auto_session("actuator", "provider")
            kwargs = factory.call_args.kwargs
            self.assertEqual(kwargs["host_context_key"], self.config.host_context_key)
            self.assertFalse(kwargs["eligibility"]().ready)
            self.plugin._auto_cancel_requested.clear()
            self.assertTrue(kwargs["eligibility"]().ready)
            factory.return_value.assert_called_once_with("actuator", "provider")

    def test_old_start_cannot_revive_or_stop_newer_start_after_stop(self):
        entered, release = threading.Event(), threading.Event()
        self.plugin._auto_tdp_status_sync = lambda: dict(can_start=True)
        count = 0
        def service():
            nonlocal count
            count += 1
            if count == 1:
                entered.set()
                if not release.wait(2):
                    raise TimeoutError("test service release missing")
            return self.runtime
        self.plugin._tdp_service = service
        responses = []
        thread = threading.Thread(target=lambda: responses.append(asyncio.run(self.plugin.start_auto_tdp(60, 7, 30))))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            asyncio.run(self.plugin.stop_auto_tdp())
            asyncio.run(self.plugin.start_auto_tdp(45, 7, 30))
        finally:
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual([policy.target_fps for policy in self.runtime.starts], [45])
        self.assertEqual(self.runtime.stops, 1)
        self.assertTrue(self.runtime.worker.running)
        self.assertEqual(responses[0]["code"], "auto_tdp.start_unavailable")
