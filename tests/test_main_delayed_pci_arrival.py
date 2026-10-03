"""Replay old issue #17 through production observation/readiness/dispatch.

The 148.2s and 230s arrivals use historical transport timing anchors, not a
hardware simulator or a diagnosis of the delay. Discovery and device mutation
are fake IO; the snapshot identity adapter and plugin caller chain are real.
"""

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
import subprocess
import unittest
from unittest.mock import AsyncMock, patch

from tests.test_automatic_dock import current
from tests.test_main_process_delivery import load_main_module
from regear.adapters.transition_runtime import versioned_snapshot_observation
from regear.application.connection_readiness import ConnectionReadinessLifecycle
from regear.application.presentation_completion import PresentationCompletion
from regear.application.supervised_transition import SupervisedTransitionExecution
from regear.domain.control_plane import PlacementState, TransitionOutcome, TransitionOutcomeKind, WorkflowState
from regear.domain.models import GameState, GpuRole


@dataclass(frozen=True)
class Reading:
    at: float
    pci: bool = False
    driver: bool = True
    game: GameState = GameState.IDLE
    enabled: bool = True
    # A repeated discovery timestamp with unchanged facts is the same sample.
    sample_at: float | None = None


def delayed_arrival(at=148.2):
    return [Reading(0), Reading(119.9), Reading(120.4), Reading(at, pci=True)]


