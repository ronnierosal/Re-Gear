"""Production automatic loop coverage for a TV that becomes visible later.

Discovery, stores, and the mutation service are fake IO boundaries. The actual
plugin readiness producer, readiness lifecycle, and automatic coordinator run
on every sample; these tests make no hardware or display-success claim.
"""

import asyncio
import types
import unittest
from dataclasses import dataclass, replace
from unittest.mock import AsyncMock, patch

from tests.test_main_process_delivery import load_main_module
from tests.test_automatic_dock import current
from regear.application.connection_readiness import ConnectionReadinessLifecycle
from regear.application.presentation_completion import PresentationCompletion
from regear.domain.control_plane import TransitionOutcomeKind
from regear.domain.models import GameState


@dataclass(frozen=True)
class Reading:
    at: float
    hdmi: bool = True
    game: GameState = GameState.IDLE
    enabled: bool = True
    hold_portable: bool = False


class MainLateTvArrivalTests(unittest.IsolatedAsyncioTestCase):
    async def run_readings(self, readings, *, suppressed=False, execution_results=(), stable_tv=False):
        module = load_main_module()
        plugin = module.Plugin()
        index = 0
        observed = current("connected-internal.json")
        if stable_tv:
            observed = replace(observed, snapshot=replace(observed.snapshot,
                displays=tuple(replace(d, stable_id="display:0123456789abcdef")
                    if d.stable_id == "external-tv" else d for d in observed.snapshot.displays)))
        dispatches, stages, events = [], [], []
        plugin._connection_readiness = ConnectionReadinessLifecycle(
            lambda: readings[index].at
        )
        plugin._automatic_dock_preferences = lambda: types.SimpleNamespace(
            load=lambda: readings[index].enabled
        )
        plugin._automatic_recovery_preferences = lambda: types.SimpleNamespace(load=lambda: False)
        plugin._topology_wakeup = None
        plugin._append_journey_event = lambda **event: events.append(event)
        plugin._events = types.SimpleNamespace(append=lambda **event: events.append(event))
        plugin._update_saved_tv = AsyncMock()
        plugin._link_recovery_service = lambda: types.SimpleNamespace(observe_transport=lambda _: None)
        plugin._audio_handoff_service = lambda: types.SimpleNamespace(remember_portable=lambda _: None)
        plugin._audio_readiness_service = lambda: types.SimpleNamespace(
            observe_before_display=lambda _: types.SimpleNamespace(
                ready=readings[index].hdmi, code="audio.test"
            )
        )
        plugin._connection_topology = types.SimpleNamespace(observe=lambda: types.SimpleNamespace(
            transport_identity="same-transport", transport_present=True,
            transport_absent_verified=False, g1_identity="same-gpu", pci_complete=True,
            driver_ready=True, link_applicable=True, hdmi_ready=readings[index].hdmi,
        ))
        if suppressed:
            plugin._automatic_dock.suppress_current_attachment_after_portable_return()

        def observe():
            return replace(
                observed, observation_id=f"sample-{index}",
                snapshot=replace(observed.snapshot, game_state=readings[index].game),
            )

        def execute(target, **kwargs):
            dispatches.append((index, target, kwargs))
            if len(dispatches) <= len(execution_results):
                return execution_results[len(dispatches) - 1]
            return types.SimpleNamespace(
                outcome=types.SimpleNamespace(kind=TransitionOutcomeKind.SUCCEEDED),
                code="transition.succeeded", accepted=True,
            )

        plugin._presentation_transition_service = lambda: types.SimpleNamespace(
            reconcile_completion=lambda _: PresentationCompletion(
                "completion.test", hold_portable=readings[index].hold_portable
            ), execute_automatic=execute,
        )

        async def wait(_delay):
            nonlocal index
            stages.append(plugin._connection_readiness.status().code)
            index += 1
            if index == len(readings):
                raise asyncio.CancelledError

        plugin._wait_for_topology = wait
        with patch.object(module, "SnapshotTransitionObservationAdapter",
                          return_value=types.SimpleNamespace(observe=observe)), \
             patch.object(module, "GamescopeDiscovery",
                          return_value=types.SimpleNamespace(scan=lambda: None)), \
             patch.object(module, "resolve_gamescope_user", return_value=types.SimpleNamespace(
                 ok=True, context=object())), \
             patch.object(module, "GamescopeIntegrationStore", return_value=types.SimpleNamespace(
                 status=lambda: types.SimpleNamespace(ready=True))):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._automatic_dock_loop()
        self.assertFalse(any(event["code"] in {
            "connection.tv_transition_exception", "automatic_dock.observation_failed",
        } for event in events))
        # The loop catches observation exceptions. Check all producer samples so
        # a swallowed IO/mock failure cannot make a no-dispatch test pass.
        self.assertEqual(plugin._last_readiness_observation.sample_id, f"sample-{len(readings) - 1}")
        return dispatches, stages

    async def test_premutation_refusal_retries_once_through_production_dispatch(self):
        from regear.application.supervised_transition import SupervisedTransitionExecution
        refused = SupervisedTransitionExecution(False, "transition.evidence_changed")
        dispatches, _ = await self.run_readings([Reading(n) for n in range(8)],
            execution_results=(refused, refused), stable_tv=True)
        self.assertEqual([call[0] for call in dispatches], [3, 4])

    async def test_uncertain_or_started_execution_never_retries_through_loop(self):
        from regear.application.supervised_transition import SupervisedTransitionExecution
        for refused in (
            SupervisedTransitionExecution(False, "transition.evidence_changed", operation_id="started"),
            SupervisedTransitionExecution(False, "transition.observation_unavailable"),
        ):
            with self.subTest(code=refused.code, operation=refused.operation_id):
                dispatches, _ = await self.run_readings([Reading(n) for n in range(8)],
                    execution_results=(refused,), stable_tv=True)
                self.assertEqual([call[0] for call in dispatches], [3])

    async def test_absent_hdmi_past_deadline_then_arrival_dispatches_once(self):
        readings = [Reading(n, hdmi=False) for n in range(5)]
        readings += [Reading(600, hdmi=False), Reading(601), Reading(602), Reading(603)]
        dispatches, stages = await self.run_readings(readings)
        self.assertEqual(stages[5], "connection.ready_display_pending")
        self.assertNotIn("connection.readiness_timed_out", stages)
        self.assertEqual([call[0] for call in dispatches], [7])
        self.assertTrue(dispatches[0][2]["standing_consent"])

    async def test_late_display_waits_for_known_idle_after_running_or_unknown_game(self):
        for game in (GameState.RUNNING, GameState.UNKNOWN):
            with self.subTest(game=game):
                readings = [Reading(n, hdmi=False, game=game) for n in range(5)]
                readings += [Reading(600, game=game), Reading(601, game=game), Reading(602)]
                dispatches, stages = await self.run_readings(readings)
                self.assertEqual([call[0] for call in dispatches], [7])
                self.assertEqual(stages[6], "connection.game_running" if game is GameState.RUNNING
                                 else "connection.game_state_unknown")

    async def test_disabled_arrival_never_dispatches(self):
        readings = [Reading(n, hdmi=False, enabled=False) for n in range(5)]
        readings += [Reading(600 + n, enabled=False) for n in range(4)]
        dispatches, stages = await self.run_readings(readings)
        self.assertEqual(dispatches, [])
        self.assertEqual(stages[-1], "connection.ready_idle")

    async def test_disable_then_enable_rearms_consumed_attempt_without_physical_replug(self):
        readings = [Reading(n) for n in range(5)]
        readings += [Reading(5, enabled=False), Reading(6), Reading(7)]
        dispatches, _ = await self.run_readings(readings)
        self.assertEqual([call[0] for call in dispatches], [3, 6])

    async def test_intentional_portable_suppression_survives_late_tv_arrival(self):
        readings = [Reading(n, hdmi=False) for n in range(5)]
        readings += [Reading(600 + n) for n in range(4)]
        dispatches, stages = await self.run_readings(readings, suppressed=True)
        self.assertEqual(dispatches, [])
        self.assertEqual(stages[-1], "connection.ready_idle")

    async def test_durable_portable_hold_blocks_arrival_even_after_toggle(self):
        readings = [Reading(n, hold_portable=True) for n in range(5)]
        readings += [Reading(5, enabled=False, hold_portable=True),
                     Reading(6, hold_portable=True), Reading(7, hold_portable=True)]
        dispatches, stages = await self.run_readings(readings)
        self.assertEqual(dispatches, [])
        self.assertEqual(stages[-1], "connection.ready_idle")


if __name__ == "__main__":
    unittest.main()
