import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.application.dock_power import DockPowerCoordinator


class DockPowerTests(unittest.TestCase):
    def make(self, **changes):
        self.calls = []
        def record(operation, action):
            self.calls.append(('record', operation, action))
            return True
        def power(action):
            self.calls.append(('power', action))
            return True
        args = dict(operation_id='a' * 32, action='shutdown', requested_at=10,
                    deadline=40, verify_down=lambda operation: operation == 'a' * 32,
                    record_intent=record, request_power=power,
                    admission_held=lambda: True, monotonic=lambda: 20)
        args.update(changes)
        return DockPowerCoordinator(**args)

    def test_verified_shutdown_records_then_submits_once(self):
        coordinator = self.make()
        self.assertTrue(coordinator.execute().requested)
        self.assertEqual(coordinator.execute().code, 'dock_power.already_consumed')
        self.assertEqual(self.calls, [('record', 'a' * 32, 'shutdown'), ('power', 'shutdown')])

    def test_sleep_requires_explicit_capability(self):
        self.assertEqual(self.make(action='sleep').execute().code, 'dock_power.sleep_unverified')
        self.assertEqual(self.calls, [])
        self.assertTrue(self.make(action='sleep', sleep_supported=True).execute().requested)

    def test_missing_admission_failed_disconnect_and_unknown_fail_closed(self):
        for changes in ({'admission_held': lambda: False},
                        {'verify_down': lambda operation: False},
                        {'verify_down': lambda operation: None},
                        {'verify_down': lambda operation: 1}):
            with self.subTest(changes=changes):
                self.assertFalse(self.make(**changes).execute().requested)
                self.assertEqual(self.calls, [])

    def test_expired_or_future_request_never_records(self):
        for now in (40, 41, 9, float('nan')):
            self.assertFalse(self.make(monotonic=lambda: now).execute().requested)
            self.assertEqual(self.calls, [])

    def test_changed_verification_after_record_never_submits(self):
        answers = iter((True, False))
        self.assertFalse(self.make(verify_down=lambda operation: next(answers)).execute().requested)
        self.assertEqual(self.calls, [('record', 'a' * 32, 'shutdown')])

    def test_deadline_or_admission_loss_after_record_never_submits(self):
        for lose_admission in (False, True):
            state = {'recorded': False}
            powers = []
            def record(operation, action):
                state['recorded'] = True
                return True
            coordinator = self.make(record_intent=record,
                admission_held=lambda: not (lose_admission and state['recorded']),
                monotonic=lambda: 40 if state['recorded'] and not lose_admission else 20,
                request_power=lambda action: powers.append(action) or True)
            self.assertFalse(coordinator.execute().requested)
            self.assertEqual(powers, [])

    def test_durable_duplicate_prevents_reconstructed_coordinator_replay(self):
        recorded = set()
        powers = []
        def record(operation, action):
            if operation in recorded:
                return False
            recorded.add(operation)
            return True
        for _ in range(2):
            self.make(record_intent=record,
                      request_power=lambda action: powers.append(action) or True).execute()
        self.assertEqual(powers, ['shutdown'])

    def test_submission_exception_is_never_replayed(self):
        powers = []
        def power(action):
            powers.append(action)
            raise TimeoutError()
        coordinator = self.make(request_power=power)
        self.assertEqual(coordinator.execute().code, 'dock_power.unresolved')
        coordinator.execute()
        self.assertEqual(powers, ['shutdown'])

    def test_recursive_concurrent_request_is_busy(self):
        nested = []
        def record(operation, action):
            nested.append(coordinator.execute().code)
            return True
        coordinator = self.make(record_intent=record)
        self.assertTrue(coordinator.execute().requested)
        self.assertEqual(nested, ['dock_power.busy'])

    def test_invalid_original_intent_rejected(self):
        for changes in ({'operation_id': ''}, {'action': 'reconnect'},
                        {'sleep_supported': 1}, {'deadline': 400},
                        {'requested_at': float('nan')}, {'deadline': 10}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.make(**changes)


if __name__ == '__main__':
    unittest.main()
