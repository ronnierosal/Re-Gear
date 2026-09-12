import math
import json
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery.dock_power_service import (
    DockPowerRequest, create_power_request, continue_dock_power,
    dock_power_capabilities)


class DockPowerCapabilitiesTests(unittest.TestCase):
    def test_implemented_shutdown_is_not_live_authorization(self):
        status = dock_power_capabilities()
        self.assertEqual(status['schema_version'], 1)
        self.assertEqual(status['code'], 'dock_power.capabilities')
        self.assertIs(status['authorizes_action'], False)
        shutdown = status['actions']['shutdown']
        self.assertEqual(shutdown['implementation'], 'implemented')
        self.assertEqual(shutdown['live_readiness'], 'not_assessed')
        self.assertIs(shutdown['actionable'], False)
        self.assertEqual(shutdown['reason_codes'], [
            'dock_power.shutdown_hardware_unverified',
            'dock_power.live_preflight_required'])
        self.assertEqual(json.loads(json.dumps(status)), status)

    def test_physical_removal_profile_does_not_promote_sleep_support(self):
        from regear.domain.control_plane import SleepBehavior
        from regear.profiles.gpd_g1 import CAPABILITIES
        self.assertIs(CAPABILITIES.sleep_behavior,
                      SleepBehavior.DISCONNECT_BEFORE_SLEEP_VERIFIED)
        sleep = dock_power_capabilities()['actions']['sleep']
        self.assertEqual(sleep['implementation'], 'unavailable')
        self.assertEqual(sleep['live_readiness'], 'unavailable')
        self.assertIs(sleep['actionable'], False)
        self.assertEqual(sleep['reason_codes'], [
            'dock_power.sleep_profile_unverified',
            'dock_power.sleep_inhibitor_handoff_unverified',
            'dock_power.sleep_wake_thermal_unverified'])
        with self.assertRaisesRegex(ValueError, 'sleep_unverified'):
            create_power_request('sleep', 'session-a')

    def test_payload_mutation_cannot_change_subsequent_status_or_execution(self):
        status = dock_power_capabilities()
        status['authorizes_action'] = True
        status['actions']['sleep']['actionable'] = True
        status['actions']['sleep']['reason_codes'].clear()
        fresh = dock_power_capabilities()
        self.assertIs(fresh['authorizes_action'], False)
        self.assertIs(fresh['actions']['sleep']['actionable'], False)
        self.assertEqual(len(fresh['actions']['sleep']['reason_codes']), 3)
        with self.assertRaisesRegex(ValueError, 'sleep_unverified'):
            create_power_request('sleep', 'session-a')


