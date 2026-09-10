from dataclasses import replace
from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.adapters.steamos.audio_profile_observation import AudioProfile, AudioProfileObservation
from hdm.adapters.steamos.commands import PipeWireCommandRunner
from hdm.delivery.audio_profile_trial import AudioProfileTrial, AudioTrialObservation
from hdm.delivery.audio_profile_trial_state import AudioTrialRecord, AudioTrialPhase as Phase


BOOT, TOPOLOGY = 'a' * 64, 'b' * 64
BDF, ORIGINAL, SINK = '0000:08:00.1', 'output:hdmi-stereo-extra1', 'portable.sink'


class FakeStore:
    def __init__(self):
        self.records = {}
        self.history = []
        self.fail_create = False
        self.fail_phase = None
        self.fail_after_publish_phase = None

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def create(self, record):
        if self.fail_create:
            raise OSError('durability failure')
        if record.operation in self.records:
            raise ValueError('existing operation')
        self.records[record.operation] = record
        self.history.append(record)

    def read(self, operation):
        return self.records[operation]

    def save(self, previous, updated):
        if (self.read(previous.operation) != previous or
                updated.revision != previous.revision + 1):
            raise ValueError('CAS mismatch')
        if updated.phase is self.fail_phase:
            raise OSError('phase durability failure')
        self.records[updated.operation] = updated
        self.history.append(updated)
        if updated.phase is self.fail_after_publish_phase:
            raise OSError('directory fsync failed after publish')


class AudioProfileTrialTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.now = 10.0
        self.current = ORIGINAL
        self.device_id = 42
        self.original_index = 2
        self.off_index = 0
        self.calls = []
        self.observation_changes = {}
        self.observe_count = 0
        self.observe_hook = None
        self.command_ok = True
        self.apply_command = True
        self.user = SimpleNamespace(uid=1000, username='deck')
        self.trial = AudioProfileTrial(self.store, self.user, self.observe,
            commands=SimpleNamespace(set_profile=self.set_profile),
            clock=lambda: self.now, wait=self.wait)

    def wait(self, amount):
        self.now += amount

    def observe(self):
        self.observe_count += 1
        if self.observe_hook:
            self.observe_hook(self.observe_count)
        original = AudioProfile(ORIGINAL, self.original_index, 'yes')
        off = AudioProfile('off', self.off_index, 'yes')
        current = original if self.current == ORIGINAL else off if self.current == 'off' else AudioProfile(self.current, 8, 'yes')
        profile = AudioProfileObservation(True, 'audio_profile.observed', BDF,
            self.device_id, current, off, (original, off, AudioProfile('external-change', 8, 'yes')))
        value = AudioTrialObservation(BOOT, TOPOLOGY, profile, SINK, True, True, self.now)
        return replace(value, **self.observation_changes)

    def set_profile(self, user, object_id, index, **kwargs):
        self.calls.append((object_id, index, self.store.read('trial').phase))
        if self.apply_command:
            self.current = 'off' if index == self.off_index else ORIGINAL
        return SimpleNamespace(ok=self.command_ok)

    def off(self, deadline=20.0):
        return self.trial.off('trial', boot_hash=BOOT, topology_hash=TOPOLOGY,
                              audio_bdf=BDF, portable_sink=SINK, deadline=deadline)

    def prepare_restore(self, phase=Phase.OFF_OBSERVED):
        self.store.create(AudioTrialRecord('trial', BOOT, TOPOLOGY, BDF,
                                           ORIGINAL, SINK, 1000, phase=phase))
        self.current = 'off'

    def test_original_and_off_requested_durable_before_command(self):
        result = self.off()
        self.assertEqual([r.phase for r in self.store.history],
                         [Phase.PREPARED, Phase.OFF_REQUESTED, Phase.OFF_OBSERVED])
        self.assertEqual(self.store.history[0].original_profile, ORIGINAL)
        self.assertEqual(self.calls, [(42, 0, Phase.OFF_REQUESTED)])
        self.assertFalse(result.resources_released)
        self.assertFalse(result.disconnect_clearance)

    def test_failed_durable_writes_prevent_command(self):
        self.store.fail_create = True
        with self.assertRaises(OSError): self.off()
        self.assertEqual(self.calls, [])
        self.store.fail_create = False
        self.store.fail_phase = Phase.OFF_REQUESTED
        with self.assertRaises(OSError): self.off()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.read('trial').phase, Phase.RECOVERY_REQUIRED)

    def test_uncertain_command_preserves_recovery_even_if_applied(self):
        self.command_ok = False
        with self.assertRaises(OSError): self.off()
        self.assertEqual(self.current, 'off')
        self.assertEqual(self.store.read('trial').phase, Phase.RECOVERY_REQUIRED)

    def test_published_revision_before_fsync_failure_recovers_actual_cas(self):
        self.store.fail_after_publish_phase = Phase.OFF_REQUESTED
        with self.assertRaises(OSError): self.off()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.read('trial').phase, Phase.RECOVERY_REQUIRED)
        self.assertEqual(self.store.read('trial').revision, 3)

    def test_uncertain_restore_preserves_recovery_and_reconciles(self):
        self.prepare_restore()
        self.command_ok = False
        with self.assertRaises(OSError): self.trial.restore('trial', deadline=20)
        self.assertEqual(self.current, ORIGINAL)
        self.assertEqual(self.store.read('trial').phase, Phase.RECOVERY_REQUIRED)
        result = self.trial.restore('trial', deadline=20)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result.record.phase, Phase.RESTORED)

    def test_second_restore_observation_rebinds_ephemeral_identifiers(self):
        self.prepare_restore()
        def change(count):
            if count == 2:
                self.device_id, self.original_index = 95, 19
        self.observe_hook = change
        self.trial.restore('trial', deadline=20)
        self.assertEqual(self.calls, [(95, 19, Phase.RESTORE_REQUESTED)])

    def test_unverified_readback_preserves_recovery(self):
        self.apply_command = False
        with self.assertRaises(TimeoutError): self.off(deadline=10.25)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.store.read('trial').phase, Phase.RECOVERY_REQUIRED)

    def test_restore_uses_fresh_device_and_named_profile_index(self):
        self.prepare_restore()
        self.device_id, self.original_index = 83, 17
        result = self.trial.restore('trial', deadline=20)
        self.assertEqual(self.calls, [(83, 17, Phase.RESTORE_REQUESTED)])
        self.assertEqual(result.record.phase, Phase.RESTORED)
        self.assertFalse(result.resources_released)

    def test_explicit_restore_from_prepared_off_completes_in_one_attempt(self):
        self.prepare_restore(Phase.PREPARED)
        result = self.trial.restore('trial', deadline=20)
        self.assertEqual(self.calls, [(42, 2, Phase.RESTORE_REQUESTED)])
        self.assertEqual(result.record.phase, Phase.RESTORED)

    @unittest.skipUnless(sys.platform == 'linux', 'actual audio journal dirfd integration')
    def test_real_store_off_restore_and_prepared_recovery(self):
        from hdm.delivery.audio_profile_trial_store import AudioTrialStore
        for prepared in (False, True):
            self.setUp()
            with tempfile.TemporaryDirectory() as root:
                fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    store = AudioTrialStore(owner_uid=os.getuid(), trusted_directory_fd=fd)
                    self.trial.store = store
                    def command(user, object_id, index, **kwargs):
                        self.current = 'off' if index == self.off_index else ORIGINAL
                        return SimpleNamespace(ok=True)
                    self.trial.commands = SimpleNamespace(set_profile=command)
                    if prepared:
                        with store.transaction() as tx:
                            tx.create(AudioTrialRecord('trial', BOOT, TOPOLOGY, BDF, ORIGINAL, SINK, 1000))
                        self.current = 'off'
                    else:
                        self.off()
                    self.trial.restore('trial', deadline=20)
                    with store.transaction() as tx:
                        self.assertEqual(tx.read('trial').phase, Phase.RESTORED)
                    with self.assertRaises(ValueError):
                        self.off()
                finally:
                    os.close(fd)

    def test_off_no_replay_and_restore_idempotent(self):
        self.off()
        self.trial.restore('trial', deadline=20)
        count = len(self.calls)
        self.trial.restore('trial', deadline=20)
        with self.assertRaises(ValueError): self.off()
        self.assertEqual(len(self.calls), count)

    def test_context_unknown_nonportable_stale_no_mutation(self):
        for change in ({'no_game': None}, {'no_game': 1}, {'portable_ready': False},
                       {'portable_ready': None}, {'boot_hash': 'c' * 64},
                       {'topology_hash': 'c' * 64}, {'portable_sink': 'other'},
                       {'observed_at': 9.0}, {'observed_at': float('nan')}):
            with self.subTest(change=change):
                self.observation_changes = change
                with self.assertRaises(ValueError): self.off()
                self.assertEqual(self.calls, [])
                self.assertEqual(self.store.history, [])

    def test_invalid_deadline_no_mutation(self):
        for deadline in (10, 41, True, float('nan'), float('inf')):
            with self.subTest(deadline=deadline):
                with self.assertRaises(TimeoutError): self.off(deadline)
                self.assertEqual(self.calls, [])

    def test_external_profile_change_before_off_not_overridden(self):
        self.observe_hook = lambda count: setattr(self, 'current', 'external-change') if count == 2 else None
        with self.assertRaises(ValueError): self.off()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.read('trial').phase, Phase.RECOVERY_REQUIRED)

    def test_restore_external_change_and_uid_mismatch_not_overridden(self):
        self.prepare_restore()
        self.current = 'external-change'
        with self.assertRaises(ValueError): self.trial.restore('trial', deadline=20)
        self.assertEqual(self.calls, [])
        self.current = 'off'
        self.user.uid = 1001
        with self.assertRaises(ValueError): self.trial.restore('trial', deadline=20)
        self.assertEqual(self.calls, [])

    def test_closed_trial_does_not_reapply_after_external_off(self):
        self.prepare_restore(Phase.RESTORED)
        with self.assertRaises(ValueError): self.trial.restore('trial', deadline=20)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.read('trial').phase, Phase.RESTORED)


