"""Preserve automatic recovery while refusing stale dispatch authority."""

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
    def exercise_dispatch(self, game_state, change=None):
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
        consent = {"recovery": True, "docking": True}
        plugin._automatic_recovery_preferences = lambda: NS(
            load=lambda: consent["recovery"]
        )
        plugin._automatic_dock_preferences = lambda: NS(load=lambda: consent["docking"])
        journal = NS(durable=True, owner=NS(value="none"))
        plugin._transition_journal_service = lambda: NS(status=lambda: journal)
        topology = NS(
            transport_identity="transport:known",
            transport_present=True,
            pci_complete=False,
        )
        plugin._connection_topology = NS(observe=lambda: topology)
        resolution = NS(ok=True, context=USER)
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
            if change == "recovery_disabled":
                consent["recovery"] = False
            if change == "docking_disabled":
                consent["docking"] = False
            if change == "non_boolean_consent":
                consent["recovery"] = 1
            if change == "unloading":
                plugin._unloading = True
            if change == "session":
                resolution.context = None
            if change == "transport":
                topology.transport_identity = "transport:other"
            if change == "transport_absent":
                topology.transport_present = False
            if change == "pci_arrived":
                topology.pci_complete = True
            if change == "journal_busy":
                journal.owner.value = "presentation"
            if change == "journal_unknown":
                journal.durable = False
            if change == "gamescope_stopped":
                current.snapshot.gamescope.running = False
            if change == "gpu_unknown":
                current.snapshot.gpus = ()
            if change == "observation_error":
                plugin._connection_topology.observe = lambda: (_ for _ in ()).throw(
                    OSError("fixture unreadable")
                )
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
                module,
                "resolve_gamescope_user",
                side_effect=lambda _: NS(ok=resolution.ok, context=resolution.context),
            ),
            patch.object(module, "SnapshotTransitionObservationAdapter") as adapter,
        ):
            adapter.return_value.observe.return_value = current
            asyncio.run(plugin._maybe_automatic_link_recovery(current, True))
        self.assertEqual(
            commands.calls,
            [RESTART] if game_state is GameState.IDLE and change is None else [],
        )
        self.assertEqual(plugin._link_recovery.attempted, bool(commands.calls))

    def test_game_start_at_dispatch_refuses_restart(self):
        self.exercise_dispatch(GameState.RUNNING)

    def test_unknown_game_at_dispatch_refuses_restart(self):
        self.exercise_dispatch(GameState.UNKNOWN)

    def test_idle_dispatch_preserves_recovery(self):
        self.exercise_dispatch(GameState.IDLE)

    def test_changed_dispatch_authority_refuses_restart(self):
        for change in (
            "recovery_disabled",
            "docking_disabled",
            "non_boolean_consent",
            "unloading",
            "session",
            "transport",
            "transport_absent",
            "pci_arrived",
            "journal_busy",
            "journal_unknown",
            "gamescope_stopped",
            "gpu_unknown",
            "observation_error",
        ):
            with self.subTest(change=change):
                self.exercise_dispatch(GameState.IDLE, change)
