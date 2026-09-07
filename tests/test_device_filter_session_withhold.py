"""Fail-closed helper tests, distinct from effective session observer tests."""
from dataclasses import replace
import hashlib
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from backend.hdm.delivery import device_filter_session_withhold as helper
from backend.hdm.delivery.device_filter_arm import FilterArm


class SessionWithholdTests(unittest.TestCase):
    def setUp(self):
        self.boot='12345678-1234-1234-1234-123456789abc'
        self.arm=FilterArm(1,'op','gamescope-session.service',1000,
            hashlib.sha256(self.boot.encode()).hexdigest(),'b'*64,'c'*64,'d'*32,30)
        self.store=Mock();self.store.read.return_value=self.arm
        self.transport=Mock(return_value=object())
        self.clock=Mock(return_value=10)
        self.loader=Mock(return_value='c'*64)
        self.topology=Mock(return_value='b'*64)
        self.hash=patch.object(helper,'config_hash',side_effect=lambda config:config)
        self.hash.start();self.addCleanup(self.hash.stop)
        self.exec=patch('os.execv',side_effect=AssertionError('native execution forbidden'))
        self.native=self.exec.start();self.addCleanup(self.exec.stop)

    def invoke(self,arm='default',**overrides):
        options=dict(state_root=Path.cwd(),raw_boot_id=self.boot,environment={'INVOCATION_ID':'e'*32},
            candidate_config='c'*64,arms=self.store,transport=self.transport,clock=self.clock,
            uid=lambda:1000,load_config=self.loader,topology=self.topology)
        options.update(overrides)
        return helper.withhold_session_entry(self.arm if arm=='default' else arm,**options)

    def test_absent_malformed_or_wrong_role_arm_never_requests(self):
        for value in (None,{},False,replace(self.arm,unit='steam-launcher.service')):
            with self.subTest(value=value):
                with self.assertRaises(helper.SessionEntryWithheld):self.invoke(value)
        self.transport.assert_not_called();self.store.read.assert_not_called()

    def test_candidate_configuration_mismatch(self):
        with self.assertRaises(helper.SessionEntryWithheld):self.invoke(candidate_config='f'*64)
        self.transport.assert_not_called()

    def test_fresh_configuration_or_topology_mismatch(self):
        self.loader.return_value='f'*64
        with self.assertRaises(helper.SessionEntryWithheld):self.invoke()
        self.loader.return_value='c'*64;self.topology.return_value='f'*64
        with self.assertRaises(helper.SessionEntryWithheld):self.invoke()
        self.transport.assert_not_called()

    def test_missing_changed_or_unreadable_durable_arm(self):
        for value in (None,replace(self.arm,operation='other'),OSError()):
            self.store.read.side_effect=value if isinstance(value,Exception) else None
            self.store.read.return_value=value
            with self.assertRaises(helper.SessionEntryWithheld):self.invoke()
        self.transport.assert_not_called()

    def test_arm_changed_after_slow_reads(self):
        self.store.read.side_effect=[self.arm,None]
        with self.assertRaises(helper.SessionEntryWithheld):self.invoke()
        self.transport.assert_not_called()

    def test_five_second_budget_includes_topology_config_and_final_arm_read(self):
        for values in ([10,15],[10,14.9,15]):
            self.clock.side_effect=values
            with self.assertRaises(helper.SessionEntryWithheld):self.invoke()
        self.transport.assert_not_called()

    def test_transport_failure_is_withheld(self):
        self.transport.side_effect=TimeoutError()
        with self.assertRaises(helper.SessionEntryWithheld):self.invoke()
        self.transport.assert_called_once();self.native.assert_not_called()

    def test_grant_shaped_reply_never_executes_or_clears_arm(self):
        self.transport.return_value={'granted':True,'launch_authorized':True}
        with self.assertRaisesRegex(helper.SessionEntryWithheld,'no response authorizes'):self.invoke()
        self.assertEqual(self.transport.call_args.kwargs,{'deadline':15})
        request=self.transport.call_args.args[0]
        self.assertEqual(request.unit,'gamescope-session.service')
        self.native.assert_not_called();self.store.clear.assert_not_called()

    def test_earlier_arm_deadline_is_preserved(self):
        self.arm=replace(self.arm,deadline=12);self.store.read.return_value=self.arm
        with self.assertRaises(helper.SessionEntryWithheld):self.invoke()
        self.assertEqual(self.transport.call_args.kwargs,{'deadline':12})


if __name__=='__main__':unittest.main()
