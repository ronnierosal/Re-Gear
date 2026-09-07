import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from tests import test_device_filter_effective_launch as steam_tests
from backend.hdm.delivery.device_filter_session_entry import (
    SessionEntryPurpose,SessionEntryExpectation,EffectiveSessionEntryObserver,EffectiveSessionEntry)
from backend.hdm.adapters.steamos.commands import UserServiceCommandRunner
from backend.hdm.ports.presentation_activation import UserServiceOperation


class SessionEntryTests(unittest.TestCase):
    def setUp(self):
        base=steam_tests.EffectiveLaunchTests();base.setUp()
        self.bundle=replace(base.bundle,session_argv=('/usr/bin/python3','-I',base.bundle.path,'session'))
        self.peer=replace(base.peer,unit='gamescope-session.service')
        self.dropins=('/etc/systemd/user/gamescope-session.service.d/95-regear-filter-runtime.conf',)
        self.expected=SessionEntryExpectation(self.bundle,base.expected.environment,self.dropins,SessionEntryPurpose.PREPARE_WITHHOLD)
        self.fields=dict(base.fields)
        self.fields.update(FragmentPath='/usr/lib/systemd/user/gamescope-session.service',DropInPaths=self.dropins[0],
            ExecStart=self.fields['ExecStart'].replace(' steam ;',' session ;'))
        self.runner=Mock();self.clock=Mock(return_value=1.)
        self.observer=EffectiveSessionEntryObserver(SimpleNamespace(uid=1000,username='deck'),self.expected,
            deadline=5.,commands=self.runner,clock=self.clock)

    def observe(self,raw=None):
        self.runner.run.return_value=SimpleNamespace(ok=True,output=raw if raw is not None else
            '\n'.join(k+'='+v for k,v in self.fields.items()))
        return self.observer(self.peer)

    def test_exact_pre_native_configuration(self):
        result=self.observe()
        self.assertIs(type(result),EffectiveSessionEntry)
        self.assertFalse(result.native_execution_authorized)
        self.assertIs(result.purpose,SessionEntryPurpose.PREPARE_WITHHOLD)
        argv=UserServiceCommandRunner.argv(UserServiceOperation.OBSERVE_FILTER_SESSION_ENTRY,uid=1000,username='deck')
        self.assertIn('gamescope-session.service',argv);self.assertIn('show',argv)
        self.assertNotIn('restart',argv)

    def test_live_override_or_old_wrapper_role_is_not_approval(self):
        for key,value in [('DropInPaths',self.dropins[0]+' /usr/lib/systemd/user/gamescope-session.service.d/drm_janitor.conf'),
                          ('ExecStartPost','/usr/bin/drm_janitor'),('EnvironmentFiles','/tmp/env'),
                          ('InvocationID','c'*32),('MainPID','999'),
                          ('ExecStart',self.fields['ExecStart'].replace(' session ;',' gamescope ;'))]:
            old=self.fields[key];self.fields[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.observe()
            self.fields[key]=old

    def test_duplicate_missing_unknown_and_oversized(self):
        raw='\n'.join(k+'='+v for k,v in self.fields.items())
        for value in (raw+'\nMainPID=123',raw.replace('MainPID=123',''),raw+'\nUnknown=x','x'*4097):
            with self.assertRaises(ValueError):self.observe(value)

    def test_deadlines_and_wrong_service(self):
        for times in ([5.],[1.,5.],[1.,1.,5.],[2.,1.]):
            self.clock.side_effect=times
            with self.assertRaises(ValueError):self.observe()
        self.peer=replace(self.peer,unit='steam-launcher.service')
        with self.assertRaises(ValueError):self.observe()

    def test_untrusted_dropin_and_purpose_rejected(self):
        for dropins in (('/home/deck/x.conf',),('/etc/systemd/user/../x.conf',),self.dropins*2):
            with self.assertRaises(ValueError):replace(self.expected,dropins=dropins)
        with self.assertRaises(ValueError):replace(self.expected,purpose='prepare_withhold')


if __name__=='__main__':unittest.main()

