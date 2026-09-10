from __future__ import annotations

import dataclasses
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.application.canonical_sleep import (  # noqa: E402
    CanonicalSleepWorkflowService,
)
from regear.domain.control_plane import (  # noqa: E402
    CapabilitySupport,
    EgpuCapabilities,
    HostCapabilities,
    PlacementState,
    RemovalBehavior,
    RequestIntent,
    RequestSource,
    SleepBehavior,
    TransitionRequest,
    WorkflowState,
    compose_capabilities,
)
from regear.domain.game_compatibility import GameSaveCapability  # noqa: E402
from regear.domain.models import EgpuPresence, GameState  # noqa: E402
from regear.domain.serialization import snapshot_from_dict  # noqa: E402
from regear.domain.sleep_workflow import (  # noqa: E402
    SleepDirective,
    SleepFlowEvent,
    SleepFlowStage,
    SleepWorkflowContext,
)
from regear.domain.transition_journal import (  # noqa: E402
    JournalEventKind,
    TransitionJournal,
    append_journal_entry,
)
from regear.ports.sleep_workflow import SleepWorkflowObservation  # noqa: E402
from regear.profiles.ally_x import CAPABILITIES as ALLY_X  # noqa: E402
from regear.profiles.gpd_g1 import CAPABILITIES as GPD_G1  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures"


def readiness():
    value = json.loads((FIXTURES / "portable.json").read_text(encoding="utf-8"))
    snapshot = snapshot_from_dict(value)
    return dataclasses.replace(
        snapshot.disconnect_readiness,
        applicable=True,
        scan_complete=True,
        ready=True,
        egpu_stable_id="gpd-g1:ephemeral",
    )


def live_capabilities():
    return compose_capabilities(
        HostCapabilities(
            "test-host",
            egpu_support=CapabilitySupport.VERIFIED,
            display_handoff=CapabilitySupport.VERIFIED,
        ),
        EgpuCapabilities(
            "test-egpu",
            display_output=CapabilitySupport.VERIFIED,
            sleep_behavior=SleepBehavior.SLEEP_UNRELIABLE,
            removal_behavior=RemovalBehavior.LIVE_REMOVAL_VERIFIED,
        ),
    )


def context(
    *,
    game_state=GameState.IDLE,
    presence=EgpuPresence.PRESENT,
    placement=PlacementState.DOCKED_EGPU,
    capabilities=None,
    removal_ready=False,
    save_capability=GameSaveCapability.UNTESTED,
):
    return SleepWorkflowContext(
        egpu_presence=presence,
        exact_egpu_identity_verified=presence is not EgpuPresence.UNKNOWN,
        capabilities=capabilities or compose_capabilities(ALLY_X, GPD_G1),
        game_state=game_state,
        save_capability=save_capability,
        disconnect_readiness=readiness(),
        placement=placement,
        removal_readiness_verified=removal_ready,
    )


def observed(
    sample_id: str,
    value=None,
    *,
    generation="generation-current",
):
    current = value or context()
    return SleepWorkflowObservation(
        generation,
        sample_id,
        current,
        "gpd-g1:exact-test" if current.egpu_presence is EgpuPresence.PRESENT else "",
    )


def request(source=RequestSource.STEAM_MENU, *, generation="generation-current"):
    return TransitionRequest(
        "sleep-request-0001",
        RequestIntent.SLEEP,
        source,
        "2026-08-31T12:00:00Z",
        generation,
    )


class Observations:
    def __init__(self, *values):
        self.values = list(values)

    def observe(self):
        if not self.values:
            raise OSError("no observation")
        return self.values.pop(0)


class Clock:
    def __init__(self):
        self.value = 100

    def now_ms(self):
        self.value += 10
        return self.value


class JournalStore:
    def __init__(self, current=None):
        self.current = current
        self.saved = []

    def load_current(self):
        return self.current

    def save(self, journal):
        if self.current is not None and self.current.operation_id != journal.operation_id:
            raise ValueError("operation changed")
        self.current = journal
        self.saved.append(journal)

    def clear_terminal(self, operation_id):
        if (
            self.current is None
            or not self.current.terminal
            or self.current.operation_id != operation_id
        ):
            raise ValueError("terminal operation mismatch")
        self.current = None


def service(observations, store=None):
    value = CanonicalSleepWorkflowService(
        observations=observations,
        clock=Clock(),
        journal_store=store or JournalStore(),
        occurred_at=lambda: "2026-08-31T12:00:00Z",
        operation_id_factory=lambda: "sleep-operation-0001",
    )
    return value


