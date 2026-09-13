"""Read-only suspend evidence using temporary counter fixtures."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.adapters.steamos.suspend_observer import (
    SuspendEvidence, SuspendObserver, classify_suspend)


class SuspendObserverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stats = self.root / 'power' / 'suspend_stats'
        self.stats.mkdir(parents=True)
        self.write('3\n', '1\n')
        self.boot = Mock(return_value='a' * 64)
        self.observer = SuspendObserver(self.root, boot_reader=self.boot)

    def write(self, success, fail):
        (self.stats / 'success').write_text(success, encoding='ascii')
        (self.stats / 'fail').write_text(fail, encoding='ascii')

    def test_baseline_and_completed_outcomes(self):
        baseline = self.observer.read()
        self.assertEqual(baseline, SuspendEvidence('a' * 64, 3, 1))
        self.assertEqual(self.observer.classify(baseline), 'unchanged')
        self.write('4\n', '1\n')
        self.assertEqual(self.observer.classify(baseline), 'success')
        self.write('3\n', '2\n')
        self.assertEqual(self.observer.classify(baseline), 'fail')

    def test_missing_malformed_and_oversized_are_not_zero(self):
        for value in ('', '-1', 'true', '1.0', '1\n2', 'x' * 129, '9' * 129):
            with self.subTest(value=value):
                self.write(value, '1\n')
                self.assertIsNone(self.observer.read())
        (self.stats / 'success').unlink()
        self.assertIsNone(self.observer.read())

    def test_boot_change_or_bad_identity_refuses(self):
        baseline = self.observer.read()
        self.boot.return_value = 'b' * 64
        self.assertEqual(self.observer.classify(baseline), 'unresolved')
        self.boot.return_value = ''
        self.assertIsNone(self.observer.read())
        self.boot.side_effect = ['a' * 64, 'b' * 64]
        self.assertIsNone(self.observer.read())

    def test_counter_change_during_read_refuses(self):
        with patch.object(self.observer, '_counter', side_effect=[3, 1, 4, 1]):
            self.assertIsNone(self.observer.read())

    def test_regression_mixed_results_and_unavailable_are_unresolved(self):
        baseline = SuspendEvidence('a' * 64, 3, 1)
        for current in (None, SuspendEvidence('a' * 64, 2, 1),
                        SuspendEvidence('a' * 64, 4, 0), SuspendEvidence('a' * 64, 4, 2)):
            self.assertEqual(classify_suspend(baseline, current), 'unresolved')
        self.assertEqual(classify_suspend(None, baseline), 'unresolved')

    def test_evidence_rejects_negative_and_boolean_counts(self):
        for value in (-1, True, 1.0):
            with self.assertRaises(ValueError):
                SuspendEvidence('a' * 64, value, 0)


if __name__ == '__main__':
    unittest.main()
