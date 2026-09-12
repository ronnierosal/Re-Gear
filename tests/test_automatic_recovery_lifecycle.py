"""Real recovery scheduling/admission composition with fake OS boundaries.

The plugin wrappers, scheduler, reservation preflight, and recovery service are
real. Gate/claim filesystem, discovery, and commands are fake IO; these tests
neither operate hardware nor replace the privileged filesystem gate tests.
"""
import asyncio
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module
from tests.test_main_link_recovery import observation, status
from tests.test_link_recovery_service import FakeCommands, USER, RESTART, service
from regear.delivery.dock_mutation_gate import DockMutationDenied
from regear.domain.models import Confidence, GameState, GpuRole


class FakeAdmission:
    """OS admission boundary, retaining the shared claim across plugin reloads."""
    def __init__(self, state):
        self.state = state
        self.held = False
        self.entries = []

    @contextmanager
    def admit(self, *, allow_inhibited=False):
        self.entries.append(allow_inhibited)
        if self.state.denial:
            raise DockMutationDenied(self.state.denial)
        if self.held:
            raise AssertionError("nested admission")
        if self.state.claim is not None and not allow_inhibited:
            raise DockMutationDenied("dock_mutation.inhibited")
        self.held = True
        try:
            yield
        finally:
            self.held = False


class AutomaticRecoveryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main_module(real_dock_gate=True)
        self.state = NS(claim=None, denial="", shutdown_consumed=False,
                        old_boot=False, retirement_count=0, now=0.0)
        self.gate = FakeAdmission(self.state)
        self.current = NS(snapshot=NS(game_state=GameState.IDLE,
            gamescope=NS(running=True, confidence=Confidence.VERIFIED),
            gpus=(NS(role=GpuRole.INTERNAL, present=True, confidence=Confidence.VERIFIED),)))
        self.transport = NS(binding="dock", generation="transport-generation")
        self.topology = NS(transport_identity="transport:known", transport_present=True,
                           pci_complete=False)
        self.journal = NS(durable=True, owner=NS(value="none"))
        self.claim_store = Mock()
        self.claim_store.load.side_effect = lambda: self.state.claim
        self.power_store = Mock()
        self.power_store.load.side_effect = lambda: self.state.claim
        self.power_store.retire_after_boot.side_effect = self.retire_after_boot
        self.audit = Mock(return_value={"code": "held_helper.settled", "settled": True})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        patches = {
            "DockMutationGate": Mock(return_value=self.gate),
            "RootOwnedRuntimeState": Mock(return_value=NS(ensure=lambda: "fake-root")),
            "WholeDockClaimStore": Mock(return_value=self.claim_store),
            "DockPowerIntentStore": Mock(return_value=self.power_store),
            "read_boot_hash": Mock(return_value="b" * 64),
            "resolve_transport": Mock(return_value=self.transport),
            "inner_removal_records_absent": Mock(return_value=True),
            "HeldTrialLauncher": Mock(return_value=NS(call=self.audit)),
            "DrmDiscovery": Mock(return_value=NS(scan=lambda: [])),
            "GamescopeDiscovery": Mock(return_value=NS(scan=lambda: [])),
            "resolve_gamescope_user": Mock(return_value=NS(ok=True, context=USER)),
            "resolve_runtime_profiles": Mock(return_value=NS(exact_host=True)),
            "SnapshotTransitionObservationAdapter": Mock(return_value=NS(observe=lambda: self.current)),
        }
        for name, value in patches.items():
            self.stack.enter_context(patch.object(self.module, name, value))
        self.stack.enter_context(patch.object(self.module.time, "monotonic",
                                             side_effect=lambda: self.state.now))
        self.make_plugin()

    def retire_after_boot(self, claim, boot, guard):
        # Fake durable-store boundary enforces the consumed old-boot prerequisite;
        # the actual plugin supplies and runs its real topology/session guard.
        if not (self.state.shutdown_consumed and self.state.old_boot):
            return False
        if guard() is not True:
            return False
        self.assertIs(claim, self.state.claim)
        self.assertEqual(boot, "b" * 64)
        self.state.claim = None
        self.state.retirement_count += 1
        return True

    def make_plugin(self):
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.plugin._unloading = False
        self.plugin._background_operations = set()
        self.plugin._discovery = object()
        self.plugin._automatic_recovery_preferences = lambda: NS(load=lambda: True)
        self.plugin._automatic_dock_preferences = lambda: NS(load=lambda: True)
        self.plugin._transition_journal_service = lambda: NS(status=lambda: self.journal)
        self.plugin._connection_topology = NS(observe=lambda: self.topology)
        self.plugin._append_journey_event = Mock()
        self.commands = FakeCommands()
        original_run = self.commands.run
        def run(*args, **kwargs):
            self.assertTrue(self.gate.held, "restart escaped dock admission")
            return original_run(*args, **kwargs)
        self.commands.run = run
        self.plugin._link_recovery, _ = service(self.commands, [True])
        async def readiness(_):
            return status()
        self.plugin._observe_connection_readiness = readiness

    def poll(self, now, *, absent=False):
        self.state.now = now
        self.plugin._last_readiness_observation = observation(
            transport_identity="" if absent else "transport:known",
            transport_present=not absent, transport_absent_verified=absent)
        return asyncio.run(self.plugin._maybe_automatic_link_recovery(self.current, True))

    def attach_until_due(self):
        self.assertFalse(self.poll(0, absent=True))
        self.assertFalse(self.poll(1))
        self.assertFalse(self.poll(10.999))
        self.assertEqual(self.commands.calls, [])

    def decision(self):
        result = asyncio.run(self.plugin._automatic_link_recovery_status())
        self.assertEqual(result["max_attempts"], 2)
        self.assertIsNot(result.get("safe_to_unplug"), True)
        return result["decision_code"]

    def event_codes(self):
        return [call.kwargs["code"] for call in self.plugin._append_journey_event.call_args_list]

    def assert_denied(self, code):
        self.assertFalse(self.poll(11))
        self.assertFalse(self.poll(12))
        self.assertFalse(self.poll(13))
        self.assertEqual(self.commands.calls, [])
        self.assertEqual(self.plugin._automatic_link_recovery.attempts, 0)
        self.assertEqual(self.state.retirement_count, 0)
        self.assertNotIn("automatic_recovery.started", self.event_codes())
        self.assertEqual(self.decision(), code)
        self.assertEqual(self.event_codes().count(code), 1)

    def test_absence_then_idle_attach_recovers_at_ten_seconds_under_admission(self):
        self.attach_until_due()
        self.assertTrue(self.poll(11))
        self.assertEqual(self.commands.calls, [RESTART])
        self.assertEqual(self.plugin._automatic_link_recovery.attempts, 1)
        self.assertEqual(self.event_codes(), ["automatic_recovery.waiting_for_transport",
            "automatic_recovery.settling", "automatic_recovery.started", "link_recovery.trained"])
        self.assertEqual(self.decision(), "link_recovery.trained")
        self.assertFalse(self.poll(30))
        self.assertEqual(self.commands.calls, [RESTART])

    def test_ordinary_software_down_survives_plugin_recreation_and_blocks_restart(self):
        claim = self.state.claim = NS(stage="software_down", binding="dock")
        for _ in range(2):
            self.make_plugin()
            self.attach_until_due()
            self.assert_denied("automatic_recovery.admission_inhibited")
            self.assertIs(self.state.claim, claim)
        self.claim_store.retire_abandoned.assert_not_called()

    def test_busy_unavailable_and_unrecognized_admission_are_reported_once(self):
        for denial, code in (
            ("dock_mutation.unavailable_or_busy", "automatic_recovery.admission_unavailable_or_busy"),
            ("dock_mutation.unavailable", "automatic_recovery.admission_unavailable_or_busy"),
            ("unexpected.private_detail", "automatic_recovery.admission_refused"),
        ):
            with self.subTest(denial=denial):
                self.make_plugin()
                self.state.denial = denial
                self.attach_until_due()
                self.assert_denied(code)
                self.assertNotIn(denial, self.event_codes())

    def test_settled_early_claim_allows_connection_recovery_without_retirement(self):
        for stage in ("claimed", "release_intent"):
            with self.subTest(stage=stage):
                claim = self.state.claim = NS(stage=stage, binding="dock")
                self.make_plugin()
                self.attach_until_due()
                self.assertTrue(self.poll(11))
                self.assertEqual(self.commands.calls, [RESTART])
                self.assertIs(self.state.claim, claim)
                self.assertEqual(self.state.retirement_count, 0)
                self.assertIn(True, self.gate.entries)
                self.assertEqual(self.decision(), "link_recovery.trained")

    def test_unsettled_early_claim_remains_inhibited(self):
        self.state.claim = NS(stage="release_intent", binding="dock")
        self.audit.return_value = {"code": "held_helper.unsettled", "settled": False}
        self.attach_until_due()
        self.assert_denied("automatic_recovery.admission_inhibited")

    def test_consumed_shutdown_new_boot_retires_then_retries_ordinary_admission(self):
        self.state.claim = NS(stage="software_down", binding="dock")
        self.state.shutdown_consumed = True
        self.state.old_boot = True
        self.attach_until_due()
        self.assertTrue(self.poll(11))
        self.assertEqual(self.commands.calls, [RESTART])
        self.assertEqual(self.state.retirement_count, 1)
        self.assertIsNone(self.state.claim)
        self.assertEqual(self.gate.entries, [False, True, False])
        self.assertEqual(self.decision(), "link_recovery.trained")


if __name__ == "__main__":
    unittest.main()
