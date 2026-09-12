"""Actual auto-TV loop, admission and boot reconciliation with fake IO.

Filesystem admission/retirement semantics have their own Linux tests. Here a
retained claim inhibits the real caller chain instead of bypassing admission.
No device commands or on-disk system state are used.
"""
import asyncio
from contextlib import contextmanager
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


class AutomaticDockCoexistenceTests(unittest.IsolatedAsyncioTestCase):
    async def journey(self, readings, *, eligible_shutdown=True, helper_settles_at=0,
                      results=()):
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
                game_state=readings[index].game), f"sample-{index}")

        def execute(*args, **kwargs):
            self.assertFalse(retained)
            calls.append(index)
            if len(calls) <= len(results):
                return results[len(calls) - 1]
            return SupervisedTransitionExecution(True, "transition.succeeded", "operation",
                TransitionOutcome(TransitionOutcomeKind.SUCCEEDED, PlacementState.DOCKED_EGPU,
                                  WorkflowState.IDLE), True)

        def audit(*args):
            audits.append(index)
            return {"code": "held_helper.settled", "settled": index >= helper_settles_at}

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

    async def test_new_boot_shutdown_retirement_and_late_hdmi_preserve_single_dispatch(self):
        readings = [Reading(n, hdmi=False) for n in range(5)] + [Reading(600+n) for n in range(4)]
        calls, audits, retained, events = await self.journey(readings)
        self.assertEqual(calls, [6])
        self.assertEqual(audits, [6])
        self.assertFalse(retained)
        self.assertNotIn("automatic_dock.observation_failed", [e["code"] for e in events])

    async def test_running_and_unknown_wait_before_any_retirement(self):
        from regear.domain.models import GameState
        for game in (GameState.RUNNING, GameState.UNKNOWN):
            readings = [Reading(n, game=game) for n in range(6)] + [Reading(6), Reading(7)]
            calls, audits, retained, _ = await self.journey(readings)
            self.assertEqual(calls, [6])
            self.assertEqual(audits, [6])
            self.assertFalse(retained)

    async def test_retained_nonretirable_claim_and_completion_hold_survive_toggle(self):
        readings = [Reading(n) for n in range(5)] + [Reading(5, enabled=False), Reading(6), Reading(7)]
        for hold in (False, True):
            calls, audits, retained, _ = await self.journey(
                [replace(r, hold_portable=hold) for r in readings], eligible_shutdown=False)
            self.assertEqual(calls, [])
            self.assertEqual(audits, [])
            self.assertTrue(retained)

    async def test_retirement_does_not_replenish_premutation_retry_budget(self):
        refused = SupervisedTransitionExecution(False, "transition.evidence_changed")
        calls, audits, retained, _ = await self.journey([Reading(n) for n in range(9)],
            results=(refused, refused))
        self.assertEqual(calls, [3, 4])
        self.assertEqual(audits, [3])
        self.assertFalse(retained)

    async def test_late_helper_settle_currently_needs_explicit_preference_rearm(self):
        """Characterize a remaining liveness gap, not a safe automatic retry grant."""
        readings = [Reading(n) for n in range(8)]
        calls, audits, retained, _ = await self.journey(readings, helper_settles_at=4)
        self.assertEqual(calls, [])
        self.assertEqual(audits, [3])
        self.assertTrue(retained)
        calls, audits, retained, _ = await self.journey(readings + [Reading(8, enabled=False), Reading(9)],
            helper_settles_at=4)
        self.assertEqual(calls, [9])
        self.assertEqual(audits, [3, 9])
        self.assertFalse(retained)
