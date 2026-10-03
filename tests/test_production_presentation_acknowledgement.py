"""Real production Plugin wrapper, handler, service and filesystem journal."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.test_main_process_delivery import load_main_module
from tests.issued_presentation_result import issue_result
from regear.delivery import build_profile_config
from regear.delivery.build_profile_policy import rpc_allowed
from regear.application.supervised_transition import SupervisedPresentationTransitionService
from regear.delivery.transition_journal_store import FileTransitionJournalStore
from regear.domain.control_plane import PlacementState, WorkflowState
from regear.domain.transition_journal import TransitionJournal, JournalEventKind, append_journal_entry
from regear.ports.audio_recovery import AudioRecoveryBlocked


ACK_ID = "DJ-" + "a" * 18


def retained(*, terminal=True, capability="presentation_transition"):
    journal = TransitionJournal(ACK_ID, "request-ack")
    journal = append_journal_entry(journal, kind=JournalEventKind.REQUESTED,
        occurred_at="2026-10-03T07:00:00Z", workflow_state=WorkflowState.IDLE,
        placement=PlacementState.PORTABLE, code="request.accepted",
        details=(("capability", capability), ("target_placement", "portable")))
    if terminal:
        journal = append_journal_entry(journal, kind=JournalEventKind.BLOCKED,
            occurred_at="2026-10-03T07:00:01Z", workflow_state=WorkflowState.ACTION_REQUIRED,
            placement=PlacementState.PORTABLE, code="transition.blocked",
            details=(("blocker_code", "observation.stale"),))
    return journal


class ProductionAcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.object(build_profile_config, "BUILD_PROFILE", "production"):
            self.module = load_main_module(real_dock_gate=True)
        self.plugin = self.module.Plugin.__new__(self.module.Plugin)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = FileTransitionJournalStore(Path(self.temp.name).resolve())
        self.service = SupervisedPresentationTransitionService(
            observations=None, orchestrator=None, journal_store=self.store,
            integration_ready=lambda: True)
        self.plugin._presentation_transition_service = Mock(return_value=self.service)
        self.plugin._automatic_dock = Mock()
        self.plugin._topology_wakeup = Mock()

    async def test_actual_production_button_acknowledges_exact_blocked_result(self):
        self.store.save(retained())
        self.assertTrue(self.service.status().acknowledgement_required)
        result = await self.plugin.acknowledge_supervised_tv_switch(ACK_ID)
        self.assertTrue(result.get("acknowledged"), result)
        self.assertIsNone(self.store.load_current())
        self.assertFalse(self.service.status().acknowledgement_required)
        self.plugin._automatic_dock.reset_after_acknowledgement.assert_called_once()
        self.plugin._automatic_dock.suppress_current_attachment_after_portable_return.assert_not_called()
        self.plugin._topology_wakeup.invalidate.assert_called_once()

    async def test_real_preview_execute_issued_id_is_admitted_and_acknowledged(self):
        plugin, store, identity = issue_result(Path(self.temp.name).resolve())
        journal = await plugin.get_transition_journal_status()
        status = await plugin.get_supervised_tv_switch_status()
        self.assertEqual(journal["acknowledgement_id"], identity)
        self.assertEqual(status["acknowledgement_id"], identity)
        self.assertEqual(len(identity), 24)
        self.assertTrue(rpc_allowed("production", "acknowledge_supervised_tv_switch",
                                    {"acknowledgement_id": identity}))
        result = await plugin.acknowledge_supervised_tv_switch(identity)
        self.assertTrue(result.get("acknowledged"), result)
        self.assertIsNone(store.load_current())

    async def test_keyword_rpc_uses_the_same_actual_handler(self):
        self.store.save(retained())
        result = await self.plugin.acknowledge_supervised_tv_switch(acknowledgement_id=ACK_ID)
        self.assertTrue(result.get("acknowledged"), result)
        self.assertIsNone(self.store.load_current())

    async def test_valid_stale_identity_reaches_exact_guard_without_clearing(self):
        original = retained()
        self.store.save(original)
        result = await self.plugin.acknowledge_supervised_tv_switch("DJ-" + "b" * 18)
        self.assertEqual({"schema_version": 1, "acknowledged": False}, result)
        self.assertEqual(self.store.load_current(), original)
        self.plugin._automatic_dock.assert_not_called()
        self.plugin._automatic_dock.reset_after_acknowledgement.assert_not_called()
        self.plugin._topology_wakeup.invalidate.assert_not_called()

    async def test_foreign_or_incomplete_journal_is_not_acknowledged(self):
        for original in (retained(terminal=False), retained(capability="sleep")):
            with self.subTest(original=original):
                self.store._target.unlink(missing_ok=True)
                self.store.save(original)
                result = await self.plugin.acknowledge_supervised_tv_switch(ACK_ID)
                self.assertEqual({"schema_version": 1, "acknowledged": False}, result)
                self.assertEqual(self.store.load_current(), original)
        self.plugin._automatic_dock.reset_after_acknowledgement.assert_not_called()

    async def test_malformed_id_is_refused_before_production_body(self):
        self.store.save(retained())
        for identity in (None, True, 4, [], {}, "", "a" * 7, "a" * 65,
                         "a" * 24 + "\n", "a" * 24 + "/", "a" * 23 + "."):
            result = await self.plugin.acknowledge_supervised_tv_switch(identity)
            self.assertEqual("build_profile.feature_unavailable", result["code"])
        self.plugin._presentation_transition_service.assert_not_called()
        self.assertIsNotNone(self.store.load_current())

    async def test_extra_or_missing_arguments_refuse_before_body(self):
        for args, kwargs in (((), {}), ((ACK_ID, "extra"), {}),
                             ((ACK_ID,), {"acknowledgement_id": ACK_ID}),
                             ((), {"acknowledgement_id": ACK_ID, "consent": True})):
            result = await self.plugin.acknowledge_supervised_tv_switch(*args, **kwargs)
            self.assertEqual("build_profile.feature_unavailable", result["code"])
        self.plugin._presentation_transition_service.assert_not_called()

    async def test_inflight_transition_refuses_without_clearing_or_rearming(self):
        original = retained()
        self.store.save(original)
        self.service._lock.acquire()
        try:
            result = await self.plugin.acknowledge_supervised_tv_switch(ACK_ID)
        finally:
            self.service._lock.release()
        self.assertFalse(result.get("acknowledged"), result)
        self.assertEqual(self.store.load_current(), original)
        self.plugin._automatic_dock.reset_after_acknowledgement.assert_not_called()
        self.plugin._topology_wakeup.invalidate.assert_not_called()

    async def test_existing_audio_guard_refuses_without_clearing(self):
        original = retained()
        self.store.save(original)
        audio = Mock()
        audio.recovery_status.return_value = "audio.recovery_required"
        audio.transition_guard.side_effect = AudioRecoveryBlocked("audio.recovery_required")
        self.service._audio_recovery = audio
        result = await self.plugin.acknowledge_supervised_tv_switch(ACK_ID)
        self.assertFalse(result.get("acknowledged"), result)
        self.assertEqual(self.store.load_current(), original)
        self.plugin._automatic_dock.reset_after_acknowledgement.assert_not_called()

    async def test_journal_clear_error_preserves_result_and_does_not_rearm(self):
        original = retained()
        self.store.save(original)
        with patch.object(self.store, "clear_terminal", side_effect=OSError("journal unavailable")):
            result = await self.plugin.acknowledge_supervised_tv_switch(ACK_ID)
        self.assertFalse(result.get("acknowledged"), result)
        self.assertEqual(self.store.load_current(), original)
        self.plugin._automatic_dock.reset_after_acknowledgement.assert_not_called()
        self.plugin._topology_wakeup.invalidate.assert_not_called()

    def test_policy_admits_only_exact_acknowledgement_contract(self):
        self.assertTrue(rpc_allowed("production", "acknowledge_supervised_tv_switch",
                                    {"acknowledgement_id": ACK_ID}))
        for value in (None, False, [], "", "invalid", "a" * 7, "a" * 65):
            self.assertFalse(rpc_allowed("production", "acknowledge_supervised_tv_switch",
                                         {"acknowledgement_id": value}))
        self.assertFalse(rpc_allowed("unknown", "acknowledge_supervised_tv_switch",
                                     {"acknowledgement_id": ACK_ID}))


if __name__ == "__main__":
    unittest.main()
