from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from regear.delivery.audio_trial_factory import LiveAudioTrialFactory
from regear.delivery.audio_profile_trial import AudioProfileTrial
from regear.delivery.audio_profile_trial_state import AudioTrialRecord


class LiveAudioTrialFactoryTests(unittest.TestCase):
    def setUp(self):
        self.record=AudioTrialRecord('trial','a'*64,'b'*64,'0000:08:00.1',
                                     'output:hdmi-stereo','portable.sink',1000)
        self.store=Mock()
        self.commands=Mock()
        self.user=SimpleNamespace(uid=1000,username='deck')
        self.scan=Mock(return_value=SimpleNamespace(ok=True))
        self.resolve=Mock(return_value=SimpleNamespace(ok=True,context=self.user))
        self.sources=[]
        self.observers=[]
        def source(*args,**kwargs):
            value=Mock()
            self.sources.append((value,args,kwargs))
            return value
        def observer(*args,**kwargs):
            value=Mock()
            self.observers.append((value,args,kwargs))
            return value
        self.now=10
        self.factory=LiveAudioTrialFactory(self.store,scan_gamescope=self.scan,
            resolve_user=self.resolve,source_factory=source,observer_factory=observer,
            commands=self.commands,clock=lambda:self.now)

    def test_construction_writes_nothing_and_returns_real_trial(self):
        trial=self.factory(self.record,20)
        self.assertIs(type(trial),AudioProfileTrial)
        self.assertIs(trial.store,self.store)
        self.assertIs(trial.user,self.user)
        self.assertIs(trial.observe,self.observers[0][0])
        self.assertIs(trial.commands,self.commands)
        self.store.assert_not_called()
        self.assertEqual(self.store.mock_calls,[])
        self.assertEqual(self.commands.mock_calls,[])
        self.sources[0][0].assert_not_called()
        self.observers[0][0].assert_not_called()
        self.assertEqual(self.sources[0][1],(self.user,self.record.portable_sink))

    def test_each_retry_has_new_source_observer_and_deadline(self):
        first=self.factory(self.record,20)
        self.now=11
        second=self.factory(self.record,25)
        self.assertIsNot(first.observe,second.observe)
        self.assertIsNot(self.sources[0][0],self.sources[1][0])
        self.assertEqual([x[2]['deadline'] for x in self.sources],[20,25])
        self.assertEqual([x[2]['deadline'] for x in self.observers],[20,25])
        self.assertEqual(self.scan.call_count,2)
        self.assertEqual(self.resolve.call_count,2)

    def test_deadline_invalid_before_any_scan(self):
        for deadline in (10,41,True,float('nan'),float('inf')):
            with self.assertRaises(TimeoutError):self.factory(self.record,deadline)
        self.scan.assert_not_called()

    def test_typed_record_required_before_scan(self):
        with self.assertRaises(ValueError):self.factory(SimpleNamespace(uid=1000),20)
        self.scan.assert_not_called()

    def test_unknown_scan_or_owner_reject_without_constructing(self):
        self.scan.return_value=SimpleNamespace(ok=False)
        with self.assertRaises(ValueError):self.factory(self.record,20)
        self.resolve.assert_not_called()
        self.scan.return_value=SimpleNamespace(ok=True)
        for owner in (SimpleNamespace(ok=False,context=None),
                      SimpleNamespace(ok=True,context=SimpleNamespace(uid=1001)),
                      SimpleNamespace(ok=True,context=SimpleNamespace(uid=True))):
            self.resolve.return_value=owner
            with self.assertRaises(ValueError):self.factory(self.record,20)
        self.assertEqual(self.sources,[])

    def test_slow_owner_resolution_deadline_rejects(self):
        def resolve(scan):
            self.now=20
            return SimpleNamespace(ok=True,context=self.user)
        self.resolve.side_effect=resolve
        with self.assertRaises(TimeoutError):self.factory(self.record,20)
        self.assertEqual(self.sources,[])

    def test_returned_trial_still_requires_live_observation_before_writes(self):
        trial=self.factory(self.record,20)
        self.observers[0][0].side_effect=ValueError('live context unavailable')
        # Use a harmless transaction stub to reach the existing fresh guard.
        self.store.transaction.return_value.__enter__=Mock(return_value=self.store)
        self.store.transaction.return_value.__exit__=Mock(return_value=False)
        with self.assertRaises(ValueError):
            trial.off('trial',boot_hash=self.record.boot_hash,topology_hash=self.record.topology_hash,
                audio_bdf=self.record.audio_bdf,portable_sink=self.record.portable_sink,deadline=20)
        self.store.create.assert_not_called()
        self.store.save.assert_not_called()
        self.assertEqual(self.commands.mock_calls,[])


if __name__=='__main__':unittest.main()
