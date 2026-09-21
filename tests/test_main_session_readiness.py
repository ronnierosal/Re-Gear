"""Exercise session diagnostics through the real plugin observation producer."""

import types
import unittest
from dataclasses import replace
from unittest.mock import patch

from tests.test_main_process_delivery import load_main_module
from tests.test_automatic_dock import current
from regear.application.connection_readiness import ConnectionReadinessLifecycle
from regear.domain.models import Confidence


class MainSessionReadinessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_main_module()
        self.plugin = self.module.Plugin()
        self.now = 0.0
        self.lifecycle = ConnectionReadinessLifecycle(lambda: self.now)
        self.observations = []

        def update(observation):
            self.observations.append(observation)
            return self.lifecycle.update(observation)

        self.plugin._connection_readiness = types.SimpleNamespace(update=update)
        self.topology = types.SimpleNamespace(
            transport_identity="transport", transport_present=True,
            transport_absent_verified=False, g1_identity="gpu", pci_complete=True,
            driver_ready=True, link_applicable=True, hdmi_ready=True,
        )
        self.plugin._connection_topology = types.SimpleNamespace(observe=lambda: self.topology)
        self.plugin._append_journey_event = lambda **event: None

    async def observe(self, running, confidence=Confidence.VERIFIED, *, audio=True, setup=True,
                      resolved=True):
        base = current("connected-internal.json")
        value = replace(base, observation_id=f"sample-{len(self.observations)}", snapshot=replace(
            base.snapshot, gamescope=replace(base.snapshot.gamescope,
                                             running=running, confidence=confidence)))
        self.plugin._audio_readiness_service = lambda: types.SimpleNamespace(
            observe_before_display=lambda _: types.SimpleNamespace(ready=audio, code="audio.test"))
        with patch.object(self.module, "GamescopeDiscovery", return_value=types.SimpleNamespace(scan=lambda: None)), \
             patch.object(self.module, "resolve_gamescope_user", return_value=types.SimpleNamespace(
                 ok=resolved, context=object() if resolved else None)), \
             patch.object(self.module, "GamescopeIntegrationStore", return_value=types.SimpleNamespace(
                 status=lambda: types.SimpleNamespace(ready=setup))):
            return await self.plugin._observe_connection_readiness(value)

    async def test_verified_stopped_precedes_audio_and_setup_even_after_timeout(self):
        for _ in range(4):
            result = await self.observe(False, resolved=False)
        self.now = 120.0
        result = await self.observe(False, resolved=False)
        self.assertEqual(result.code, "connection.session_unavailable")
        self.assertIs(self.observations[-1].session_available, False)
        self.assertFalse(self.observations[-1].session_ready)

    async def test_topology_failure_keeps_priority_over_verified_stopped(self):
        self.topology.driver_ready = False
        result = await self.observe(False)
        self.assertEqual(result.code, "connection.waiting_for_driver")

    async def test_running_resumes_audio_setup_and_ready_checks(self):
        await self.observe(False)
        result = await self.observe(True, audio=False)
        self.assertEqual(result.code, "connection.waiting_for_audio")
        self.assertIs(self.observations[-1].session_available, True)
        result = await self.observe(True, setup=False)
        self.assertFalse(self.observations[-1].session_ready)
        self.assertEqual(result.code, "connection.waiting_for_session")
        await self.observe(True, setup=False)
        self.now = 120.0
        result = await self.observe(True, setup=False)
        self.assertEqual(result.code, "connection.session_integration_unprepared")
        for _ in range(4):
            result = await self.observe(True)
        self.assertEqual(result.code, "connection.ready_idle")

    async def test_unknown_unverified_and_failed_discovery_never_attest_stopped(self):
        for running, confidence in (
            (None, Confidence.VERIFIED), (False, Confidence.UNKNOWN),
            (False, Confidence.OBSERVED), (True, Confidence.UNKNOWN),
            (True, Confidence.OBSERVED), (None, Confidence.UNKNOWN),
        ):
            with self.subTest(running=running, confidence=confidence):
                result = await self.observe(running, confidence, resolved=False)
                self.assertIsNone(self.observations[-1].session_available)
                self.assertFalse(self.observations[-1].session_ready)
                self.assertNotEqual(result.code, "connection.session_unavailable")

    async def test_failed_discovery_does_not_override_verified_running(self):
        result = await self.observe(True, resolved=False)
        self.assertIs(self.observations[-1].session_available, True)
        self.assertFalse(self.observations[-1].session_ready)
        self.assertNotEqual(result.code, "connection.session_unavailable")

    async def test_setup_success_does_not_verify_unknown_session(self):
        await self.observe(True, Confidence.OBSERVED, setup=True)
        self.assertIsNone(self.observations[-1].session_available)
        self.assertFalse(self.observations[-1].session_ready)


if __name__ == "__main__":
    unittest.main()
