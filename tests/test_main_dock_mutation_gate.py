"""RPC admission is exercised separately from unrelated mocked delivery tests."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module
from tests import test_main_link_recovery as recovery_fixtures
from regear.delivery.dock_mutation_gate import DockMutationDenied


class Denied:
    @contextmanager
    def admit(self):
        raise DockMutationDenied("test.inhibited")
        yield


class MainDockAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)

    def test_unavailable_factory_never_invokes_mutation(self):
        self.plugin._dock_mutation_gate = Mock(side_effect=OSError("unavailable"))
        command = Mock()
        with self.assertRaises(DockMutationDenied):
            self.plugin._run_dock_mutation(command)
        command.assert_not_called()

    def test_gate_lifetime_covers_entire_operation(self):
        held = []
        @contextmanager
        def admit():
            held.append(True)
            try:
                yield
            finally:
                held.clear()
        self.plugin._dock_mutation_gate = lambda: NS(admit=admit)
        self.assertTrue(self.plugin._run_dock_mutation(lambda: bool(held)))
        self.assertEqual(held, [])

    def test_manual_recovery_refuses_without_calling_service(self):
        fixture = recovery_fixtures.LinkRecoveryStrategySelectionTests()
        fixture.module = self.module
        plugin, service = fixture.executable()
        plugin._dock_mutation_gate = lambda: Denied()
        result = fixture.run_execute(plugin, confirm=True)
        self.assertEqual(result['code'], 'link_recovery.dock_mutation_inhibited')
        self.assertEqual(service.asked_for, [])

    def test_legacy_disconnect_refuses_before_runtime_execution(self):
        runtime = NS(execute=Mock())
        self.plugin._live_disconnect_runtime = lambda: runtime
        self.plugin._dock_mutation_gate = lambda: Denied()
        with patch.object(self.module, 'RelaunchIntentStore'):
            result = asyncio.run(self.plugin.execute_egpu_disconnect())
        self.assertFalse(result['ok'])
        runtime.execute.assert_not_called()

    def test_automatic_recovery_inhibition_does_not_consume_attempt(self):
        from regear.application.automatic_link_recovery import AutomaticLinkRecovery
        from regear.domain.models import GameState
        from tests.test_link_recovery_service import FakeCommands, USER, service
        plugin = self.plugin
        plugin._unloading = False
        plugin._discovery = object()
        plugin._last_readiness_observation = recovery_fixtures.observation(
            transport_identity='transport:known')
        policy = plugin._automatic_link_recovery = AutomaticLinkRecovery()
        facts = dict(absent=False, present=True, identity='transport:known',
                     pci_complete=False, enabled=True, idle=True)
        policy.observe(now=0, **{**facts, 'absent': True, 'present': False})
        policy.observe(now=1, **facts)
        plugin._automatic_recovery_preferences = lambda: NS(load=lambda: True)
        plugin._automatic_dock_preferences = lambda: NS(load=lambda: True)
        plugin._transition_journal_service = lambda: NS(status=lambda: NS(
            durable=True, owner=NS(value='none')))
        plugin._dock_mutation_gate = lambda: Denied()
        current = NS(snapshot=NS(game_state=GameState.IDLE, gamescope=NS(running=True),
            gpus=(NS(role=self.module.GpuRole.INTERNAL, present=True,
                     confidence=self.module.Confidence.VERIFIED),)))
        async def observe(_):
            return recovery_fixtures.status()
        async def background(fn):
            return fn()
        plugin._observe_connection_readiness = observe
        plugin._run_background_operation = background
        plugin._append_journey_event = Mock()
        commands = FakeCommands()
        plugin._link_recovery, _ = service(commands, [True])
        with patch.object(self.module.time, 'monotonic', return_value=11), \
             patch.object(self.module, 'resolve_runtime_profiles', return_value=NS(exact_host=True)), \
             patch.object(self.module, 'GamescopeDiscovery'), \
             patch.object(self.module, 'resolve_gamescope_user', return_value=NS(ok=True, context=USER)), \
             patch.object(self.module, 'SnapshotTransitionObservationAdapter') as adapter:
            adapter.return_value.observe.return_value = current
            self.assertFalse(asyncio.run(plugin._maybe_automatic_link_recovery(current, True)))
        self.assertEqual(commands.calls, [])
        self.assertEqual(policy.attempts, 0)
        self.assertFalse(policy.in_flight)
        plugin._append_journey_event.assert_not_called()


if __name__ == '__main__':
    unittest.main()