class MainDelayedPciArrivalTests(unittest.IsolatedAsyncioTestCase):
    async def journey(self, readings):
        module = load_main_module()
        plugin = module.Plugin()
        index = 0
        attached = current("connected-internal.json").snapshot
        epoch = datetime(2026, 9, 11, tzinfo=timezone.utc)
        collected, dispatches, statuses, events = [], [], [], []

        def snapshot(reading):
            stamp = reading.at if reading.sample_at is None else reading.sample_at
            return replace(
                attached,
                observed_at=(epoch + timedelta(seconds=stamp)).isoformat(),
                game_state=reading.game,
                gpus=attached.gpus if reading.pci else tuple(
                    gpu for gpu in attached.gpus if gpu.role is GpuRole.INTERNAL
                ),
            )

        def collect():
            value = snapshot(readings[index])
            collected.append(versioned_snapshot_observation(value))
            return value

        def topology():
            reading = readings[index]
            return NS(
                transport_identity="same-transport", transport_present=True,
                transport_absent_verified=False,
                g1_identity="same-gpu" if reading.pci else "",
                pci_complete=reading.pci, driver_ready=reading.pci and reading.driver,
                link_applicable=reading.pci, hdmi_ready=reading.pci,
            )

        def execute(target, *, expected_generation, standing_consent):
            self.assertIs(target, PlacementState.DOCKED_EGPU)
            self.assertTrue(standing_consent)
            self.assertEqual(expected_generation, collected[-1].generation)
            dispatches.append(index)
            return SupervisedTransitionExecution(
                True, "transition.succeeded", "fixture-operation",
                TransitionOutcome(TransitionOutcomeKind.SUCCEEDED,
                                  PlacementState.DOCKED_EGPU, WorkflowState.IDLE),
                True,
            )

        async def wait(_delay):
            nonlocal index
            statuses.append(plugin._connection_readiness.status())
            # The loop catches observation errors; no-dispatch alone is weak.
            self.assertEqual(plugin._last_readiness_observation.sample_id,
                             versioned_snapshot_observation(snapshot(readings[index])).sample_id)
            index += 1
            if index == len(readings):
                raise asyncio.CancelledError

        plugin._discovery = NS(collect_snapshot=collect)
        plugin._connection_topology = NS(observe=topology)
        plugin._connection_readiness = ConnectionReadinessLifecycle(lambda: readings[index].at)
        plugin._automatic_dock_preferences = lambda: NS(load=lambda: readings[index].enabled)
        plugin._automatic_recovery_preferences = lambda: NS(load=lambda: False)
        plugin._link_recovery_service = lambda: NS(observe_transport=lambda _: None)
        plugin._topology_wakeup = None
        plugin._append_journey_event = lambda **event: events.append(event)
        plugin._events = NS(append=lambda **event: events.append(event))
        plugin._audio_handoff_service = lambda: NS(remember_portable=lambda _: None)
        plugin._audio_readiness_service = lambda: NS(observe_before_display=lambda _: NS(
            ready=readings[index].pci, code="audio.fixture"))
        plugin._presentation_transition_service = lambda: NS(
            reconcile_completion=lambda _: PresentationCompletion("completion.fixture"),
            execute_automatic=execute,
        )
        plugin._update_saved_tv = AsyncMock()
        plugin._wait_for_topology = wait
        # Keep _observe_connection_readiness, the coordinator and
        # _run_automatic_tv_transition real. Only external IO is substituted.
        with patch.object(module, "GamescopeDiscovery", return_value=NS(scan=lambda: None)), \
             patch.object(module, "resolve_gamescope_user", return_value=NS(ok=True, context=object())), \
             patch.object(module, "GamescopeIntegrationStore", return_value=NS(
                 status=lambda: NS(ready=True))), \
             patch.object(subprocess, "run", side_effect=AssertionError("unexpected OS command")):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._automatic_dock_loop()
        self.assertEqual(len(collected), len(readings))
        self.assertEqual(plugin._update_saved_tv.await_count, len(readings))
        self.assertFalse(any(event["code"] in {
            "automatic_dock.observation_failed", "connection.tv_transition_exception",
            "automatic_recovery.observation_failed",
        } for event in events))
        return dispatches, statuses, collected

    async def test_historical_transport_delays_recover_and_dispatch_once(self):
        for arrival in (148.2, 230.0):
            with self.subTest(transport_to_pci_seconds=arrival):
                readings = delayed_arrival(arrival)
                readings += [Reading(arrival + offset, pci=True)
                             for offset in (1, 2, 3, 4.6, 5.6, 200)]
                calls, statuses, collected = await self.journey(readings)
                self.assertEqual(statuses[2].code, "connection.readiness_timed_out")
                self.assertEqual(statuses[3].code, "connection.late_enumeration_detected")
                self.assertEqual(statuses[3].window_age_ms, 0)
                self.assertEqual(statuses[3].topology_samples, 0)
                self.assertEqual(calls, [7])
                self.assertEqual(statuses[-1].code, "connection.ready_idle")
                self.assertNotIn("connection.readiness_timed_out",
                                 [status.code for status in statuses[3:]])
                # Fresh scans of unchanged semantics must contribute quorum.
                self.assertEqual(collected[3].generation, collected[7].generation)
                self.assertNotEqual(collected[3].sample_id, collected[7].sample_id)

    async def test_duplicate_discovery_samples_cannot_settle_late_enumeration(self):
        readings = delayed_arrival()
        readings += [Reading(149, pci=True)]
        readings += [Reading(at, pci=True, sample_at=149) for at in (150, 151, 152)]
        readings += [Reading(at, pci=True) for at in (153, 154, 155, 156)]
        calls, statuses, collected = await self.journey(readings)
        self.assertEqual(len({value.sample_id for value in collected[4:8]}), 1)
        self.assertEqual([status.topology_samples for status in statuses[4:8]], [1] * 4)
        self.assertEqual(calls, [10])

    async def test_late_enumeration_waits_for_known_idle_game(self):
        for game in (GameState.RUNNING, GameState.UNKNOWN):
            with self.subTest(game=game):
                readings = delayed_arrival()
                readings += [Reading(at, pci=True, game=game)
                             for at in (149, 150, 151, 152, 300)]
                readings += [Reading(301, pci=True), Reading(302, pci=True)]
                calls, statuses, _ = await self.journey(readings)
                self.assertEqual(calls, [9])
                self.assertEqual(statuses[8].code, "connection.game_running"
                                 if game is GameState.RUNNING else "connection.game_state_unknown")

    async def test_unsettled_driver_cannot_renew_late_enumeration_deadline(self):
        readings = delayed_arrival()
        readings += [Reading(at, pci=True, driver=False) for at in (149, 267, 268.2, 300)]
        readings += [Reading(at, pci=True) for at in (301, 302, 303, 304)]
        calls, statuses, _ = await self.journey(readings)
        self.assertEqual(calls, [])
        self.assertEqual(statuses[5].code, "connection.waiting_for_driver")
        self.assertTrue(all(status.code == "connection.readiness_timed_out"
                            for status in statuses[6:]))
        self.assertGreater(statuses[-1].window_age_ms, 120_000)

    async def test_disabled_auto_docking_still_observes_late_recovery_without_dispatch(self):
        readings = delayed_arrival() + [Reading(at, pci=True) for at in (149, 150, 151, 152, 300)]
        calls, statuses, _ = await self.journey([replace(reading, enabled=False) for reading in readings])
        self.assertEqual(calls, [])
        self.assertEqual(statuses[-1].code, "connection.ready_idle")


if __name__ == "__main__":
    unittest.main()
