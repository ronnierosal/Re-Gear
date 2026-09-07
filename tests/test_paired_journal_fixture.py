from contextlib import contextmanager
from dataclasses import replace
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from types import SimpleNamespace
from scripts import probe_paired_journal_fixture as fixture
from hdm.delivery.device_filter_journal import FilterJournal,JournalRecord,encode_record,decode_record
from hdm.delivery.device_filter_lifecycle import FilterLifecycle,LaunchBinding,Phase,PairedStage,PairedOwnership
from hdm.delivery.device_filter_recovery import FilterRecovery
from hdm.delivery.device_receive_recovery import ReceiveRecovery
from hdm.delivery.cgroup_retention_map import MapIdentity
from hdm.delivery.device_receive_kernel import ReceiveIdentity


class MemoryJournal:
    def __init__(self,binding):self.raw=encode_record(JournalRecord(1,FilterLifecycle(binding)));self.locked=False;self.events=[]
    @contextmanager
    def transaction(self):
        if self.locked:raise ValueError('nested transaction')
        self.locked=True
        try:yield self
        finally:self.locked=False
    def read(self,*args):return decode_record(self.raw)
    def change(self,operation,unit,revision,action,**evidence):
        current=self.read()
        if not self.locked or current.revision!=revision:raise ValueError('CAS conflict')
        self.events.append(action)
        if action=='retention_intent':paired=PairedOwnership(evidence['map_id'],PairedStage.RETENTION_INTENT)
        elif action=='recover':
            result=replace(current,revision=revision+1,lifecycle=current.lifecycle.after_crash())
            self.raw=encode_record(result);return self.read()
        else:paired=current.paired.advance(action,**evidence)
        self.raw=encode_record(replace(current,revision=revision+1,paired=paired))
        return self.read()


class PairedJournalFixtureTests(unittest.TestCase):
    def setUp(self):
        self.binding=LaunchBinding('a'*64,'fixture','gamescope-session.service','b'*32,1000,123,456,1,789,'c'*64,100.)
        self.journal=MemoryJournal(self.binding)
        self.map=Mock(map_fd=10);self.map.create.return_value=MapIdentity(2);self.map.identity.return_value=MapIdentity(2)
        self.map.release_entry.return_value=True
        self.receive=Mock(program_fd=11,link_fd=12)
        self.receive.link_identity.return_value=ReceiveIdentity(3,4,5,6)
        self.receive.probe_program_present.return_value=False
        self.pins=Mock(fd=8)
        self.recovery=ReceiveRecovery(map_factory=lambda:self.map,receive_factory=lambda:self.receive,
            directory_factory=lambda:self.pins,unlink=Mock())
        self.layout=SimpleNamespace(file_inode_offset=1,inode_mode_offset=2,inode_rdev_offset=3,hook_btf_id=5)

    def publish(self,journal=None):
        with patch.object(fixture.os,'major',lambda dev:1,create=True),patch.object(fixture.os,'minor',lambda dev:3,create=True):
            fixture.publish_journal_pair(journal or self.journal,self.binding,20,self.layout,3,
                map_factory=lambda:self.map,receive_factory=lambda:self.receive,pins_factory=lambda **k:self.pins,
                compiler=lambda *a,**k:b'program',observe_denial=lambda:True)

    def recover(self,journal_factory=None,**kwargs):
        return fixture.recover_journal_pair(journal_factory or (lambda:self.journal),self.binding,
            current_boot_hash=self.binding.boot_hash,observe_denial=lambda:True,
            observe_restored=kwargs.get('observe_restored',lambda:True),
            recovery_factory=lambda journal:FilterRecovery(journal,receive_recovery=self.recovery))

    def test_real_recovery_classes_persist_full_order_without_nested_lock(self):
        self.publish()
        report=self.recover()
        self.assertFalse(report['launch_authorized']);self.assertFalse(report['disconnect_clearance'])
        self.assertEqual(self.journal.events,['retention_intent','retention_confirmed','receive_intent',
            'receive_confirmed','recover','receive_release_pending','receive_released','retention_release_pending','paired_complete'])
        self.assertEqual(self.journal.read().lifecycle.phase,Phase.CANCELLED)
        self.assertEqual(self.journal.read().paired.stage,PairedStage.COMPLETE)

    def test_publication_records_intent_before_each_pin(self):
        def map_pin(*args):self.assertEqual(self.journal.read().paired.stage,PairedStage.RETENTION_INTENT)
        def receive_pin(*args):self.assertEqual(self.journal.read().paired.stage,PairedStage.RECEIVE_INTENT)
        self.map.pin.side_effect=map_pin;self.receive.pin.side_effect=receive_pin
        self.publish()
        self.map.close.assert_called();self.receive.close.assert_called();self.pins.close.assert_called()

    def test_fresh_reader_factory_called_after_publication(self):
        self.publish()
        factory=Mock(return_value=self.journal)
        self.recover(factory)
        factory.assert_called_once_with()

    def test_failed_restoration_never_reports_pass(self):
        self.publish()
        with self.assertRaises(ValueError):self.recover(observe_restored=lambda:False)

    def test_pin_failure_retains_durable_intent(self):
        self.receive.pin.side_effect=PermissionError()
        with self.assertRaises(PermissionError):self.publish()
        self.assertEqual(self.journal.read().paired.stage,PairedStage.RECEIVE_INTENT)
        self.map.release_entry.assert_not_called()
        self.map.close.assert_called()

    @unittest.skipUnless(sys.platform=='linux','real Linux journal file operations')
    def test_actual_file_journal_fresh_reader_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            os.chmod(temporary,0o700)
            fd=os.open(temporary,os.O_RDONLY|os.O_DIRECTORY)
            try:
                def factory():return FilterJournal(Path(temporary),owner_uid=os.geteuid(),trusted_directory_fd=fd)
                first=factory();first.create(self.binding)
                self.publish(first)
                report=self.recover(factory)
                self.assertTrue(report['paired_complete_observed'])
                with factory().transaction() as tx:record=tx.read(self.binding.operation,self.binding.unit)
                self.assertEqual(record.lifecycle.phase,Phase.CANCELLED)
                self.assertEqual(record.paired.stage,PairedStage.COMPLETE)
                self.assertFalse(record.delivery_granted)
            finally:os.close(fd)


if __name__=='__main__':unittest.main()