class AudioProfileCommandTests(unittest.TestCase):
    def test_numeric_command_no_shell(self):
        runner = PipeWireCommandRunner(effective_uid=lambda: 0)
        with patch('hdm.adapters.steamos.commands.subprocess.run',
                   return_value=SimpleNamespace(stdout=b'', stderr=b'', returncode=0)) as run:
            self.assertTrue(runner.set_profile(SimpleNamespace(username='deck', uid=1000), 42, 0).ok)
        self.assertEqual(run.call_args.args[0][-4:], ('/usr/bin/wpctl', 'set-profile', '42', '0'))
        self.assertIs(run.call_args.kwargs['shell'], False)

    def test_explicit_profile_deadline_is_bounded_and_invalid_values_do_not_run(self):
        runner = PipeWireCommandRunner(effective_uid=lambda: 0)
        user = SimpleNamespace(username='deck', uid=1000)
        with patch('hdm.adapters.steamos.commands.subprocess.run',
                   return_value=SimpleNamespace(stdout=b'', stderr=b'', returncode=0)) as run:
            self.assertTrue(runner.set_profile(user, 42, 0, timeout_seconds=0.5).ok)
            self.assertEqual(run.call_args.kwargs['timeout'], 0.5)
            run.reset_mock()
            for timeout in (True, 0, -1, float('nan'), float('inf')):
                self.assertFalse(runner.set_profile(user, 42, 0, timeout_seconds=timeout).ok)
            run.assert_not_called()

    def test_invalid_numeric_arguments_never_execute(self):
        runner = PipeWireCommandRunner(effective_uid=lambda: 0)
        with patch('hdm.adapters.steamos.commands.subprocess.run') as run:
            for object_id, index in ((True, 0), (0, 0), ('42', 0), (42, True),
                                     (42, -1), (42, '0'), (2**32, 0), (42, 2**32)):
                self.assertFalse(runner.set_profile(SimpleNamespace(username='deck', uid=1000), object_id, index).ok)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
