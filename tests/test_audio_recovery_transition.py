"""Real audio controller plus supervised service; commands are simulated."""
import threading
import unittest
from dataclasses import replace
from contextlib import contextmanager

from tests import test_audio_profile_trial as audio_fixture
from hdm.delivery.audio_profile_trial import AudioProfileRecovery
from hdm.delivery.audio_profile_trial_state import AudioTrialPhase as Phase
from tests.test_supervised_transition import service, Observations, PlacementState
from hdm.ports.audio_recovery import AudioRecoveryBlocked


class AudioRecoveryTransitionTests(unittest.TestCase):
    def setUp(self):
        self.audio = audio_fixture.AudioProfileTrialTests()
        self.audio.setUp()
        self.audio.prepare_restore()
        store = self.audio.store
        lock = threading.Lock()
        @contextmanager
        def transaction():
            if not lock.acquire(blocking=False):
                raise TimeoutError('audio transaction busy')
            try:
                yield store
            finally:
                lock.release()
        def pending():
            records = [r for r in store.records.values() if r.phase is not Phase.RESTORED]
            if len(records) > 1:
                raise ValueError('multiple active')
            return records[0] if records else None
        store.transaction = transaction
        store.pending = pending
        self.value, self.orchestrator, self.journal = service(Observations())
        self.recovery = AudioProfileRecovery(store, lambda record, deadline: self.audio.trial,
                                             clock=lambda: self.audio.now)
        self.value._audio_recovery = self.recovery

    def test_restore_observed_and_persisted_before_presentation(self):
        original = self.orchestrator.recover_interrupted
        def presentation():
            self.assertEqual(self.audio.current, self.audio.store.read('trial').original_profile)
            self.assertEqual(self.audio.store.read('trial').phase, Phase.RESTORED)
            with self.assertRaises(TimeoutError):
                with self.audio.store.transaction():
                    self.fail('audio lock released before presentation')
            return original()
        self.orchestrator.recover_interrupted = presentation
        self.value.recover_interrupted()
        self.assertEqual(self.orchestrator.recoveries, 1)
        self.assertEqual(len(self.audio.calls), 1)
        self.value.recover_interrupted()
        self.assertEqual(len(self.audio.calls), 1)

    def test_unknown_portable_or_changed_identity_blocks_all_presentation_commands(self):
        for changes in ({'portable_ready': False}, {'no_game': False}, {'boot_hash': 'c'*64},
                        {'topology_hash': 'd'*64}, {'portable_sink': 'other'}):
            with self.subTest(changes=changes):
                self.audio.observation_changes = changes
                result = self.value.recover_interrupted()
                self.assertEqual(result.outcome.failure.code, 'audio.recovery_unavailable')
                self.assertEqual(self.orchestrator.recoveries, 0)
                self.assertTrue(self.audio.store.pending())
        self.assertEqual(self.audio.calls, [])

    def test_uncertain_restore_command_never_runs_presentation(self):
        self.audio.command_ok = False
        result = self.value.recover_interrupted()
        self.assertEqual(result.outcome.failure.code, 'audio.recovery_unavailable')
        self.assertEqual(self.orchestrator.recoveries, 0)
        self.assertEqual(self.audio.store.read('trial').phase, Phase.RECOVERY_REQUIRED)
        self.audio.command_ok = True
        self.value.recover_interrupted()
        self.assertEqual(self.orchestrator.recoveries, 1)
        self.assertEqual(len(self.audio.calls), 1)  # Applied command reconciles, never replays.

    def test_pending_blocks_normal_paths_without_implicit_restoration(self):
        self.assertEqual(self.value.execute('unused').code, 'audio.recovery_required')
        self.assertEqual(self.value.execute_automatic(PlacementState.DOCKED_EGPU,
            expected_generation='generation', standing_consent=True).code, 'audio.recovery_required')
        self.assertFalse(self.value.acknowledge('operation-0001'))
        self.assertEqual(self.value.reconcile_completion(None).code, 'audio.recovery_required')
        self.assertEqual(self.audio.calls, [])
        self.assertEqual(self.orchestrator.plans, [])

    def test_service_reconstruction_preserves_pending_gate(self):
        fresh, orchestrator, _ = service(Observations())
        fresh._audio_recovery = self.recovery
        self.assertEqual(fresh.status().code, 'audio.recovery_required')
        self.assertEqual(fresh.execute('unused').code, 'audio.recovery_required')
        self.assertEqual(orchestrator.plans, [])
        self.assertEqual(self.audio.calls, [])

    def test_malformed_journal_blocks_recovery(self):
        def invalid():
            raise ValueError('malformed record')
        self.audio.store.pending = invalid
        self.assertEqual(self.value.status().code, 'audio.recovery_unavailable')
        result = self.value.recover_interrupted()
        self.assertEqual(result.outcome.failure.code, 'audio.recovery_unavailable')
        self.assertEqual(self.orchestrator.recoveries, 0)
        self.assertEqual(self.audio.calls, [])

    def test_presentation_exception_does_not_rearm_audio_or_leak_lock(self):
        def failed():
            raise OSError('presentation failed')
        self.orchestrator.recover_interrupted = failed
        with self.assertRaises(OSError):
            self.value.recover_interrupted()
        self.assertEqual(self.audio.store.read('trial').phase, Phase.RESTORED)
        with self.recovery.transition_guard():
            pass
        self.assertEqual(self.value.execute('invalid').code, 'transition.approval_invalid')

    def test_competing_off_cannot_enter_during_presentation(self):
        original = self.orchestrator.recover_interrupted
        failures = []
        def competitor():
            try:
                self.audio.off()
            except TimeoutError:
                failures.append('blocked')
        def presentation():
            thread = threading.Thread(target=competitor)
            thread.start()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            return original()
        self.orchestrator.recover_interrupted = presentation
        self.value.recover_interrupted()
        self.assertEqual(failures, ['blocked'])
        self.assertEqual(len(self.audio.calls), 1)
        self.assertEqual(self.audio.store.read('trial').phase, Phase.RESTORED)

    def test_retry_requests_fresh_observer_deadline(self):
        deadlines = []
        def factory(record, deadline):
            deadlines.append(deadline)
            return self.audio.trial
        self.recovery.trial_factory = factory
        self.audio.observation_changes = {'portable_ready': False}
        self.value.recover_interrupted()
        self.audio.now = 100.0
        self.audio.observation_changes = {}
        self.value.recover_interrupted()
        self.assertEqual(deadlines, [20.0, 110.0])
        self.assertEqual(self.orchestrator.recoveries, 1)

    def test_factory_cannot_use_another_journal(self):
        other = audio_fixture.AudioProfileTrialTests()
        other.setUp()
        self.recovery.trial_factory = lambda record, deadline: other.trial
        result = self.value.recover_interrupted()
        self.assertEqual(result.outcome.failure.code, 'audio.recovery_unavailable')
        self.assertEqual(self.orchestrator.recoveries, 0)
        self.assertEqual(self.audio.calls, [])


if __name__ == '__main__':
    unittest.main()
