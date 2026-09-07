from dataclasses import replace
import json
import unittest
from backend.hdm.delivery.device_filter_journal import JournalRecord,encode_record,decode_record
from backend.hdm.delivery.device_filter_lifecycle import FilterLifecycle,OwnedFilter,Phase,DirectCleanupStage,PairedOwnership,PairedStage
from tests.test_device_filter_paired_journal import PairedJournalTests


class DirectCleanupJournalTests(unittest.TestCase):
    change=PairedJournalTests.change
    def setUp(self):
        PairedJournalTests.setUp(self)
        self.owner=OwnedFilter(10,'d'*64,True,True,11,12)
        self.current=JournalRecord(1,FilterLifecycle(self.binding,Phase.CANCELLED,self.owner))

    def test_cas_stage_order_and_schema_three_roundtrip(self):
        self.assertEqual(json.loads(encode_record(self.current))['schema'],1)
        with self.assertRaises(ValueError):self.change('direct_cleanup_complete')
        self.change('direct_detached_verified')
        self.assertEqual(json.loads(encode_record(self.current))['schema'],3)
        self.assertEqual(decode_record(encode_record(self.current)),self.current)
        with self.assertRaises(ValueError):self.change('direct_detached_verified')
        self.change('direct_cleanup_complete')
        self.assertEqual(self.current.direct_cleanup,DirectCleanupStage.COMPLETE)
        with self.assertRaises(ValueError):self.change('direct_cleanup_complete')

    def test_missing_owner_and_incomplete_pair_refused(self):
        self.current=replace(self.current,lifecycle=FilterLifecycle(self.binding,Phase.CANCELLED))
        with self.assertRaises(ValueError):self.change('direct_detached_verified')
        self.current=replace(self.current,lifecycle=FilterLifecycle(self.binding,Phase.CANCELLED,self.owner),
            paired=PairedOwnership(3,PairedStage.RECEIVE_CONFIRMED,self.receive))
        with self.assertRaises(ValueError):self.change('direct_detached_verified')

    def test_reconstruction_rejects_crossphase_and_unknown_fields(self):
        self.change('direct_detached_verified')
        raw=json.loads(encode_record(self.current))
        for field,value in (('phase','attached'),('owned',None),('direct_cleanup',True),('direct_cleanup','unknown'),('paired',False)):
            malformed=dict(raw,**{field:value})
            with self.assertRaises(ValueError):decode_record(json.dumps(malformed).encode())
        with self.assertRaises(ValueError):decode_record(json.dumps(dict(raw,extra=0)).encode())

    def test_paired_complete_roundtrip_and_stale_cas(self):
        self.current=replace(self.current,paired=PairedOwnership(3,PairedStage.COMPLETE,self.receive))
        self.change('direct_detached_verified')
        self.assertEqual(decode_record(encode_record(self.current)),self.current)
        with self.assertRaises(ValueError):self.journal._change_locked(1,self.binding.operation,self.binding.unit,1,'direct_cleanup_complete')


if __name__=='__main__':unittest.main()
