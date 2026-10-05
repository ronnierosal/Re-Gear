"""Actual executor/payload boundary; synthetic time and hardware, never device proof."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests import test_whole_dock_runtime as fixtures


class LatencyObservationTests(unittest.TestCase):
    def run_case(self, delayed=None, *, clock_error=False, write_error=False,
                 changed=False):
        case = fixtures.RuntimeTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        wall = [0.0]
        runtime = case.runtime
        runtime._diagnostic_clock = (Mock(side_effect=ValueError('private'))
                                     if clock_error else lambda: wall[0])
        runtime._monotonic = Mock(side_effect=lambda: wall[0])
        runtime._wait = Mock(side_effect=lambda seconds: wall.__setitem__(0, wall[0] + seconds))
        for name, stage in (('remove_usb', 'usb_remove'), ('deauthorize', 'deauthorization_write')):
            writer = getattr(case.writer, name)
            original = writer.side_effect
            def write(target, guard, original=original, stage=stage):
                if stage == delayed:
                    wall[0] += 30.0
                if write_error and stage == 'deauthorization_write':
                    raise ValueError('private writer failure')
                return original(target, guard)
            writer.side_effect = write
        if delayed == 'authorization_hold':
            def hold(*args):
                wall[0] += 30.0
                return True
            runtime._before_deauthorize = hold
        def validate(*args, **kwargs):
            if kwargs.get('tunnel_down'):
                if changed:
                    raise fixtures.whole_dock_topology.TopologyRefused('dock_topology.attachment_changed')
                if delayed == 'pci_settle' and wall[0] < 30.0:
                    raise fixtures.whole_dock_topology.TopologyRefused('dock_topology.pci_branch_remains')
            return True
        with patch.object(fixtures.module, 'revalidate_retained', side_effect=validate):
            result = runtime.execute('operation', case.approval)
        from tests.test_main_process_delivery import load_main_module
        plugin_module = load_main_module(real_dock_gate=True)
        plugin = plugin_module.Plugin.__new__(plugin_module.Plugin)
        plugin._remember_teardown_result(result, runtime)
        return case, result, plugin._whole_dock_teardown_details

    def test_equal_total_delays_are_distinguished_at_actual_payload_boundary(self):
        expected = {'usb_remove', 'authorization_hold', 'deauthorization_write', 'pci_settle'}
        for stage in expected:
            with self.subTest(stage=stage):
                case, result, payload = self.run_case(stage)
                self.assertTrue(result.software_down)
                self.assertFalse(result.safe_to_unplug)
                self.assertEqual(case.claim.stage, 'software_down')
                case.writer.remove_usb.assert_called_once()
                case.writer.deauthorize.assert_called_once()
                self.assertEqual(set(payload['timings_ms']), expected)
                self.assertEqual(payload['timings_ms'][stage], 30000)
                self.assertTrue(all(v == 0 for k, v in payload['timings_ms'].items() if k != stage))
                self.assertEqual(payload['settle_observations'], 61 if stage == 'pci_settle' else 1)

    def test_immediate_success_has_no_delay_or_extra_deadline_clock_reads(self):
        case, result, payload = self.run_case()
        self.assertTrue(result.software_down)
        case.runtime._wait.assert_not_called()
        self.assertEqual(case.runtime._monotonic.call_count, 1)
        self.assertEqual(set(payload['timings_ms'].values()), {0})

    def test_diagnostic_clock_failure_cannot_change_success_or_authority(self):
        case, result, payload = self.run_case(clock_error=True)
        self.assertTrue(result.software_down)
        self.assertFalse(result.safe_to_unplug)
        self.assertNotIn('timings_ms', payload)
        self.assertEqual(payload['settle_observations'], 1)
        case.writer.deauthorize.assert_called_once()

    def test_write_failure_is_retained_without_settle_or_replay(self):
        case, result, payload = self.run_case('deauthorization_write', write_error=True)
        self.assertFalse(result.software_down)
        self.assertEqual(case.claim.stage, 'tunnel_remove_intent')
        self.assertEqual(payload['tunnel_code'], 'dock_teardown.deauthorization_write_unverified')
        self.assertEqual(payload['timings_ms']['deauthorization_write'], 30000)
        self.assertNotIn('pci_settle', payload['timings_ms'])
        self.assertEqual(payload['settle_observations'], 0)
        case.runtime._wait.assert_not_called()
        case.writer.deauthorize.assert_called_once()

    def test_changed_identity_stops_without_wait_or_relaxing_guard(self):
        case, result, payload = self.run_case(changed=True)
        self.assertFalse(result.software_down)
        self.assertEqual(payload['tunnel_reason'], 'dock_topology.attachment_changed')
        self.assertEqual(payload['settle_observations'], 1)
        case.runtime._wait.assert_not_called()
        self.assertEqual(case.claim.stage, 'tunnel_remove_intent')

    def test_payload_rejects_private_unknown_invalid_and_mutable_measurements(self):
        from tests.test_main_process_delivery import load_main_module
        m = load_main_module(real_dock_gate=True)
        plugin = m.Plugin.__new__(m.Plugin)
        values = {'usb_remove': 3, 'authorization_hold': True, 'deauthorization_write': -1,
                  'pci_settle': float('nan'), 'private/path': 33}
        runtime = SimpleNamespace(tunnel_stage='completed', tunnel_code='',
                                  teardown_timings_ms=values, settle_observations=True)
        plugin._remember_teardown_result(SimpleNamespace(code='dock_teardown.software_down'), runtime)
        out = plugin._whole_dock_teardown_details
        self.assertEqual(out['timings_ms'], {'usb_remove': 3})
        self.assertNotIn('settle_observations', out)
        values['usb_remove'] = 100
        self.assertEqual(out['timings_ms']['usb_remove'], 3)

    def test_clock_values_are_bounded_and_unknown_is_not_fabricated_zero(self):
        from tests.test_main_process_delivery import load_main_module
        m = load_main_module(real_dock_gate=True)
        plugin = m.Plugin.__new__(m.Plugin)
        for bad in (True, -1, 7200001, float('inf'), 'private'):
            with self.subTest(value=bad):
                runtime = SimpleNamespace(teardown_timings_ms={'usb_remove': bad},
                                          settle_observations=72)
                plugin._remember_teardown_result(SimpleNamespace(code='dock_teardown.unresolved'), runtime)
                self.assertNotIn('timings_ms', plugin._whole_dock_teardown_details)
                self.assertNotIn('settle_observations', plugin._whole_dock_teardown_details)

    def test_runtime_clock_nan_infinity_backward_and_huge_values(self):
        for values, expected in (([float('nan'), 0], {}), ([0, float('inf')], {}),
                                 ([1, 0], {}), ([0, 1e300], {'usb_remove': 7200000})):
            with self.subTest(values=values):
                case = fixtures.RuntimeTests()
                case.setUp()
                try:
                    case.runtime._diagnostic_clock = Mock(side_effect=values)
                    result = case.runtime.execute('operation', case.approval)
                    self.assertTrue(result.software_down)
                    self.assertEqual(case.runtime.teardown_timings_ms, expected)
                    case.writer.deauthorize.assert_called_once()
                finally:
                    case.doCleanups()

    def test_measurement_write_failure_cannot_replace_original_writer_failure(self):
        case = fixtures.RuntimeTests()
        case.setUp()
        try:
            class Unwritable(dict):
                def __setitem__(self, key, value):
                    raise RuntimeError('diagnostic storage unavailable')
            case.runtime.teardown_timings_ms = Unwritable()
            case.writer.deauthorize.side_effect = ValueError('original writer failure')
            result = case.runtime.execute('operation', case.approval)
            self.assertFalse(result.software_down)
            self.assertEqual(case.runtime.tunnel_code, 'dock_teardown.deauthorization_write_unverified')
            self.assertEqual(case.claim.stage, 'tunnel_remove_intent')
            case.writer.deauthorize.assert_called_once()
        finally:
            case.doCleanups()
