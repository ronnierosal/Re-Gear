from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.hdm.delivery.device_filter_arm import FilterArm
from backend.hdm.delivery.device_filter_trial_owner_store import (
    TrialOwnerStore, build_trial_owner_record, _encode, _decode)
from backend.hdm.delivery.device_filter_trial_config import render_trial_dropin
from backend.hdm.ports.presentation_activation import GamescopeUserContext
from tests.test_device_filter_runtime_store import bundle


def record():
    arm = FilterArm(1, 'trial-1', 'gamescope-session.service', 1000,
                    'a' * 64, 'b' * 64, 'c' * 64, 'd' * 32, 190.0)
    user = GamescopeUserContext('deck', 1000, 1000, Path('/home/deck'),
                               Path('/run/user/1000'), Path('/run/user/1000/bus'))
    runtime = bundle()
    return build_trial_owner_record(arm, user, runtime,
        candidate=render_trial_dropin(runtime, arm.unit, user=user).content,
        legacy_original=b'original\xff')


class OwnerEncodingTests(unittest.TestCase):
    def test_roundtrip_exact_and_nonverified(self):
        original = record()
        self.assertEqual(_decode(_encode(original)), original)
        self.assertFalse(original.hardware_verified)

    def test_wrong_candidate_and_user_rejected(self):
        original = record()
        with self.assertRaises(ValueError):
            build_trial_owner_record(original.arm, original.user, bundle(),
                                     candidate=b'other', legacy_original=None)
        with self.assertRaises(ValueError):
            _encode(replace(original, user=replace(original.user, uid=1001)))

    def test_terminal_is_not_hardware_verification(self):
        original = record()
        terminal = replace(original, phase='restart_requested', recovery_from='scheduling')
        self.assertFalse(_decode(_encode(terminal)).hardware_verified)
        for changed in (replace(original, phase='completed'), replace(original, hardware_verified=True)):
            with self.assertRaises(ValueError):
                _encode(changed)

    def test_recovery_origin_mandatory_only_after_recovery(self):
        original = record()
        for changed in (replace(original, recovery_from='prepared'),
                        replace(original, phase='recovering'),
                        replace(original, phase='recovering', recovery_from='recovering')):
            with self.assertRaises(ValueError):
                _encode(changed)
        valid = replace(original, phase='recovering', recovery_from='dropin_applying')
        self.assertEqual(_decode(_encode(valid)), valid)

    def test_duplicate_and_boolean_schema_rejected(self):
        raw = _encode(record())
        with self.assertRaises(ValueError):
            _decode(raw[:-1] + b',"schema":1}')
        parsed = json.loads(raw)
        parsed['schema'] = True
        with self.assertRaises(ValueError):
            _decode(json.dumps(parsed).encode())


@unittest.skipUnless(sys.platform == 'linux', 'Linux durable owner fixture')
class OwnerStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.store = TrialOwnerStore(owner_uid=os.getuid(), trusted_directory_fd=self.fd)
        self.record = record()
        self.operation, self.unit = self.record.arm.operation, self.record.arm.unit

    def step(self, current, next_phase):
        return self.store.transition(self.operation, self.unit, current.phase,
                                     next_phase, expected_record=current)

    def test_exclusive_create_and_read(self):
        self.assertIsNone(self.store.read(self.operation, self.unit))
        self.store.create(self.record)
        self.assertEqual(self.store.read(self.operation, self.unit), self.record)
        with self.assertRaises(FileExistsError):
            self.store.create(self.record)

    def test_phase_progression_and_no_schedule_replay(self):
        self.store.create(self.record)
        current = self.record
        for phase in ('legacy_suspending', 'dropin_applying', 'arming'):
            current = self.step(current, phase)
        scheduling = self.step(current, 'scheduling')
        with self.assertRaises(ValueError):
            self.step(self.record, 'scheduling')
        recovering = self.step(scheduling, 'recovering')
        terminal = self.step(recovering, 'restart_requested')
        self.assertFalse(terminal.hardware_verified)
        self.assertEqual(terminal.recovery_from, 'scheduling')
        self.assertEqual(self.store.read(self.operation, self.unit), terminal)
        with self.assertRaises(ValueError):
            self.step(terminal, 'scheduling')

    def test_each_partial_setup_phase_can_recover(self):
        for phase in ('legacy_suspending', 'dropin_applying', 'arming'):
            other = replace(self.record, arm=replace(self.record.arm, operation='trial-' + phase))
            self.store.create(other)
            current = other
            for next_phase in ('legacy_suspending', 'dropin_applying', 'arming'):
                current = self.store.transition(current.arm.operation, self.unit, current.phase,
                    next_phase, expected_record=current)
                if next_phase == phase:
                    break
            result = self.store.transition(current.arm.operation, self.unit, phase,
                'recovering', expected_record=current)
            self.assertEqual(result.phase, 'recovering')
            self.assertEqual(result.recovery_from, phase)
            self.assertEqual(self.store.read(current.arm.operation, self.unit), result)

    def test_direct_recovery_before_scheduling(self):
        self.store.create(self.record)
        recovered = self.step(self.record, 'recovering')
        self.assertEqual(recovered.phase, 'recovering')
        self.assertEqual(recovered.recovery_from, 'prepared')
        self.assertEqual(self.store.read(self.operation, self.unit), recovered)

    def test_immutable_binding_cas(self):
        self.store.create(self.record)
        with self.assertRaises(ValueError):
            self.step(replace(self.record, legacy_original=b'changed'), 'legacy_suspending')
        self.assertEqual(self.store.read(self.operation, self.unit), self.record)

    def test_uncertain_write_read_does_not_reauthorize_schedule(self):
        self.store.create(self.record)
        current = self.record
        for phase in ('legacy_suspending', 'dropin_applying', 'arming'):
            current = self.step(current, phase)
        write = self.store._write
        def fail_after_write(*args, **kwargs):
            write(*args, **kwargs)
            raise OSError('injected post-publication failure')
        with patch.object(self.store, '_write', side_effect=fail_after_write):
            with self.assertRaises(OSError):
                self.step(current, 'scheduling')
        observed = self.store.read(self.operation, self.unit)
        self.assertEqual(observed.phase, 'scheduling')
        with self.assertRaises(ValueError):
            self.step(self.record, 'scheduling')
        self.step(observed, 'recovering')

    def test_symlink_checkpoint_rejected(self):
        outside = self.root / 'outside'
        outside.write_bytes(_encode(self.record))
        name = self.store._name(self.operation, self.unit)
        (self.root / name).symlink_to(outside)
        with self.assertRaises(OSError):
            self.store.read(self.operation, self.unit)
