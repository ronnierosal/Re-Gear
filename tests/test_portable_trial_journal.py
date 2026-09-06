import tempfile
import unittest
from pathlib import Path

from test_transition_orchestrator import (
    FakeClockWaiter, FakeMechanism, ScriptedObservations, orchestrator,
    observation, snapshot, resolve_runtime_profiles, evidence_from_snapshot,
    plan_manual_transition, ExperimentalTransitionPermit, PlacementState,
    TransitionOutcomeKind,
)
from hdm.application.supervised_transition import SupervisedPresentationTransitionService
from hdm.application.presentation_completion import reconcile_presentation_completion
from hdm.delivery.transition_journal_store import FileTransitionJournalStore


class PortableTrialJournalTests(unittest.TestCase):
    def run_transition(self, trial):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = snapshot('tv-docked.json')
        portable = snapshot('connected-internal.json')
        capabilities = resolve_runtime_profiles(source).capabilities
        evidence = evidence_from_snapshot(source, observed_generation='generation-1', capabilities=capabilities)
        permit = ExperimentalTransitionPermit('permit-123', 'operation-123', 'generation-1',
            PlacementState.PORTABLE, capabilities.host_profile_id, capabilities.egpu_profile_id,
            evidence.egpu_stable_id, portable_vulkan_trial=trial)
        decision = plan_manual_transition(plan_id='operation-123', request_id='request-123',
            current=PlacementState.DOCKED_EGPU, target=PlacementState.PORTABLE,
            capabilities=capabilities, evidence=evidence, experimental_permit=permit)
        self.assertIsNotNone(decision.plan, decision.blockers)
        clock = FakeClockWaiter()
        engine = orchestrator(ScriptedObservations(
            observation('generation-1', source), observation('generation-1b', source),
            observation('generation-2', portable)), FakeMechanism(clock), FileTransitionJournalStore(root), clock)
        result = engine.run(decision.plan, portable_vulkan_trial=trial)
        self.assertEqual(result.outcome.kind, TransitionOutcomeKind.SUCCEEDED, result)
        self.assertTrue(result.durable)
        return FileTransitionJournalStore(root), observation('generation-2', portable)

    def test_trial_metadata_survives_reload_and_status_is_unverified(self):
        store, _ = self.run_transition(True)
        journal = store.load_current()
        self.assertEqual(dict(journal.entries[0].details)['launch_policy'], 'portable_vulkan_trial')
        service = SupervisedPresentationTransitionService(observations=None, orchestrator=None,
            journal_store=store, integration_ready=lambda: True)
        status = service.status()
        self.assertEqual(status.code, 'portable_trial.application_unverified')
        self.assertTrue(status.acknowledgement_required)
        self.assertEqual(status.operation_id, 'operation-123')

    def test_trial_completion_holds_and_does_not_retire(self):
        store, current = self.run_transition(True)
        original = store.load_current()
        result = reconcile_presentation_completion(store, current)
        self.assertTrue(result.hold_portable)
        self.assertFalse(result.finalized)
        self.assertEqual(result.code, 'completion.explicit_result_required')
        self.assertEqual(store.load_current(), original)
        self.assertIsNone(store.load_completed())

    def test_normal_journal_has_no_trial_policy_or_trial_status(self):
        store, current = self.run_transition(False)
        self.assertNotIn('launch_policy', dict(store.load_current().entries[0].details))
        service = SupervisedPresentationTransitionService(observations=None, orchestrator=None,
            journal_store=store, integration_ready=lambda: True)
        self.assertEqual(service.status().code, 'transition.committed')
        completion = reconcile_presentation_completion(store, current)
        self.assertTrue(completion.finalized)
        self.assertIsNone(store.load_current())
        self.assertIsNotNone(store.load_completed())


if __name__ == '__main__':
    unittest.main()
