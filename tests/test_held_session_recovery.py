"""Recovery integration over real Linux journals/masks and fake user commands."""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery.held_session_recovery import recover
from regear.delivery.runtime_mask_lease import MaskLeaseIntent, MaskLeaseJournal, RuntimeMaskLease, UNITS


@unittest.skipUnless(sys.platform == 'linux', 'Linux journal and mask descriptors')
class HeldSessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.units = self.root / 'units'
        self.private = self.root / 'lease'
        self.units.mkdir(mode=0o700)
        self.private.mkdir(mode=0o700)
        self.ufd = os.open(self.units, os.O_RDONLY | os.O_DIRECTORY)
        self.lfd = os.open(self.private, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.ufd)
        self.addCleanup(os.close, self.lfd)
        self.journal = MaskLeaseJournal(self.lfd, owner_uid=os.geteuid())
        self.masks = RuntimeMaskLease(self.ufd, self.lfd, owner_uid=os.geteuid())
        self.addCleanup(self.journal.close)
        self.addCleanup(self.masks.close)
        self.intent = MaskLeaseIntent('a' * 32, 'b' * 64,
                                     ('pipewire.socket', 'gamescope-session.target'))
        with self.journal.locked():
            self.journal.create_intent(self.intent)
            self.records = [self.masks.create(unit, self.intent.token,
                lambda identity: self.journal.record_mask(self.intent, identity))
                for unit in sorted(UNITS)]
        self.calls = []
        self.states = {unit: 'inactive' for unit in UNITS}
        self.failure = None
        self.fake = type('FakeCommands', (), {'run': lambda _, *args: self.command(*args)})()

    def command(self, action, unit=None):
        self.calls.append((action, unit))
        # Even first command must run after the durable revocation marker.
        self.assertTrue((self.private / 'recovering.json').is_file())
        if (action, unit) == self.failure:
            return False
        if action == 'start':
            self.assertFalse(os.path.lexists(self.units / unit))
            self.states[unit] = 'active'
        if action == 'state':
            return self.states[unit]
        return True

    def run_recovery(self, **overrides):
        args = dict(units_fd=self.ufd, lease_fd=self.lfd, uid=os.geteuid(),
                    token=self.intent.token, boot_identity=self.intent.boot_identity,
                    commands=self.fake)
        args.update(overrides)
        return recover(**args)

    def test_restores_masks_and_only_prior_active_units_then_finishes(self):
        result = self.run_recovery()
        self.assertEqual(result.code, 'held_recovery.restored')
        self.assertTrue(result.restored)
        self.assertFalse(result.journal_retained)
        self.assertFalse(result.safe_to_unplug)
        self.assertEqual([unit for action, unit in self.calls if action == 'start'],
                         ['pipewire.socket', 'gamescope-session.target'])
        self.assertEqual(list(self.units.iterdir()), [])
        self.assertTrue((self.private / 'finished.json').is_file())
        with self.journal.locked():
            with self.assertRaises(ValueError):
                self.journal.record_mask(self.intent, self.records[0])

    def test_token_or_boot_mismatch_does_not_revoke_or_modify(self):
        for overrides in ({'token': 'c' * 32}, {'boot_identity': 'd' * 64}):
            with self.subTest(overrides=overrides):
                result = self.run_recovery(**overrides)
                self.assertEqual(result.code, 'held_recovery.identity_changed')
                self.assertEqual(self.calls, [])
                self.assertFalse((self.private / 'recovering.json').exists())
                self.assertEqual(len(list(self.units.iterdir())), len(UNITS))

    def test_foreign_mask_preserved_other_owned_masks_cleaned(self):
        foreign = self.units / 'pipewire.service'
        foreign.unlink()
        foreign.write_text('foreign unit')
        result = self.run_recovery()
        self.assertEqual(result.code, 'held_recovery.masks_unverified')
        self.assertTrue(result.journal_retained)
        self.assertEqual(foreign.read_text(), 'foreign unit')
        self.assertEqual(list(self.units.iterdir()), [foreign])
        self.assertEqual(self.calls, [])
        self.assertTrue((self.private / 'recovering.json').is_file())
        self.assertFalse((self.private / 'finished.json').exists())

    def test_reload_failure_retains_revocation_and_no_starts(self):
        self.failure = ('reload', None)
        result = self.run_recovery()
        self.assertEqual(result.code, 'held_recovery.reload_unverified')
        self.assertEqual(self.calls, [('reload', None)])
        self.assertFalse((self.private / 'finished.json').exists())
        with self.journal.locked():
            with self.assertRaises(ValueError):
                self.journal.record_mask(self.intent, self.records[0])

    def test_unexpected_active_prior_inactive_unit_prevents_finish(self):
        self.states['wireplumber.service'] = 'active'
        result = self.run_recovery()
        self.assertEqual(result.code, 'held_recovery.state_unverified')
        self.assertFalse(result.restored)
        self.assertFalse((self.private / 'finished.json').exists())
        self.assertNotIn(('start', 'wireplumber.service'), self.calls)

    def test_interrupted_recovery_marker_can_resume(self):
        with self.journal.locked():
            self.journal.begin_recovery(self.intent)
        result = self.run_recovery()
        self.assertEqual(result.code, 'held_recovery.restored')

    def test_completed_recovery_only_verifies_without_replaying_commands(self):
        self.assertEqual(self.run_recovery().code, 'held_recovery.restored')
        self.calls.clear()
        result = self.run_recovery()
        self.assertEqual(result.code, 'held_recovery.already_restored')
        self.assertTrue(result.restored)
        self.assertFalse(result.journal_retained)
        self.assertEqual(len(self.calls), len(UNITS))
        self.assertTrue(all(action == 'state' for action, unit in self.calls))

    def test_competing_recovery_lock_prevents_commands(self):
        with self.journal.recovery_locked():
            result = self.run_recovery()
        self.assertEqual(result.code, 'held_recovery.unavailable')
        self.assertEqual(self.calls, [])
        self.assertFalse((self.private / 'recovering.json').exists())
        self.assertEqual(len(list(self.units.iterdir())), len(UNITS))

    def test_changed_state_during_finish_keeps_journal_unfinished(self):
        state_calls = []
        original = self.fake.run
        def changing(action, unit=None):
            if action == 'state':
                state_calls.append(unit)
                if len(state_calls) > len(UNITS):
                    self.states['gamescope-session.target'] = 'inactive'
            return original(action, unit)
        self.fake.run = changing
        result = self.run_recovery()
        self.assertTrue(result.journal_retained)
        self.assertGreater(len(state_calls), len(UNITS))
        self.assertFalse((self.private / 'finished.json').exists())


if __name__ == '__main__':
    unittest.main()
