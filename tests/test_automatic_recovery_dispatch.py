"""No-hardware reproduction: expected guard fails on audited main 05a8aca."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
from tests.test_main_link_recovery import (
    load_main_module,
    observation,
    status,
    GameState,
)
from tests.test_link_recovery_service import FakeCommands, USER, RESTART, service
from regear.application.automatic_link_recovery import AutomaticLinkRecovery

import unittest


class AutomaticRecoveryDispatchTests(unittest.TestCase):
    def exercise_dispatch(self, game_state):
        module = load_main_module()
        plugin = module.Plugin.__new__(module.Plugin)
        plugin._unloading = False
        plugin._discovery = object()
        plugin._last_readiness_observation = observation(
            transport_identity="transport:known"
        )
        policy = plugin._automatic_link_recovery = AutomaticLinkRecovery()
        facts = dict(
            absent=False,
            present=True,
            identity="transport:known",
            pci_complete=False,
            enabled=True,
            idle=True,
        )
        policy.observe(now=0, **{**facts, "absent": True, "present": False})
        policy.observe(now=1, **facts)
        plugin._automatic_recovery_preferences = lambda: NS(load=lambda: True)
        plugin._automatic_dock_preferences = lambda: NS(load=lambda: True)
        plugin._transition_journal_service = lambda: NS(
            status=lambda: NS(durable=True, owner=NS(value="none"))
        )
        gpus = (
            NS(
                role=module.GpuRole.INTERNAL,
                present=True,
                confidence=module.Confidence.VERIFIED,
            ),
        )
        current = NS(
            snapshot=NS(
                game_state=GameState.IDLE, gamescope=NS(running=True), gpus=gpus
            )
        )

        async def observe(_):
            return status()

        async def background(fn):
            current.snapshot.game_state = game_state
            return fn()

        plugin._observe_connection_readiness = observe
        plugin._run_background_operation = background
        plugin._append_journey_event = lambda **kwargs: None
        commands = FakeCommands()
        plugin._link_recovery, _ = service(commands, [True])
        with (
            patch.object(module.time, "monotonic", return_value=11),
            patch.object(
                module, "resolve_runtime_profiles", return_value=NS(exact_host=True)
            ),
            patch.object(module, "GamescopeDiscovery"),
            patch.object(
                module, "resolve_gamescope_user", return_value=NS(ok=True, context=USER)
            ),
            patch.object(module, "SnapshotTransitionObservationAdapter") as adapter,
        ):
            adapter.return_value.observe.return_value = current
            result = asyncio.run(plugin._maybe_automatic_link_recovery(current, True))
        self.assertEqual(
            commands.calls, [RESTART] if game_state is GameState.IDLE else []
        )

    def test_game_start_at_dispatch_refuses_restart(self):
        self.exercise_dispatch(GameState.RUNNING)

    def test_unknown_game_at_dispatch_refuses_restart(self):
        self.exercise_dispatch(GameState.UNKNOWN)

    def test_idle_dispatch_preserves_recovery(self):
        self.exercise_dispatch(GameState.IDLE)