class DockPowerServiceTests(unittest.TestCase):
    def setUp(self):
        self.request = create_power_request('shutdown', 'session-a', monotonic=lambda: 10)
        self.calls = []
        self.consumed = False
        self.verified = True
        self.admitted = True
        self.runtime = SimpleNamespace(binding=SimpleNamespace(binding='dock', generation=2),
            verify_power_continuation=self.verify)
        self.store = SimpleNamespace(consume=self.consume)
        self.power = SimpleNamespace(request_poweroff=self.poweroff)

    def verify(self, operation, *, portable_verified):
        self.calls.append(('verify', operation))
        return self.verified and portable_verified()

    def consume(self, *fields):
        self.calls.append(('consume', fields))
        if self.consumed:
            return False
        self.consumed = True
        return True

    def poweroff(self):
        self.calls.append(('poweroff',))
        return SimpleNamespace(requested=True)

    def run_request(self, **changes):
        args = dict(runtime=self.runtime, store=self.store,
            portable_verified=lambda: True, power=self.power,
            admission_held=lambda: self.admitted, monotonic=lambda: 20)
        args.update(changes)
        return continue_dock_power(self.request, **args)

    def test_original_request_is_immutable_backend_uuid_and_bounded(self):
        self.assertRegex(self.request.operation, r'^[0-9a-f]{32}$')
        self.assertEqual(self.request.deadline, 310)
        with self.assertRaises(FrozenInstanceError):
            self.request.action = 'sleep'
        for ttl in (0, -1, 301, True, None, '300', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                create_power_request('shutdown', 'session-a', ttl_seconds=ttl)

    def test_rounded_deadline_never_exceeds_requested_ttl(self):
        now = 212.2
        self.assertGreater((now + 300) - now, 300)
        for ttl in (300, 0.1):
            with self.subTest(ttl=ttl):
                request = create_power_request('shutdown', 'session-a',
                    monotonic=lambda: now, ttl_seconds=ttl)
                self.assertGreater(request.deadline, now)
                self.assertLessEqual(request.deadline - now, ttl)
                self.assertLessEqual(request.deadline - now, 300)
                expected = (math.nextafter(now + ttl, -math.inf)
                            if (now + ttl) - now > ttl else now + ttl)
                self.assertEqual(request.deadline, expected)
        with self.assertRaisesRegex(ValueError, 'invalid_intent'):
            DockPowerRequest('a' * 32, 'shutdown', 'session-a', now, now + 300)

    def test_unrepresentable_positive_ttl_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'invalid_intent'):
            create_power_request('shutdown', 'session-a',
                monotonic=lambda: 1e20, ttl_seconds=300)

    def test_sleep_refused_before_any_teardown(self):
        with self.assertRaisesRegex(ValueError, 'sleep_unverified'):
            create_power_request('sleep', 'session-a')
        self.request = replace(self.request, action='sleep')
        self.assertEqual(self.run_request().code, 'dock_power.sleep_unverified')
        self.assertEqual(self.calls, [])

    def test_shutdown_consumes_exact_original_bound_fields_before_power(self):
        self.assertTrue(self.run_request().requested)
        self.assertEqual([call[0] for call in self.calls],
                         ['verify', 'consume', 'verify', 'poweroff'])
        self.assertEqual(self.calls[1][1], (self.request.operation, 'dock', 2,
            'shutdown', 'session-a', 10, 310))
        self.assertFalse(self.run_request().requested)
        self.assertEqual(sum(call[0] == 'poweroff' for call in self.calls), 1)

    def test_expired_and_future_requests_never_consume(self):
        for now in (9, 310, 400, float('nan')):
            self.calls.clear()
            self.assertFalse(self.run_request(monotonic=lambda: now).requested)
            self.assertEqual(self.calls, [])

    def test_missing_admission_or_portable_proof_never_consumes(self):
        self.admitted = False
        self.assertFalse(self.run_request().requested)
        self.assertEqual(self.calls, [])
        self.admitted = True
        self.assertFalse(self.run_request(portable_verified=lambda: False).requested)
        self.assertFalse(self.consumed)

    def test_changed_proof_after_consumption_never_submits_or_replays(self):
        def consume(*fields):
            result = self.consume(*fields)
            self.verified = False
            return result
        self.store.consume = consume
        self.assertFalse(self.run_request().requested)
        self.verified = True
        self.assertFalse(self.run_request().requested)
        self.assertFalse(any(call[0] == 'poweroff' for call in self.calls))

    def test_ambiguous_power_submission_remains_consumed(self):
        def fail():
            self.calls.append(('poweroff',))
            raise TimeoutError()
        self.power.request_poweroff = fail
        self.assertEqual(self.run_request().code, 'dock_power.unresolved')
        self.assertFalse(self.run_request().requested)
        self.assertEqual(sum(call[0] == 'poweroff' for call in self.calls), 1)

    def test_truthy_non_boolean_power_reply_is_not_acceptance(self):
        self.power.request_poweroff = lambda: SimpleNamespace(requested=1)
        self.assertEqual(self.run_request().code, 'dock_power.request_unverified')

    def test_invalid_request_fields_rejected(self):
        for changes in ({'operation': 'client-id'}, {'action': 'reboot'},
                        {'session': ''}, {'deadline': 311}, {'requested_at': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.request, **changes)
        self.assertEqual(continue_dock_power(None, runtime=None, store=None,
            portable_verified=None, power=None, admission_held=None).code,
            'dock_power.invalid_intent')


if __name__ == '__main__':
    unittest.main()
