import asyncio
import types
import unittest
from unittest.mock import patch

from tests.test_main_process_delivery import load_main_module
from tests.test_automatic_dock import current, readiness
from hdm.application.attach_readiness import AttachReadinessStage
from hdm.application.attach_readiness import AttachReadinessStatus
from hdm.application.presentation_completion import PresentationCompletion
from hdm.domain.control_plane import TransitionOutcomeKind


class Monitor:
    def __init__(self, available=True):
        self.available = available
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

    async def run_iteration(self, *, hold=False, stage=AttachReadinessStage.READY_IDLE, available=True):
        plugin = self.module.Plugin()
        plugin._topology_wakeup = Monitor(available)
        plugin._automatic_dock_preferences = lambda: types.SimpleNamespace(load=lambda: True)
        observed = current("connected-internal.json")
        plugin._record_topology_observation = lambda _: AttachReadinessStatus(
            stage, "attach.test", 250 if stage is AttachReadinessStage.SETTLING else 1000
        )
        calls = []
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
        calls, waits = await self.run_iteration(stage=AttachReadinessStage.SETTLING)
        self.assertEqual(calls, [])
        self.assertEqual(waits, [0.25])

    async def test_actual_wait_forwards_timeout_and_unload_closes_listener(self):
        plugin = self.module.Plugin()
        monitor = plugin._topology_wakeup = Monitor()
        await plugin._wait_for_topology(5.0)
        self.assertEqual(monitor.waits, [5.0])
        plugin._sleep_guard = types.SimpleNamespace(close=lambda: types.SimpleNamespace(active=False, error=""))
        await plugin._unload()
        self.assertTrue(monitor.closed)
        self.assertIsNone(plugin._topology_wakeup)

    async def test_game_running_never_executes(self):
        calls, waits = await self.run_iteration(stage=AttachReadinessStage.GAME_RUNNING)
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
