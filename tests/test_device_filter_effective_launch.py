import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from backend.hdm.delivery.device_filter_effective_launch import (
    SteamLaunchExpectation,EffectiveSteamLaunchObserver,FRAGMENT,DROPIN,EMPTY)
from backend.hdm.delivery.device_filter_runtime_bundle import RuntimeBundle
from backend.hdm.delivery.device_filter_peer import WaitingPeerIdentity
from backend.hdm.adapters.steamos.commands import UserServiceCommandRunner
from backend.hdm.ports.presentation_activation import UserServiceOperation


class EffectiveLaunchTests(unittest.TestCase):
    def setUp(self):
        path='/var/lib/regear/filter-runtime/'+'a'*64+'/runtime.pyz'
        self.bundle=RuntimeBundle(b'', 'a'*64,path,b'',('/usr/bin/python3','-I',path,'steam'),())
        self.expected=SteamLaunchExpectation(self.bundle,('HDM_STATE_ROOT=/var/lib/regear',))
        self.peer=WaitingPeerIdentity(123,1000,42,'b'*32,'steam-launcher.service','/fixture',1,2)
        self.fields=dict(LoadState='loaded',FragmentPath=FRAGMENT,DropInPaths=DROPIN,
            ExecStart='{ path=/usr/bin/python3 ; argv[]='+' '.join(self.bundle.steam_argv)+
                ' ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=123 ; code=(null) ; status=0/0 }',
            Environment='HDM_STATE_ROOT=/var/lib/regear',InvocationID=self.peer.invocation,MainPID='123',
            **{key:'' for key in EMPTY})
        self.runner=Mock()
        self.clock=Mock(return_value=1.)
        self.observer=EffectiveSteamLaunchObserver(SimpleNamespace(uid=1000,username='deck'),self.expected,
            deadline=5.,commands=self.runner,clock=self.clock)

    def run_observe(self,raw=None,peer=None):
        self.runner.run.return_value=SimpleNamespace(ok=True,output=raw if raw is not None else
            '\n'.join(k+'='+v for k,v in self.fields.items()))
        return self.observer(self.peer if peer is None else peer)

    def test_exact_expected_configuration_and_bounded_command(self):
        result=self.run_observe()
        self.assertEqual(result.identity,self.peer)
        self.assertEqual(result.runtime_digest,self.bundle.digest)
        self.assertEqual(self.runner.run.call_args.kwargs['timeout_seconds'],1)
        argv=UserServiceCommandRunner.argv(UserServiceOperation.OBSERVE_FILTER_STEAM_LAUNCH,uid=1000,username='deck')
        self.assertIn('--property=EnvironmentFiles',argv)
        self.assertIn('show',argv)
        self.assertNotIn('restart',argv)

    def test_overrides_invocation_and_extra_command_rejected(self):
        for key,value in [('DropInPaths',DROPIN+' /tmp/extra.conf'),('EnvironmentFiles','/tmp/env'),
                          ('InvocationID','c'*32),('MainPID','124'),('ExecStartPre','/bin/true'),
                          ('ExecStart',self.fields['ExecStart'].replace('pid=123','pid=124')),
                          ('Environment','HDM_STATE_ROOT=/tmp'),('ExecStart',self.fields['ExecStart']+' { other }')]:
            with self.subTest(key=key):
                old=self.fields[key];self.fields[key]=value
                with self.assertRaises(ValueError):self.run_observe()
                self.fields[key]=old

    def test_duplicate_missing_extra_and_bounded_output(self):
        raw='\n'.join(k+'='+v for k,v in self.fields.items())
        for value in (raw+'\nMainPID=123',raw+'\nUnknown=x',raw.replace('MainPID=123',''), 'x'*4097):
            with self.assertRaises(ValueError):self.run_observe(value)

    def test_deadline_before_after_and_final_revalidation(self):
        for times in ([5.], [1.,5.], [1.,1.,5.], [2.,1.], [float('nan')]):
            self.clock.side_effect=times
            with self.assertRaises(ValueError):self.run_observe()

    def test_gamescope_unsupported_and_uid_mismatch(self):
        for peer in (replace(self.peer,unit='gamescope-session.service'),replace(self.peer,uid=1001)):
            with self.assertRaises(ValueError):self.run_observe(peer=peer)
        self.runner.run.assert_not_called()

    def test_expectation_not_learned_and_duplicate_environment_rejected(self):
        with self.assertRaises(ValueError):SteamLaunchExpectation(self.bundle,('A=1','A=2'))
        with self.assertRaises(ValueError):SteamLaunchExpectation(replace(self.bundle,steam_argv=('/bin/sh',)),())
        self.fields['LoadState']='not-found'
        with self.assertRaises(ValueError):self.run_observe()


if __name__=='__main__':unittest.main()
