"""Actual auto-TV loop, admission and boot reconciliation with fake IO.

Filesystem admission/retirement semantics have their own Linux tests. Here a
retained claim inhibits the real caller chain instead of bypassing admission.
No device commands or on-disk system state are used.
"""
import asyncio
from contextlib import contextmanager
import json
from regear.adapters.steamos import commands
from dataclasses import replace
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests.test_main_process_delivery import load_main_module
from tests.test_automatic_dock import current
from tests.test_main_late_tv_arrival import Reading
from regear.application.connection_readiness import ConnectionReadinessLifecycle
from regear.application.presentation_completion import PresentationCompletion
from regear.application.supervised_transition import SupervisedTransitionExecution
from regear.delivery.dock_mutation_gate import DockMutationDenied
from regear.domain.control_plane import TransitionOutcome, TransitionOutcomeKind, PlacementState, WorkflowState
from regear.ports.transition import VersionedObservation


class ShutdownSettleRetryTests(unittest.IsolatedAsyncioTestCase):
    async def journey(self, readings, *, eligible_shutdown=True, helper_settles_at=0,
                      results=(), audit_override=None, final_game=None):
        module = load_main_module(real_dock_gate=True)
        plugin = module.Plugin()
        index = 0
        retained = True
        calls, audits, events = [], [], []
        snapshot = current("connected-internal.json").snapshot
        snapshot = replace(snapshot, displays=tuple(
            replace(d, stable_id="display:0123456789abcdef") if d.stable_id == "external-tv" else d
            for d in snapshot.displays))
        claim = NS(stage="software_down", binding="dock")
        topology = NS(binding="dock", generation="new-boot")
        user = NS(uid=1000, username="deck")

        @contextmanager
        def admit(*, allow_inhibited=False):
            if retained and not allow_inhibited:
                raise DockMutationDenied("dock_mutation.inhibited")
            yield

        def retire(expected, boot, guard):
            nonlocal retained
            self.assertIs(expected, claim)
            if not eligible_shutdown or not guard():
                return False
            retained = False
            return True

        def observe():
            return VersionedObservation("generation", replace(snapshot,
                game_state=final_game if final_game is not None and audits and audits[-1] == index else readings[index].game), f"sample-{index}")

        def execute(*args, **kwargs):
            self.assertFalse(retained)
            calls.append(index)
            if len(calls) <= len(results):
                return results[len(calls) - 1]
            return SupervisedTransitionExecution(True, "transition.succeeded", "operation",
                TransitionOutcome(TransitionOutcomeKind.SUCCEEDED, PlacementState.DOCKED_EGPU,
                                  WorkflowState.IDLE), True)

        # Use the real launcher JSON/exit adapter, with subprocess as fake IO.
        with patch.object(commands.os, "geteuid", return_value=0, create=True):
            launcher = commands.HeldTrialLauncher(uid=1000, username="deck")
        def audit(*args):
            audits.append(index)
            settled = index >= helper_settles_at
            payload = audit_override if audit_override is not None else {
                "code": "held_helper.settled" if settled else "held_helper.unsettled",
                "settled": settled, "safe_to_unplug": False}
            with patch.object(commands.subprocess, "run", return_value=NS(
                    returncode=0 if settled else 1, stdout=json.dumps(payload).encode())):
                return launcher.call("audit", "0" * 32)

        async def wait(_delay):
            nonlocal index
            index += 1
            if index == len(readings):
                raise asyncio.CancelledError

        plugin._dock_mutation_gate = lambda: NS(admit=admit)
        plugin._transition_journal_service = lambda: NS(status=lambda:NS(
            durable=True, owner=NS(value="none")))
        plugin._connection_readiness = ConnectionReadinessLifecycle(lambda:readings[index].at)
        plugin._automatic_dock_preferences = lambda:NS(load=lambda:readings[index].enabled)
        plugin._automatic_recovery_preferences = lambda:NS(load=lambda:False)
        plugin._topology_wakeup = None
        plugin._events = NS(append=lambda **event:events.append(event))
        plugin._append_journey_event = lambda **event:events.append(event)
        plugin._update_saved_tv = AsyncMock()
        plugin._audio_handoff_service = lambda:NS(remember_portable=lambda _:None)
        plugin._audio_readiness_service = lambda:NS(observe_before_display=lambda _:NS(
            ready=readings[index].hdmi, code="audio.test"))
        plugin._connection_topology = NS(observe=lambda:NS(transport_identity="dock",
            transport_present=True, transport_absent_verified=False, g1_identity="gpu",
            pci_complete=True, driver_ready=True, link_applicable=True, hdmi_ready=readings[index].hdmi))
        plugin._presentation_transition_service = lambda:NS(execute_automatic=execute,
            reconcile_completion=lambda _:PresentationCompletion("completion.test",
                hold_portable=readings[index].hold_portable))
        plugin._wait_for_topology = wait
        # Advanced software-down claims are not eligible for early-abort cleanup.
        plugin._reconcile_abandoned_dock_trial = Mock(return_value={"ok":False})
        with patch.object(module, "SnapshotTransitionObservationAdapter", return_value=NS(observe=observe)), \
             patch.object(module, "GamescopeDiscovery"), \
             patch.object(module, "resolve_gamescope_user", return_value=NS(ok=True, context=user)), \
             patch.object(module, "GamescopeIntegrationStore", return_value=NS(status=lambda:NS(ready=True))), \
             patch.object(module, "DrmDiscovery", return_value=NS(scan=lambda:[NS(boot_vga=False, pci_bdf="gpu")])), \
             patch.object(module, "resolve_whole_dock", return_value=topology), \
             patch.object(module, "inner_removal_records_absent", return_value=True), \
             patch.object(module, "read_boot_hash", return_value="b"*64), \
             patch.object(module, "HeldTrialLauncher", return_value=NS(call=audit)), \
             patch.object(module, "DockPowerIntentStore", return_value=NS(load=lambda:claim, retire_after_boot=retire)), \
             patch.object(module, "WholeDockClaimStore", return_value=NS(load=lambda:claim if retained else None)):
            with self.assertRaises(asyncio.CancelledError):
                await plugin._automatic_dock_loop()
        self.assertEqual(plugin._last_readiness_observation.sample_id, f"sample-{len(readings)-1}")
        return calls, audits, retained, events

    async def test_explicit_unsettled_then_settled_retries_without_toggle(self):
        calls, audits, retained, _ = await self.journey([Reading(n) for n in range(8)], helper_settles_at=4)
        self.assertEqual(calls, [4])
        self.assertEqual(audits, [3, 4])
        self.assertFalse(retained)

    async def test_two_unsettled_reads_exhaust_shared_retry_budget(self):
        calls, audits, retained, _ = await self.journey([Reading(n) for n in range(8)], helper_settles_at=5)
        self.assertEqual(calls, [])
        self.assertEqual(audits, [3, 4])
        self.assertTrue(retained)

    async def test_helper_retry_then_evidence_refusal_has_no_extra_retry(self):
        calls, audits, retained, _ = await self.journey([Reading(n) for n in range(8)], helper_settles_at=4,
            results=(SupervisedTransitionExecution(False, "transition.evidence_changed"),))
        self.assertEqual(calls, [4])
        self.assertEqual(audits, [3, 4])
        self.assertFalse(retained)

    async def test_other_helper_failures_do_not_retry(self):
        calls, audits, retained, _ = await self.journey([Reading(n) for n in range(8)], helper_settles_at=4,
            audit_override={"code":"held_helper.failed", "settled":False, "safe_to_unplug":False})
        self.assertEqual(calls, [])
        self.assertEqual(audits, [3])
        self.assertTrue(retained)

    async def test_changed_game_during_audit_cannot_receive_retry_disposition(self):
        from regear.domain.models import GameState
        calls, audits, retained, _ = await self.journey([Reading(n) for n in range(8)], helper_settles_at=4,
            final_game=GameState.RUNNING)
        self.assertEqual(calls, [])
        self.assertEqual(audits, [3])
        self.assertTrue(retained)

    async def test_ineligible_shutdown_never_audits_or_retries(self):
        calls, audits, retained, _ = await self.journey([Reading(n) for n in range(8)],
            eligible_shutdown=False, helper_settles_at=4)
        self.assertEqual(calls, [])
        self.assertEqual(audits, [])
        self.assertTrue(retained)


