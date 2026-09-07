import json
import unittest
from unittest.mock import Mock
from backend.hdm.delivery.device_filter_lifecycle import (
    LaunchBinding,FilterLifecycle,Phase,PairedOwnership,PairedStage,PairedReceiveIdentity,paired_token)
from backend.hdm.delivery.device_filter_journal import FilterJournal,JournalRecord,encode_record,decode_record


class PairedJournalTests(unittest.TestCase):
    def setUp(self):
        self.binding=LaunchBinding('a'*64,'op','gamescope-session.service','b'*32,1000,10,20,1,30,'c'*64,99)
        self.current=JournalRecord(1,FilterLifecycle(self.binding))
        self.receive=PairedReceiveIdentity(4,5,6,7)
        self.journal=object.__new__(FilterJournal)
        self.journal._read=lambda *args:self.current
        def save(directory,record):self.current=decode_record(encode_record(record))
        self.journal._write=Mock(side_effect=save)

    def change(self,action,**evidence):
        return self.journal._change_locked(1,self.binding.operation,self.binding.unit,self.current.revision,action,**evidence)

    def publish(self):
        self.change('retention_intent',map_id=3)
        self.change('retention_confirmed')
        self.change('receive_intent',receive=self.receive)
        self.change('receive_confirmed')

    def test_legacy_schema_one_and_paired_schema_two_roundtrip(self):
        self.assertEqual(json.loads(encode_record(self.current))['schema'],1)
        self.change('retention_intent',map_id=3)
        self.assertEqual(json.loads(encode_record(self.current))['schema'],2)
        self.assertEqual(decode_record(encode_record(self.current)),self.current)

    def test_publication_cancellation_and_release_order(self):
        self.publish()
        metadata=self.current.paired
        self.change('recover')
        self.assertEqual(self.current.paired,metadata)
        self.assertEqual(self.current.lifecycle.phase,Phase.CANCELLED)
        for action in ('receive_release_pending','receive_released','retention_release_pending','paired_complete'):
            self.change(action)
        self.assertEqual(self.current.paired.stage,PairedStage.COMPLETE)
        with self.assertRaises(ValueError):self.change('paired_complete')

    def test_out_of_order_and_partial_release_refused(self):
        self.change('retention_intent',map_id=3)
        with self.assertRaises(ValueError):self.change('receive_confirmed')
        self.change('cancel')
        with self.assertRaises(ValueError):self.change('receive_release_pending')
        with self.assertRaises(ValueError):self.change('retention_confirmed')

    def test_paired_grant_and_stale_cas_refused(self):
        self.publish()
        with self.assertRaises(ValueError):self.change('grant')
        with self.assertRaises(ValueError):
            self.journal._change_locked(1,self.binding.operation,self.binding.unit,1,'cancel')

    def test_strict_bounds_fields_and_complete_requires_receive(self):
        self.change('retention_intent',map_id=3)
        raw=json.loads(encode_record(self.current))
        for field,value in (('map_id',True),('map_id',2**32),('stage','unknown'),('stage','complete')):
            bad=json.loads(json.dumps(raw));bad['paired'][field]=value
            with self.assertRaises(ValueError):decode_record(json.dumps(bad).encode())
        bad=dict(raw,extra=0)
        with self.assertRaises(ValueError):decode_record(json.dumps(bad).encode())
        with self.assertRaises(ValueError):decode_record(b'{"schema":2,"schema":2}')
        with self.assertRaises(ValueError):PairedReceiveIdentity(1,2,3,True)
        with self.assertRaises(ValueError):PairedOwnership(3,PairedStage.COMPLETE)

    def test_role_tokens_are_distinct_and_binding_bound(self):
        self.assertEqual(len(paired_token(self.binding,'retention')),64)
        self.assertNotEqual(paired_token(self.binding,'retention'),paired_token(self.binding,'receive'))
        with self.assertRaises(ValueError):paired_token(self.binding,'../path')

    def test_release_stage_reconstruction_requires_cancelled_lifecycle(self):
        self.publish()
        self.change('cancel')
        for stage in (PairedStage.RECEIVE_RELEASE_PENDING,PairedStage.RECEIVE_RELEASED,
                      PairedStage.RETENTION_RELEASE_PENDING,PairedStage.COMPLETE):
            metadata=PairedOwnership(3,stage,self.receive)
            valid=JournalRecord(10,self.current.lifecycle,paired=metadata)
            raw=json.loads(encode_record(valid))
            self.assertEqual(decode_record(encode_record(valid)),valid)
            for phase in ('requested','attached','pin_pending','recovery_required','granted'):
                forged=json.loads(json.dumps(raw));forged['phase']=phase
                if phase not in ('requested',):
                    forged['owned']=dict(program_id=8,program_hash='d'*64,ownership_verified=True,
                        survives_owner_exit=phase!='pin_pending',link_id=9,kernel_cgroup_id=10)
                with self.assertRaises(ValueError):decode_record(json.dumps(forged).encode())
            with self.assertRaises(ValueError):
                JournalRecord(10,FilterLifecycle(self.binding),paired=metadata)


if __name__=='__main__':unittest.main()
