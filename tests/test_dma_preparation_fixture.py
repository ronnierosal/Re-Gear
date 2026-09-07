from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from scripts import probe_dma_preparation_fixture as fixture


class DmaPreparationFixtureTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.prepare=Mock(side_effect=lambda:self.events.append('prepare') or SimpleNamespace(
            prepared=True,launch_authorized=False,disconnect_clearance=False))
        self.recover=Mock(side_effect=lambda:self.events.append('recover'))
        self.validate=Mock()
        self.override={}

    def deliver(self,fd,seq):
        self.events.append(seq)
        return self.override.get(seq,dict(received=0 if seq==3 else 1,
            truncated=seq==3,identity=None if seq==3 else [1,fd]))

    def run_case(self,**changes):
        args=dict(internal=10,external=20,identify=lambda fd:(1,fd),deliver=self.deliver,
            outside=self.deliver,prepare=self.prepare,recover=self.recover,validate=self.validate)
        args.update(changes)
        return fixture.exercise(**args)

    def test_actual_sequence_and_claim_limits(self):
        report=self.run_case()
        self.assertEqual(self.events,[1,2,'prepare',3,4,16,'recover',5])
        for field in ('disconnect_clearance','launch_authorized','player_mutation',
                      'importer_isolation_verified','inherited_player_resources_verified'):
            self.assertFalse(report[field])

    def test_baseline_failure_never_prepares(self):
        self.override[2]=dict(received=0,truncated=True,identity=None)
        with self.assertRaises(ValueError):self.run_case()
        self.prepare.assert_not_called()

    def test_each_enforcement_or_restore_failure_never_passes(self):
        for seq in (3,4,16,5):
            self.override={seq:dict(received=0,truncated=False,identity=None)}
            with self.assertRaises(ValueError):self.run_case()

    def test_recovery_and_final_identity_failure_never_pass(self):
        self.recover.side_effect=RuntimeError('uncertain')
        with self.assertRaises(RuntimeError):self.run_case()
        self.assertNotIn(5,self.events)
        self.recover.side_effect=None
        self.validate.side_effect=[None,None,None,ValueError('changed')]
        with self.assertRaises(ValueError):self.run_case()

    def test_authorizing_result_and_overlapping_buffers_rejected(self):
        self.prepare.side_effect=None
        self.prepare.return_value=SimpleNamespace(prepared=True,launch_authorized=True,disconnect_clearance=False)
        with self.assertRaises(ValueError):self.run_case()
        with self.assertRaises(ValueError):self.run_case(identify=lambda fd:(1,1))

    def test_explicit_root_guards_and_sanitized_failure(self):
        with patch.object(fixture.platform,'system',return_value='Windows'),patch.object(fixture.os,'open') as opened:
            with self.assertRaises(ValueError):fixture.run_fixture()
            opened.assert_not_called()
        with patch.object(fixture.sys,'argv',['probe']),patch.object(fixture,'run_fixture') as run:
            with self.assertRaises(SystemExit):fixture.main()
            run.assert_not_called()
        with patch.object(fixture.sys,'argv',['probe','--supervised-dma-preparation']), \
             patch.object(fixture.platform,'system',return_value='Windows'), \
             patch.object(fixture,'run_fixture',side_effect=RuntimeError('PRIVATE')),patch('builtins.print') as output:
            self.assertEqual(fixture.main(),1)
            self.assertNotIn('PRIVATE',output.call_args.args[0])


if __name__=='__main__':unittest.main()
