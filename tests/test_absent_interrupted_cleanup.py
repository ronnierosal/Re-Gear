"""Physical absence must not require rediscovering the unplugged router."""
import unittest
import sys
import json
from unittest.mock import Mock

from tests import test_main_dock_mutation_gate as support
from regear.delivery.whole_dock_claim import WholeDockClaim, WholeDockClaimStore
from tests import test_dock_power_intent as intent_support


class InterruptedAbsenceTests(unittest.TestCase):
    def fixture(self, **options):
        case = support.CompletedAttachmentAbsenceTests()
        case.setUp()
        result = case.fixture(stage='tunnel_remove_intent', **options)
        return case, result

    def test_absent_interrupted_claim_archives_without_attached_completion(self):
        case, result = self.fixture()
        self.assertEqual(result, (True, 1))
        case.plugin._complete_interrupted_whole_dock_trial.assert_not_called()

    def test_attached_or_unknown_transport_retains_interrupted_claim(self):
        for options in ({'absent': False}, {'strict': False}, {'settled': False},
                        {'parent_power': True}, {'changed': True}):
            with self.subTest(options=options):
                case, result = self.fixture(**options)
                self.assertFalse(result[0])
                case.plugin._complete_interrupted_whole_dock_trial.assert_not_called()

    def test_archive_preserves_interrupted_stage_and_distinct_audit_name(self):
        store = object.__new__(WholeDockClaimStore)
        store._retire_observed = Mock(return_value=True)
        claim = WholeDockClaim('operation', 'binding', 'generation', 'tunnel_remove_intent')
        guard = Mock(return_value=True)
        store.retire_physically_disconnected(claim, guard)
        store._retire_observed.assert_called_once_with(
            claim, guard, guard, 'interrupted-absent-dock-')
        self.assertEqual(claim.stage, 'tunnel_remove_intent')


@unittest.skipUnless(sys.platform == 'linux', 'Linux durable filesystem required')
class InterruptedAbsenceFilesystemTests(unittest.TestCase):
    setUp = intent_support.IntentFilesystemTests.setUp
    tearDown = intent_support.IntentFilesystemTests.tearDown

    def interrupted(self, action='sleep'):
        args = list(intent_support.ARGS)
        args[3] = action
        args[4] = '1' * 64 + ':' + 'a' * 32
        self.assertTrue(self.store.bind(*args))
        self.claim.record(args[0], 'tunnel_remove_intent')
        return self.claim.load(), args[4]

    def test_dead_sleep_cleanup_preserves_failure_audit_and_rearms_admission(self):
        claim, _ = self.interrupted()
        self.assertTrue(self.store.reconcile_stranded_sleep(claim, None, lambda: True))
        audit = self.store.retire_physically_disconnected(
            claim, lambda: self.store.power_intent_absent(claim))
        self.assertTrue(audit.startswith('interrupted-absent-dock-'))
        self.assertEqual(json.loads((self.root / audit).read_text())['stage'],
                         'tunnel_remove_intent')
        self.assertTrue(self.claim.claim('next', 'dock', 'new-generation'))

    def test_live_sleep_and_failed_absence_keep_intent(self):
        claim, session = self.interrupted()
        self.assertFalse(self.store.reconcile_stranded_sleep(claim, session, lambda: True))
        self.assertFalse(self.store.reconcile_stranded_sleep(claim, None, lambda: False))
        self.assertFalse(self.store.power_intent_absent(claim))
        self.assertEqual(self.claim.load(), claim)

    def test_interrupted_shutdown_is_not_discarded(self):
        claim, _ = self.interrupted(action='shutdown')
        self.assertFalse(self.store.reconcile_stranded_sleep(claim, None, lambda: True))
        self.assertFalse(self.store.power_intent_absent(claim))

    def test_reconnect_during_archive_keeps_inhibition(self):
        claim, _ = self.interrupted()
        self.assertTrue(self.store.reconcile_stranded_sleep(claim, None, lambda: True))
        with self.assertRaises(ValueError):
            self.store.retire_physically_disconnected(claim, Mock(side_effect=[True, False]))
        self.assertEqual(self.claim.load(), claim)
        self.assertTrue(self.claim.inhibited())
