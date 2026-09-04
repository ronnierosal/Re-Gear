import asyncio
import threading
import types
import unittest
from dataclasses import replace
from unittest.mock import patch

from tests.test_main_process_delivery import load_main_module
from tests.test_automatic_dock import current, readiness
from hdm.application.attach_readiness import AttachReadinessStage
from hdm.application.attach_readiness import AttachReadinessStatus
from hdm.application.connection_readiness import (
    ConnectionReadinessStage,
    ConnectionReadinessStatus,
)
from hdm.application.presentation_completion import PresentationCompletion
from hdm.domain.control_plane import TransitionOutcomeKind
from hdm.domain.models import Confidence, EgpuLinkState


class Monitor:
    def __init__(self, available=True):
        self.available = available
        self.last_wake_source = "kernel_event"
        self.invalidations = 0
        self.closed = False
        self.waits = []

    def invalidate(self):
        self.invalidations += 1

    def close(self):
        self.closed = True

    async def wait(self, delay):
        self.waits.append(delay)
        return True


class MainEventCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = load_main_module()

    def test_exact_observed_up_link_satisfies_readiness_gate(self):
        observed = current("connected-internal.json")
        snapshot = replace(
            observed.snapshot,
            egpu_link=replace(
                observed.snapshot.egpu_link,
                applicable=True,
                state=EgpuLinkState.UP,
                confidence=Confidence.OBSERVED,
            ),
        )
        self.assertTrue(self.module._exact_g1_link_is_up(snapshot))
        self.assertFalse(
            self.module._exact_g1_link_is_up(
                replace(
                    snapshot,
                    egpu_link=replace(snapshot.egpu_link, state=EgpuLinkState.DOWN),
                )
            )
        )

    async def test_blocked_transition_factory_keeps_event_loop_responsive(self):
        plugin = self.module.Plugin()
        plugin._automatic_dock_preferences = lambda: types.SimpleNamespace(load=lambda: False)
        observed = current("connected-internal.json")
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()
        entered = threading.Event()
        release = threading.Event()
        heartbeat = threading.Event()
        evidence = {}

        def blocked_factory():
            evidence["factory_on_event_loop"] = threading.get_ident() == loop_thread
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test factory was not released")
            raise ValueError("injected unavailable Gamescope scan")

        def probe():
            if entered.wait(2):
                loop.call_soon_threadsafe(heartbeat.set)
                evidence["heartbeat_during_factory"] = heartbeat.wait(0.5)
            release.set()

        async def stop_after_iteration(_delay):
            raise asyncio.CancelledError

        plugin._presentation_transition_service = blocked_factory
        plugin._wait_for_topology = stop_after_iteration
        probe_thread = threading.Thread(target=probe)
        probe_thread.start()
        try:
            with patch.object(
                self.module, "SnapshotTransitionObservationAdapter",
                return_value=types.SimpleNamespace(observe=lambda: observed),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await plugin._automatic_dock_loop()
        finally:
            release.set()
            await asyncio.to_thread(probe_thread.join, 2)
        self.assertFalse(probe_thread.is_alive())
        self.assertFalse(evidence["factory_on_event_loop"])
        self.assertTrue(evidence["heartbeat_during_factory"])

    async def run_iteration(self, *, hold=False, stage=ConnectionReadinessStage.READY_IDLE, available=True):
        plugin = self.module.Plugin()
        plugin._topology_wakeup = Monitor(available)
        plugin._automatic_dock_preferences = lambda: types.SimpleNamespace(load=lambda: True)
        observed = current("connected-internal.json")
        async def observe_connection(_current):
            return ConnectionReadinessStatus(
                stage, "connection.test",
                500 if stage is ConnectionReadinessStage.STABILIZING else 1000,
            )
        plugin._observe_connection_readiness = observe_connection
        calls = []
        events = []
        plugin._append_journey_event = lambda **event: events.append(event)
        plugin._connection_wake_source = "local_change"
        def execute(*args, **kwargs):
            calls.append("execute")
            return types.SimpleNamespace(
                outcome=types.SimpleNamespace(kind=TransitionOutcomeKind.SUCCEEDED),
                code="transition.succeeded", accepted=True,
            )
        service = types.SimpleNamespace(
            reconcile_completion=lambda _: PresentationCompletion("completion.test", hold_portable=hold),
            execute_automatic=execute,
        )
        plugin._presentation_transition_service = lambda: service
        waits = []
        async def wait(delay):
            waits.append(delay)
            raise asyncio.CancelledError
        plugin._wait_for_topology = wait
        with patch.object(self.module, "SnapshotTransitionObservationAdapter", return_value=types.SimpleNamespace(observe=lambda: observed)):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._automatic_dock_loop()
        if calls:
            self.assertTrue(any(
                event["code"] == "observation.wake.local_change"
                and event["stage"] == "automatic_transition_observation"
                for event in events
            ))
        return calls, waits

    async def test_durable_portable_hold_prevents_automatic_execute(self):
        calls, waits = await self.run_iteration(hold=True)
        self.assertEqual(calls, [])
        self.assertEqual(waits, [5.0])

    async def test_ready_event_path_uses_existing_execute_once(self):
        calls, waits = await self.run_iteration()
        self.assertEqual(calls, ["execute"])
        self.assertEqual(waits, [5.0])

    async def test_unavailable_events_retain_polling_and_settling_remains_fast(self):
        _, waits = await self.run_iteration(available=False)
        self.assertEqual(waits, [1.0])
        calls, waits = await self.run_iteration(stage=ConnectionReadinessStage.STABILIZING)
        self.assertEqual(calls, [])
        self.assertEqual(waits, [0.5])

    async def test_actual_wait_forwards_timeout_and_unload_closes_listener(self):
        plugin = self.module.Plugin()
        monitor = plugin._topology_wakeup = Monitor()
        await plugin._wait_for_topology(5.0)
        self.assertEqual(monitor.waits, [5.0])
        plugin._sleep_guard = types.SimpleNamespace(close=lambda: types.SimpleNamespace(active=False, error=""))
        await plugin._unload()
        self.assertTrue(monitor.closed)
        self.assertIsNone(plugin._topology_wakeup)

    async def test_wake_cause_reaches_transition_diagnostics(self):
        plugin = self.module.Plugin()
        monitor = plugin._topology_wakeup = Monitor()
        events = []
        plugin._append_journey_event = lambda **event: events.append(event)
        for source in ("kernel_event", "local_change", "kernel_and_local",
                       "poll_timer", "observer_degraded"):
            monitor.last_wake_source = source
            await plugin._wait_for_topology(1)
            plugin._record_connection_wake("automatic_transition_observation")
            self.assertEqual(events[-1]["code"], "observation.wake." + source)
            self.assertEqual(events[-1]["stage"], "automatic_transition_observation")

    async def test_game_running_never_executes(self):
        calls, waits = await self.run_iteration(stage=ConnectionReadinessStage.GAME_RUNNING)
        self.assertEqual(calls, [])
        self.assertEqual(waits, [5.0])

    async def test_preference_change_invalidates_monitor(self):
        plugin = self.module.Plugin()
        monitor = plugin._topology_wakeup = Monitor()
        plugin._automatic_dock_preferences = lambda: types.SimpleNamespace(save=lambda _: None)
        await plugin.set_automatic_dock_enabled(True, True)
        self.assertEqual(monitor.invalidations, 1)


if __name__ == "__main__":
    unittest.main()
