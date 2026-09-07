import unittest
from unittest.mock import Mock,patch
from scripts import probe_prepare_observation_timing as probe


class TimingTests(unittest.TestCase):
    def options(self):
        return dict(identity=Mock(return_value='identity'),btf=Mock(return_value=b'raw'),
            symbols=Mock(return_value=(123,456)),boot=Mock(return_value='boot'),
            cache=Mock(parse=Mock(return_value='layout')),clock=Mock(side_effect=[i*.01 for i in range(100)]))

    def test_three_fresh_samples_and_no_authority_or_private_output(self):
        options=self.options();result=probe.measure(**options)
        self.assertEqual(result['state'],'ready');self.assertEqual(len(result['samples']),3)
        for key in ('identity','btf','symbols'):self.assertEqual(options[key].call_count,3)
        self.assertEqual(options['boot'].call_count,6)
        self.assertFalse(result['session_launch_budget_verified'])
        self.assertFalse(result['disconnect_clearance']);self.assertFalse(result['launch_authorized'])
        self.assertNotIn('123',str(result));self.assertNotIn('raw',str(result))

    def test_changes_stop_sampling(self):
        for field in ('identity','symbols','boot'):
            options=self.options();options[field].side_effect=['first','changed']
            self.assertEqual(probe.measure(**options)['state'],'changed')
        options=self.options();options['cache'].parse.side_effect=['first','changed']
        self.assertEqual(probe.measure(**options)['state'],'changed')

    def test_invalid_and_decreasing_clocks_fail(self):
        for clock in ([float('nan')],[1,0],[True]):
            options=self.options();options['clock']=Mock(side_effect=clock)
            with self.assertRaises(ValueError):probe.measure(**options)

    def test_deadline_is_bounded(self):
        options=self.options();options['clock']=Mock(side_effect=[0,31])
        with self.assertRaises(TimeoutError):probe.measure(**options)
        options['identity'].assert_not_called()

    def test_root_and_cli_refusal_no_collection(self):
        with patch.object(probe.platform,'system',return_value='Windows'),patch.object(probe,'measure') as measure:
            with self.assertRaises(ValueError):probe.run_probe()
            measure.assert_not_called()
        with patch.object(probe.sys,'argv',['probe']),patch.object(probe,'run_probe') as run:
            with self.assertRaises(SystemExit):probe.main()
            run.assert_not_called()

    def test_error_report_sanitized(self):
        with patch.object(probe.sys,'argv',['probe','--read-only-observation']), \
             patch.object(probe,'run_probe',side_effect=PermissionError(13,'PRIVATE')),patch('builtins.print') as output:
            self.assertEqual(probe.main(),1)
            self.assertNotIn('PRIVATE',output.call_args.args[0])
            self.assertIn('PermissionError',output.call_args.args[0])

    def test_launch_mode_uses_fresh_lean_source_without_audio_capture(self):
        source=Mock()
        def measure(**kwargs):
            kwargs['identity']();kwargs['identity']()
            return dict(state='ready',session_launch_budget_verified=False)
        with patch.object(probe.platform,'system',return_value='Linux'), \
             patch.object(probe.platform,'machine',return_value='x86_64'), \
             patch.object(probe.os,'geteuid',return_value=0,create=True), \
             patch.object(probe.time,'monotonic',side_effect=[10,11]), \
             patch('hdm.adapters.steamos.prepare_hardware_identity.PrepareHardwareIdentitySource',return_value=source), \
             patch.object(probe,'measure',side_effect=measure), \
             patch.object(probe,'collect_identity',side_effect=AssertionError('audio fixture forbidden')):
            result=probe.run_launch_probe()
        self.assertEqual([c.kwargs['deadline'] for c in source.collect.call_args_list],[12,13])
        self.assertEqual(result['collector'],'launch_hardware')
        self.assertFalse(result['authenticated_session_observed'])
        self.assertFalse(result['session_launch_budget_verified'])


if __name__=='__main__':unittest.main()