class LauncherAuditResultTests(unittest.TestCase):
    def test_started_or_unknown_operation_never_reconciles_or_retries_admission(self):
        module = load_main_module(real_dock_gate=True)
        for error in (DockMutationDenied("dock_mutation.inhibited"), OSError("unknown")):
            plugin = module.Plugin.__new__(module.Plugin)
            plugin._run_dock_mutation = Mock(side_effect=lambda operation: operation())
            plugin._presentation_transition_service = lambda:NS(execute_automatic=Mock(side_effect=error))
            plugin._reconcile_dock_power_after_boot = Mock()
            with self.assertRaises(type(error)):
                plugin._run_automatic_tv_transition("generation", True)
            self.assertEqual(plugin._run_dock_mutation.call_count, 1)
            plugin._reconcile_dock_power_after_boot.assert_not_called()

    def test_false_helper_disposition_with_started_metadata_never_rearms(self):
        from tests.test_automatic_tv_premutation_retry import sample, READY
        from regear.application.automatic_dock import AutomaticDockCoordinator
        refused = SupervisedTransitionExecution(False, "automatic_dock.shutdown_helper_unsettled")
        for value in (replace(refused, accepted=True), replace(refused, operation_id="started"),
                      replace(refused, durable=True), replace(refused, outcome=TransitionOutcome(
                          TransitionOutcomeKind.SUCCEEDED, PlacementState.DOCKED_EGPU, WorkflowState.IDLE))):
            coordinator = AutomaticDockCoordinator()
            request = coordinator.update(enabled=True, readiness=READY, current=sample())
            coordinator.record_execution(value, expected_generation=request.expected_generation)
            self.assertFalse(coordinator.update(enabled=True, readiness=READY, current=sample("new")).should_switch)

    def test_only_exact_audit_unsettled_exit_one_is_preserved(self):
        with patch.object(commands.os, "geteuid", return_value=0, create=True):
            launcher = commands.HeldTrialLauncher(uid=1000, username="deck")
        valid = {"code":"held_helper.unsettled", "settled":False, "safe_to_unplug":False}
        for action, rc, value, expected in (
                ("audit",1,valid,valid), ("prepare",1,valid,{"code":"held_helper.failed"}),
                ("audit",2,valid,{"code":"held_helper.failed"}),
                ("audit",1,{**valid,"settled":0},{"code":"held_helper.failed"}),
                ("audit",1,{**valid,"safe_to_unplug":True},{"code":"held_helper.failed"}),
                ("audit",1,{**valid,"extra":"unknown"},{"code":"held_helper.failed"}),
                ("audit",1,{**valid,"code":"held_helper.failed"},{"code":"held_helper.failed"})):
            with self.subTest(action=action,rc=rc,value=value), patch.object(commands.subprocess,"run",
                    return_value=NS(returncode=rc,stdout=json.dumps(value).encode())):
                self.assertEqual(launcher.call(action,"0"*32),expected)
        for output in (b"not-json", b"[]", b"x" * 16385):
            with patch.object(commands.subprocess,"run",return_value=NS(returncode=1,stdout=output)):
                self.assertEqual(launcher.call("audit","0"*32), {"code":"held_helper.failed"})