class CanonicalSleepWorkflowServiceTests(unittest.TestCase):
    def test_steam_menu_and_physical_button_enter_the_same_engine(self):
        for source in (RequestSource.STEAM_MENU, RequestSource.PHYSICAL_BUTTON):
            with self.subTest(source=source):
                value = service(Observations(observed("sample-1")))
                result = value.start(request(source))
                self.assertTrue(result.accepted)
                self.assertEqual(result.flow.stage, SleepFlowStage.SHUTDOWN_REQUIRED)
                self.assertIn(
                    SleepDirective.SHUTDOWN_BEFORE_DISCONNECT,
                    result.flow.directives,
                )
                self.assertNotIn(
                    SleepDirective.SHOW_SAFE_TO_DISCONNECT,
                    result.flow.directives,
                )

    def test_physical_button_requires_declared_interception_capability(self):
        unsupported = dataclasses.replace(
            context(),
            capabilities=compose_capabilities(
                HostCapabilities("unknown-host"), GPD_G1
            ),
        )
        result = service(Observations(observed("sample-1", unsupported))).start(
            request(RequestSource.PHYSICAL_BUTTON)
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "sleep.physical_interception_unavailable")

    def test_stale_generation_or_automatic_source_never_creates_journal(self):
        store = JournalStore()
        stale = service(Observations(observed("sample-1")), store).start(
            request(generation="stale-generation")
        )
        self.assertFalse(stale.accepted)
        self.assertEqual(stale.code, "sleep.request_generation_stale")
        self.assertIsNone(store.current)

        automatic = service(Observations(), store).start(
            request(RequestSource.AUTOMATIC)
        )
        self.assertFalse(automatic.accepted)
        self.assertEqual(automatic.code, "sleep.source_unsupported")
        self.assertIsNone(store.current)

    def test_step_started_is_durable_before_external_game_action(self):
        store = JournalStore()
        value = service(
            Observations(observed("sample-1", context(game_state=GameState.RUNNING))),
            store,
        )
        result = value.start(request())
        self.assertEqual(result.flow.stage, SleepFlowStage.AWAITING_GAME_CONSENT)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.STEP_STARTED)
        self.assertEqual(
            dict(store.current.entries[-1].details)["step_code"],
            SleepFlowStage.AWAITING_GAME_CONSENT.value,
        )

    def test_verified_effect_event_requires_a_fresh_observation(self):
        running = context(game_state=GameState.RUNNING)
        idle = context(game_state=GameState.IDLE)
        value = service(
            Observations(
                observed("sample-1", running),
                observed("sample-1", running),
                observed("sample-1", idle),
                observed("sample-2", idle),
            )
        )
        started = value.start(request())
        closing = value.advance(
            started.flow.request_id, SleepFlowEvent.GAME_CONSENT_GRANTED
        )
        self.assertEqual(closing.flow.stage, SleepFlowStage.CLOSING_GAME)
        stale = value.advance(
            started.flow.request_id, SleepFlowEvent.GAME_EXIT_VERIFIED
        )
        self.assertFalse(stale.accepted)
        self.assertEqual(stale.code, "sleep.fresh_observation_required")
        finished = value.advance(
            started.flow.request_id, SleepFlowEvent.GAME_EXIT_VERIFIED
        )
        self.assertTrue(finished.accepted)
        self.assertEqual(finished.flow.stage, SleepFlowStage.SHUTDOWN_REQUIRED)

    def test_verified_save_child_requires_durable_exact_substep(self):
        running = context(
            game_state=GameState.RUNNING,
            save_capability=GameSaveCapability.VERIFIED_TRIGGERABLE_AUTOSAVE,
        )
        store = JournalStore()
        value = service(
            Observations(
                observed("sample-1", running),
                observed("sample-2", running),
            ),
            store,
        )
        started = value.start(request())
        closing = value.advance(
            started.flow.request_id, SleepFlowEvent.GAME_CONSENT_GRANTED
        )
        self.assertEqual(closing.flow.stage, SleepFlowStage.CLOSING_GAME)
        parent, host_profile, egpu_profile = value.game_save_requirements(
            started.flow.request_id
        )
        self.assertEqual(parent, started.operation_id)
        self.assertEqual(host_profile, running.capabilities.host_profile_id)
        self.assertEqual(egpu_profile, running.capabilities.egpu_profile_id)
        self.assertFalse(
            value.mark_verified_game_save_completed(
                started.flow.request_id, parent
            )
        )

        journal = append_journal_entry(
            store.current,
            kind=JournalEventKind.SUBSTEP_STARTED,
            occurred_at="test",
            workflow_state=WorkflowState.SLEEP_PENDING_DISCONNECT,
            placement=PlacementState.DOCKED_EGPU,
            code="game.save_substep_started",
            details=(("step_code", "game_save.verified"),),
        )
        journal = append_journal_entry(
            journal,
            kind=JournalEventKind.SUBSTEP_VERIFIED,
            occurred_at="test",
            workflow_state=WorkflowState.SLEEP_PENDING_DISCONNECT,
            placement=PlacementState.DOCKED_EGPU,
            code="game.save_substep_verified",
            details=(("step_code", "game_save.verified"),),
        )
        store.save(journal)
        self.assertTrue(
            value.mark_verified_game_save_completed(
                started.flow.request_id, parent
            )
        )
        self.assertTrue(value.verified_game_save_completed(started.flow.request_id))
        self.assertEqual(
            value.game_save_requirements(started.flow.request_id),
            ("", "", ""),
        )

    def test_exact_egpu_identity_change_terminalizes_before_game_close(self):
        running = context(game_state=GameState.RUNNING)
        changed = SleepWorkflowObservation(
            "generation-changed",
            "sample-2",
            running,
            "gpd-g1:different-instance",
        )
        store = JournalStore()
        value = service(
            Observations(observed("sample-1", running), changed), store
        )
        started = value.start(request())
        result = value.advance(
            started.flow.request_id, SleepFlowEvent.GAME_CONSENT_GRANTED
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "sleep.egpu_identity_changed")
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.FAILED)
        self.assertEqual(value.status().code, "sleep.egpu_identity_changed")

    def test_live_removal_path_continues_original_request_exactly_once(self):
        capabilities = live_capabilities()
        waiting = context(capabilities=capabilities, removal_ready=True)
        absent = context(
            presence=EgpuPresence.ABSENT,
            placement=PlacementState.UNKNOWN,
            capabilities=capabilities,
            removal_ready=True,
        )
        portable = dataclasses.replace(absent, placement=PlacementState.PORTABLE)
        store = JournalStore()
        value = service(
            Observations(
                observed("sample-1", waiting),
                observed("sample-2", absent),
                observed("sample-3", portable),
                observed("sample-3", portable),
            ),
            store,
        )
        result = value.start(request())
        self.assertEqual(result.flow.stage, SleepFlowStage.AWAITING_DISCONNECT)
        result = value.advance(
            result.flow.request_id, SleepFlowEvent.EGPU_REMOVAL_VERIFIED
        )
        self.assertEqual(result.flow.stage, SleepFlowStage.RESTORING_PORTABLE)
        result = value.advance(
            result.flow.request_id, SleepFlowEvent.PORTABLE_RECOVERY_VERIFIED
        )
        self.assertEqual(result.flow.stage, SleepFlowStage.READY_TO_CONTINUE_SLEEP)
        self.assertEqual(
            result.flow.directives, (SleepDirective.CONTINUE_ORIGINAL_SLEEP,)
        )
        result = value.advance(
            result.flow.request_id, SleepFlowEvent.ORIGINAL_SLEEP_CONTINUED
        )
        self.assertEqual(result.flow.stage, SleepFlowStage.COMPLETED)
        self.assertEqual(store.current.entries[-1].kind, JournalEventKind.COMMITTED)
        repeated = value.advance(
            result.flow.request_id, SleepFlowEvent.ORIGINAL_SLEEP_CONTINUED
        )
        self.assertFalse(repeated.accepted)
        self.assertEqual(repeated.code, "sleep.session_terminal")

    def test_restart_recovery_never_continues_sleep(self):
        store = JournalStore()
        active = service(
            Observations(observed("sample-1", context(game_state=GameState.RUNNING))),
            store,
        )
        started = active.start(request())
        self.assertEqual(started.flow.stage, SleepFlowStage.AWAITING_GAME_CONSENT)

        portable_absent = context(
            presence=EgpuPresence.ABSENT,
            placement=PlacementState.PORTABLE,
        )
        restarted = service(
            Observations(observed("sample-restart", portable_absent)), store
        )
        recovered = restarted.recover_interrupted()
        self.assertTrue(recovered.accepted)
        self.assertEqual(recovered.code, "sleep.restart_portable_verified")
        self.assertEqual(
            store.current.entries[-1].kind, JournalEventKind.RECOVERY_VERIFIED
        )
        self.assertNotIn(
            JournalEventKind.COMMITTED,
            tuple(entry.kind for entry in store.current.entries),
        )

    def test_foreign_journal_blocks_start_and_cannot_be_acknowledged(self):
        foreign = append_journal_entry(
            TransitionJournal("process-operation-1", "process-request-1"),
            kind=JournalEventKind.REQUESTED,
            occurred_at="test",
            workflow_state=WorkflowState.PREPARING_TO_DISCONNECT,
            placement=PlacementState.DOCKED_EGPU,
            code="process_release.requested",
        )
        store = JournalStore(foreign)
        value = service(Observations(observed("sample-1")), store)
        result = value.start(request())
        self.assertFalse(result.accepted)
        self.assertEqual(result.code, "sleep.journal_recovery_required")
        self.assertFalse(value.acknowledge("process-operation-1"))
        self.assertEqual(value.status().code, "sleep.foreign_journal")
        self.assertEqual(value.recover_interrupted().code, "sleep.foreign_journal")

    def test_terminal_result_requires_exact_acknowledgement(self):
        store = JournalStore()
        value = service(Observations(observed("sample-1")), store)
        result = value.start(request())
        status = value.status()
        self.assertTrue(status.acknowledgement_required)
        self.assertTrue(status.action_required)
        self.assertEqual(status.source, RequestSource.STEAM_MENU)
        self.assertFalse(value.acknowledge("sleep-operation-wrong"))
        self.assertTrue(value.acknowledge(result.operation_id))
        self.assertEqual(value.status().code, "sleep.idle")


if __name__ == "__main__":
    unittest.main()
