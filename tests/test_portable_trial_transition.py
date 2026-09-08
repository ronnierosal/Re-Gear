import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_presentation_transition import (
    BOOT_ID, USER, FakeCommands, FakeIntegration, binding, observed,
    GamescopeUserResolution, PresentationTransitionMechanism,
)
from test_supervised_transition import Observations, VersionedObservation, service, snapshot
from hdm.domain.control_plane import PlacementState, PlannedStep, TransitionStepCode
from hdm.delivery.presentation_config import PresentationConfigStore
from hdm.delivery.portable_trial_store import PortableTrialStore


class TrialApprovalTests(unittest.TestCase):
    def test_trial_token_routes_once_and_does_not_claim_application(self):
        observation = VersionedObservation('generation-1', snapshot('tv-docked.json'))
        value, orchestrator, _ = service(Observations(observation, observation))
        calls = []
        def trial_runner(plan, engine):
            calls.append(plan.plan_id)
            return engine.run(plan)
        value._portable_trial_runner = trial_runner
        preview = value.preview(PlacementState.PORTABLE, user_confirmed=True, portable_vulkan_trial=True)
        self.assertTrue(preview.ready, preview.blockers)
        result = value.execute(preview.approval_token)
        self.assertTrue(result.accepted)
        self.assertEqual(result.code, 'portable_trial.application_unverified')
        self.assertEqual(len(calls), 1)
        self.assertFalse(value.execute(preview.approval_token).accepted)

    def test_normal_and_automatic_portable_never_call_trial_runner(self):
        for automatic in (False, True):
            with self.subTest(automatic=automatic):
                observation = VersionedObservation('generation-1', snapshot('tv-docked.json'))
                value, _, _ = service(Observations(observation, observation))
                value._portable_trial_runner = lambda *args: self.fail('normal path entered trial')
                if automatic:
                    result = value.execute_automatic(PlacementState.PORTABLE,
                        expected_generation='generation-1', standing_consent=True)
                else:
                    token = value.preview(PlacementState.PORTABLE, user_confirmed=True).approval_token
                    result = value.execute(token)
                self.assertTrue(result.accepted)

    def test_trial_rejects_changed_generation_and_already_portable(self):
        before = VersionedObservation('generation-1', snapshot('tv-docked.json'))
        after = VersionedObservation('generation-2', snapshot('tv-docked.json'))
        value, _, _ = service(Observations(before, after))
        value._portable_trial_runner = lambda *args: self.fail('stale trial ran')
        token = value.preview(PlacementState.PORTABLE, user_confirmed=True,
                              portable_vulkan_trial=True).approval_token
        self.assertEqual(value.execute(token).code, 'transition.evidence_changed')
        value, _, _ = service(Observations(VersionedObservation('generation-1', snapshot())))
        value._portable_trial_runner = lambda *args: None
        self.assertFalse(value.preview(PlacementState.PORTABLE, user_confirmed=True,
                                       portable_vulkan_trial=True).ready)


class TrialMechanismTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = PresentationConfigStore(self.root)
        self.store = PortableTrialStore(self.root)
        self.source = observed('tv-docked.json')
        self.original = self.config.write_target(target=PlacementState.DOCKED_EGPU,
            binding=binding(), snapshot=self.source, boot_id=BOOT_ID)
        self.events = []
        self.mechanism = PresentationTransitionMechanism(
            integration=FakeIntegration(events=self.events), config=self.config,
            commands=FakeCommands(self.events),
            resolve_user=lambda: GamescopeUserResolution(USER), read_boot_id=lambda: BOOT_ID,
            trial_store=self.store, active_operation=lambda: 'operation-1', trial_layer_ready=lambda: True)
        self.plan = SimpleNamespace(plan_id='operation-1', observed_generation='generation-1')
        self.step = PlannedStep(TransitionStepCode.PRESENTATION_RESTORE_PORTABLE,
                                10000, expected_placement=PlacementState.PORTABLE)

    def run_trial(self):
        def run(plan, **kwargs):
            self.assertTrue(kwargs['portable_vulkan_trial'])
            return self.mechanism.apply(self.step, binding(), self.source)
        return self.mechanism.run_portable_trial(self.plan, SimpleNamespace(run=run))

    def test_original_is_durable_before_config_write_and_restart(self):
        original_write = self.config.write_target
        def write(**kwargs):
            record = self.store.read()
            self.assertIsNotNone(record)
            self.assertEqual(record['original_config']['target'], 'docked_egpu')
            self.assertEqual(self.config.load(), self.original)
            return original_write(**kwargs)
        self.config.write_target = write
        self.assertTrue(self.run_trial().succeeded)
        self.assertEqual(self.config.load().target, 'portable')
        self.assertIsNone(self.store.consume())

    def test_restart_failure_restores_exact_original_and_burns_trial(self):
        from hdm.ports.presentation_activation import UserServiceOperation
        self.mechanism._commands = FakeCommands(self.events, (UserServiceOperation.RESTART_GAMESCOPE_SESSION,))
        self.assertFalse(self.run_trial().succeeded)
        self.assertEqual(self.config.load(), self.original)
        self.assertIsNone(self.store.consume())

    def test_missing_layer_does_not_write_config_or_restart(self):
        self.mechanism._trial_layer_ready = lambda: False
        self.assertFalse(self.run_trial().succeeded)
        self.assertEqual(self.config.load(), self.original)
        self.assertIsNone(self.store.read())
        self.assertNotIn('command.restart_gamescope_session', self.events)

    def test_normal_recovery_ignores_corrupt_unrelated_trial(self):
        (self.root / 'portable-vulkan-trial.json').write_text('corrupt')
        self.mechanism._active_operation = lambda: ''
        result = self.mechanism.recover(PlacementState.DOCKED_EGPU, binding(), self.source)
        self.assertTrue(result.succeeded)

    def test_interrupted_recovery_cancels_trial_even_without_observation(self):
        import hashlib
        expected = self.config.build_target(target=PlacementState.PORTABLE,
            binding=binding(), snapshot=self.source, boot_id=BOOT_ID)
        self.store.arm(operation_id='operation-1', generation='generation-1',
            boot_id_sha256=hashlib.sha256(BOOT_ID.encode()).hexdigest(),
            internal_gpu='1002:0000', internal_connector=expected.internal_connector,
            egpu_binding_sha256='b' * 64, original_config=self.original,
            expected_config=expected, expires_at=100)
        self.config.restore(expected)
        result = self.mechanism.recover(PlacementState.DOCKED_EGPU, binding(), None)
        self.assertFalse(result.succeeded)
        self.assertIsNone(self.store.consume())
        self.assertEqual(self.config.load(), expected)


if __name__ == '__main__':
    unittest.main()
